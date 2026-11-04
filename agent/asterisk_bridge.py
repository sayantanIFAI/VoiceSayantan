"""Asterisk phone-call transport for the PCM voice agent, via chan_websocket (Asterisk 22.8+).

WHY THIS FILE EXISTS
---------------------
agent/twilio_bridge.py already proved the pattern: make a telephony transport LOOK LIKE the browser
WebSocket that ws_audio() expects, so none of the turn logic (VAD, ASR, intent, booking, TTS,
half-duplex gate, barge-in) has to change. This file does the same thing for a SIP call arriving
through the project's own Asterisk lab PBX (deploy/asterisk/) instead of through Twilio:

    caller's SIP phone --RTP--> Asterisk extension 7000 --Dial(WebSocket/voicebot)--> wss:// (this file)
                                                                                           |
                                                                                  the SAME ws_audio() turn loop

THE PROTOCOL (verified against Asterisk 22.11.0 source, channels/chan_websocket.c -- not assumed
from the project doc's paraphrase of it)
--------------------------------------------------------------------------------------------------
Asterisk is dialled with a codec of "slin16": 16 kHz signed-linear PCM, the SAME rate the agent's
buffer already runs at (agent/pcm_buffer.py SAMPLE_RATE). Unlike Twilio (always 8 kHz mu-law), there
is no codec conversion on the inbound path at all -- audio bytes go straight into the agent.

    ws_audio calls                      the adapter does
    -----------------------------       -------------------------------------------------------------------------
    await ws.accept()                   waits for chan_websocket's MEDIA_START event (agent/asterisk_media.py)
    await ws.receive()  (bytes)         binary frame = 16 kHz PCM16LE already, forwarded unchanged
    await ws.receive()  (text)          MEDIA_MARK_PROCESSED for our last MARK_MEDIA -> {"type":"playback_done"}
    await ws.send_bytes(wav)            WAV -> 16 kHz PCM16LE -> binary frames, then MARK_MEDIA to learn when played
    await ws.send_text('{"type":"stop_playback"}')   -> FLUSH_MEDIA command (drops queued audio: barge-in)
    await ws.close()                    lets queued audio finish (bounded), then HANGUP + close (call ends)

AUTHENTICATION
---------------
Unlike Twilio's media stream (which cannot present credentials, hence the HMAC stream-token scheme in
twilio_bridge.py), Asterisk's res_websocket_client natively supports HTTP Basic Auth (username/password
in websocket_client.conf). So the gateway's nginx route for this path (deploy/gateway/nginx.conf,
location /asterisk-media/) can simply keep auth_basic ON with its own dedicated htpasswd entry -- no
token scheme needed here. This adapter does not re-check anything; the gateway already did.

WHAT IS DELIBERATELY NOT DONE HERE YET (open design question, not a bug)
--------------------------------------------------------------------------------------------------
DTMF_END events (caller pressed a keypad digit) are logged but NOT translated into the human-handoff
decision from THIS adapter -- keypad 0 is handled independently, at the PBX layer, by
deploy/asterisk/ami_dtmf_transfer.py (an AMI client on the Oracle VM watching DTMFEnd events directly
on the caller's own channel, which is immune to whatever this media leg is doing -- see that script's
module docstring for why that has to be PBX-side, not here).

AI-INITIATED HANDOFF (send_text's "handoff_human" case)
--------------------------------------------------------------------------------------------------
When main.py's _handoff_to_human() decides (deterministically -- agent/human_request.py,
agent/lid.py's ambiguous-streak rule, emergency/abuse/complaint guards, never the LLM) that the
caller needs a person, it sends a `{"type": "handoff_human", "reason": ...}` text frame down the
same WebSocket this adapter wraps, then plays the spoken notice, then calls close(). This adapter:
  1. On the frame: records the reason only. Redirecting the caller's channel immediately would tear
     down this Dial() leg right then (ami_dtmf_transfer.py's own docstring: a Redirect ends the AI
     leg's bridge) and cut the spoken notice off mid-sentence.
  2. On close() (called only once that notice has finished playing): POSTs to the Oracle VM's
     /transfer endpoint (ami_dtmf_transfer.py's EXTERNAL TRANSFER REQUESTS listener) with this
     channel's id, asking for the exact same AMI Redirect keypad-0 triggers. Best-effort: if it
     fails, the call still ends via the normal HANGUP path below, same as before this existed.
This is OFF by default -- see CONFIGURATION. Until both env vars are set, the frame is only logged,
exactly as before (agent/twilio_bridge.py keeps dropping it for phone calls the same way).

CONFIGURATION
--------------
  ASTERISK_BRIDGE          "0" to not register the route at all (default: on)
  ASTERISK_TRANSFER_URL    Oracle VM's transfer endpoint, e.g. "http://<oracle-host>:8091/transfer"
                            (deploy/asterisk/ami_dtmf_transfer.py). Unset = handoff_human is logged
                            only, nothing is redirected (today's behaviour, unchanged).
  ASTERISK_TRANSFER_TOKEN  must match that script's TRANSFER_TOKEN. Both unset together is the safe
                            default; setting one without the other also leaves this a no-op.
  ASTERISK_TRANSFER_BASIC_USER / _PASS   only if the Oracle side sits behind
                            deploy/asterisk/transfer_gateway_nginx.conf's Basic-Auth front door.
  ASTERISK_TRANSFER_CA_CERT  path to a pinned cert for TLS verification (e.g. a copy of that
                            gateway's self-signed cert). Unset = normal system CA verification,
                            which fails closed against a self-signed cert -- never silently trusts one.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import hashlib
import io
import json
import logging
import os
import time
import uuid
import wave

import numpy as np

try:  # fastapi is always present in the running app; the guard only keeps this importable standalone
    from fastapi import WebSocket
    from starlette.websockets import WebSocketDisconnect
except ImportError:  # pragma: no cover
    WebSocket = None  # type: ignore[assignment,misc]

    class WebSocketDisconnect(Exception):  # type: ignore[no-redef]
        pass

from agent import asterisk_media
from agent.asterisk_media import AsteriskEventError
from agent.twilio_bridge import _lowpass_taps, _sinc_interp  # reuse the proven windowed-sinc resampler, not a duplicate

logger = logging.getLogger("asterisk_bridge")

AGENT_RATE = 16000  # agent/pcm_buffer.py SAMPLE_RATE; also the "slin16" codec's rate, so inbound audio needs no conversion
START_TIMEOUT_S = 10.0  # how long a new WebSocket channel may take to send MEDIA_START
DRAIN_CLOSE_S = 2.0  # close() waits at most this long for a queued MARK_MEDIA to come back
_SEND_CHUNK_BYTES = 3200  # 100ms of 16kHz/16-bit mono PCM; keeps every outbound WS frame well under
# Asterisk res_http_websocket's frame-size ceiling (observed closing the connection with 1009
# "Message too big" on a ~116 KB single-frame clip)
_CONVERT_CACHE_MAX = 128  # converted reply clips kept (pinned catalogue answers repeat constantly)

_DISCONNECT = {"type": "websocket.disconnect"}

# AI-initiated handoff (module docstring). Both unset (the default) keeps handoff_human a no-op,
# same as before this existed. The other three are optional, for when the Oracle side sits behind
# the TLS + Basic-Auth front door in deploy/asterisk/transfer_gateway_nginx.conf rather than being
# reached directly: unset, httpx just does normal system CA verification (fails closed against a
# self-signed cert, which is the safe default -- it does not silently accept anything).
ASTERISK_TRANSFER_URL = os.environ.get("ASTERISK_TRANSFER_URL", "")
ASTERISK_TRANSFER_TOKEN = os.environ.get("ASTERISK_TRANSFER_TOKEN", "")
ASTERISK_TRANSFER_BASIC_USER = os.environ.get("ASTERISK_TRANSFER_BASIC_USER", "")
ASTERISK_TRANSFER_BASIC_PASS = os.environ.get("ASTERISK_TRANSFER_BASIC_PASS", "")
ASTERISK_TRANSFER_CA_CERT = os.environ.get("ASTERISK_TRANSFER_CA_CERT", "")  # path, e.g. a copy of the gateway's self-signed cert
_TRANSFER_REQUEST_TIMEOUT_S = 4.0


async def _request_pbx_transfer(channel_id: str, reason: str) -> bool:
    """Asks deploy/asterisk/ami_dtmf_transfer.py's external-transfer listener (on the Oracle VM) to
    Redirect this caller's channel to the human queue -- the same AMI action keypad-0 triggers there.
    No-op, logged, until both ASTERISK_TRANSFER_URL and ASTERISK_TRANSFER_TOKEN are set. Best-effort:
    a failure here is logged and swallowed, same discipline as _route_to_human_placeholder in main.py
    -- the caller has already heard the handoff notice either way, and the call still ends normally."""
    if not ASTERISK_TRANSFER_URL or not ASTERISK_TRANSFER_TOKEN:
        logger.info(
            "handoff_human on asterisk channel %s (%s) -- ASTERISK_TRANSFER_URL/TOKEN not set, not wired",
            channel_id, reason,
        )
        return False
    try:
        import httpx  # lazy import, same reasoning as main.py's _route_to_human_placeholder

        kwargs: dict = {"timeout": _TRANSFER_REQUEST_TIMEOUT_S}
        if ASTERISK_TRANSFER_BASIC_USER and ASTERISK_TRANSFER_BASIC_PASS:
            kwargs["auth"] = (ASTERISK_TRANSFER_BASIC_USER, ASTERISK_TRANSFER_BASIC_PASS)
        if ASTERISK_TRANSFER_CA_CERT:
            kwargs["verify"] = ASTERISK_TRANSFER_CA_CERT
        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.post(
                ASTERISK_TRANSFER_URL,
                json={
                    "channel_id": channel_id,
                    "request_id": str(uuid.uuid4()),
                    "token": ASTERISK_TRANSFER_TOKEN,
                },
            )
        if resp.status_code == 200:
            logger.info("asterisk channel %s transfer requested (%s): %s", channel_id, reason, resp.text)
            return True
        logger.warning("asterisk transfer request for %s failed: HTTP %s", channel_id, resp.status_code)
        return False
    except Exception as e:  # noqa: BLE001 - best effort; see docstring above
        logger.warning("asterisk transfer request for %s failed: %s", channel_id, e)
        return False


# ================================================================================================ outbound audio codec


def _resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """TTS replies may be 22.05/24/16 kHz (agent/twilio_bridge.py's resample_to_8k docstring); Asterisk wants exactly
    AGENT_RATE. Flow: anti-alias low-pass at the source rate when downsampling, then windowed-sinc interpolation onto
    the destination grid -- the same two-step method twilio_bridge.py uses for its 8 kHz leg, generalised to any
    destination rate instead of a hardcoded one. A same-rate WAV (the common case) skips both steps."""
    x = np.asarray(samples, dtype=np.float32)
    if src_rate == dst_rate or x.size == 0:
        return x
    if src_rate > dst_rate:
        x = np.convolve(x, _lowpass_taps(min(3600.0, dst_rate / 2.0 - 100.0), src_rate), mode="same")
    n_out = int(x.size * dst_rate / float(src_rate))
    positions = np.arange(n_out) * (src_rate / float(dst_rate))
    return _sinc_interp(x, positions)


def wav_to_pcm16_agent_rate(wav_bytes: bytes) -> bytes:
    """Every reply the agent speaks is a WAV (agent/tts.py). Flow: parse the WAV header, take the samples (8/16/32-bit
    PCM, any channel count -> mono), resample to AGENT_RATE, return raw PCM16LE bytes (chan_websocket's "slin16"
    wire format -- no mu-law, no base64, just the samples). Raises ValueError/wave.Error for anything unreadable."""
    with contextlib.closing(wave.open(io.BytesIO(wav_bytes), "rb")) as w:
        channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(frames)
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    elif width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 65536.0
    else:
        raise ValueError(f"unsupported WAV sample width {width}")
    if channels > 1:
        x = x[: x.size - x.size % channels].reshape(-1, channels).mean(axis=1)
    y = _resample(x, rate, AGENT_RATE)
    return np.clip(np.rint(y), -32768, 32767).astype("<i2").tobytes()


_convert_cache: "collections.OrderedDict[str, bytes]" = collections.OrderedDict()


def wav_to_pcm16_agent_rate_cached(wav_bytes: bytes) -> bytes:
    """Same reasoning as agent/twilio_bridge.py's wav_to_mulaw_8k_cached: pinned catalogue answers repeat constantly
    and cost 0 ms to synthesise, so converting the same bytes again on every call would throw that saving away."""
    key = hashlib.sha1(wav_bytes).hexdigest()
    hit = _convert_cache.get(key)
    if hit is not None:
        _convert_cache.move_to_end(key)
        return hit
    out = wav_to_pcm16_agent_rate(wav_bytes)
    _convert_cache[key] = out
    while len(_convert_cache) > _CONVERT_CACHE_MAX:
        _convert_cache.popitem(last=False)
    return out


# ====================================================================================== WebSocket adapter for ws_audio


class AsteriskStreamRejected(Exception):
    """Raised when a chan_websocket connection must not be served (no MEDIA_START, wrong codec)."""


class AsteriskStreamAdapter:
    """Makes one Asterisk chan_websocket connection look like the browser WebSocket ws_audio() already uses (see the
    table in the module docstring). One adapter per call. Only the methods ws_audio and CallSession call are
    provided: accept / receive / send_bytes / send_text / close."""

    phone_line = True  # a telephone leg: trusts barge-in without the browser echo-canceller convergence rule (agent/full_duplex.py)

    def __init__(self, ws, *, start_timeout_s: float = START_TIMEOUT_S) -> None:
        self._ws = ws
        self._start_timeout_s = start_timeout_s
        self.channel_id: str | None = None
        # The ORIGINAL caller's channel name (e.g. "PJSIP/2001-00000017") -- NOT self.channel_id, which
        # is this media/WebSocket leg's own uniqueid (chan_websocket.c: ast_channel_uniqueid(instance->channel)).
        # Redirecting the caller to the human queue needs the CALLER's channel, the one
        # deploy/asterisk/ami_dtmf_transfer.py's AMI watcher tracks (Newexten's Channel field) -- confirmed by
        # reading chan_websocket.c directly, not guessed, after a live test sent the media channel's id and got
        # "channel not in AI leg" back. extensions.conf sets __CALLER_CHANNEL on the caller's channel before
        # Dial(); the "__" prefix makes Asterisk inherit it onto this new WebSocket channel, so it shows up here
        # in MEDIA_START's channel_variables. None until a call using the updated dialplan connects.
        self.caller_channel_id: str | None = None
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._reader: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._pending_marks: set = set()
        self._mark_seq = 0
        self._closed = False
        self.frames_in = 0
        self.frames_out = 0
        self._pending_transfer_reason: str | None = None

    # -- handshake ---------------------------------------------------------------------------------------------

    async def accept(self) -> None:
        """ws_audio's first line. The real WebSocket is already accepted by the route; what remains is Asterisk's
        handshake. Flow: read control frames until MEDIA_START, record the channel_id, then start the reader."""
        deadline = time.monotonic() + self._start_timeout_s
        while self.channel_id is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AsteriskStreamRejected("no MEDIA_START event from Asterisk in time")
            try:
                message = await asyncio.wait_for(self._ws.receive(), timeout=remaining)
            except (asyncio.TimeoutError, TimeoutError):
                raise AsteriskStreamRejected("no MEDIA_START event from Asterisk in time") from None
            if message.get("type") == "websocket.disconnect":
                raise AsteriskStreamRejected("channel closed before MEDIA_START")
            text = message.get("text")
            if not text:
                continue  # a binary frame arriving before MEDIA_START would be unexpected; ignore rather than reject
            try:
                event = asterisk_media.parse_event(text)
            except AsteriskEventError:
                continue
            if event.kind == "MEDIA_START":
                self.channel_id = event.get("channel_id") or ""
                variables = event.get("channel_variables") or {}
                if isinstance(variables, dict):
                    # Asterisk's ast_channel_inherit_variables (main/channel.c) stores a "__"-prefixed
                    # inherited variable on the CHILD channel under its FULL name, prefix included --
                    # it does NOT strip it the way a single "_" prefix does. Confirmed by reading that
                    # function directly after a live test with the unprefixed key always came back None.
                    self.caller_channel_id = variables.get("__CALLER_CHANNEL") or None
                fmt = str(event.get("format", "")).lower()
                if fmt and fmt not in ("slin16", "sln16"):
                    raise AsteriskStreamRejected(f"unsupported media format {fmt!r}, expected slin16")
        logger.info(
            "asterisk chan_websocket started: channel %s (caller channel %s)",
            self.channel_id, self.caller_channel_id or "unknown -- extensions.conf not yet updated?",
        )
        self._reader = asyncio.ensure_future(self._read_loop())

    # -- inbound -----------------------------------------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Mirrors agent/twilio_bridge.py's _read_loop: receive() must be able to return synthetic events too, so
        Asterisk's socket is read in one place. audio frame -> forwarded as-is (already 16 kHz PCM16LE); mark ack ->
        playback_done once every pending mark has come back; DTMF -> logged only, see module docstring."""
        try:
            while True:
                message = await self._ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                audio = message.get("bytes")
                if audio:
                    self.frames_in += 1
                    self._inbox.put_nowait({"type": "websocket.receive", "bytes": audio})
                    continue
                text = message.get("text")
                if not text:
                    continue
                try:
                    event = asterisk_media.parse_event(text)
                except AsteriskEventError:
                    continue
                if event.kind == "MEDIA_MARK_PROCESSED":
                    name = event.get("correlation_id")
                    if name in self._pending_marks:
                        self._pending_marks.discard(name)
                        if not self._pending_marks:
                            self._inbox.put_nowait({"type": "websocket.receive", "text": json.dumps({"type": "playback_done"})})
                elif event.kind == "DTMF_END":
                    logger.info("asterisk DTMF on channel %s: %s", self.channel_id, event.get("digit"))
                elif event.kind == "ERROR":
                    logger.warning("asterisk chan_websocket error on channel %s: %s", self.channel_id, event.get("error_text"))
        except (WebSocketDisconnect, RuntimeError):
            pass
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the call must end cleanly, not leave the turn loop waiting forever
            logger.exception("asterisk chan_websocket reader failed")
        finally:
            self._closed = True
            self._inbox.put_nowait(_DISCONNECT)

    async def receive(self) -> dict:
        """What ws_audio's loop awaits. Returns the next queued message; once the channel has ended it keeps
        returning a disconnect so the loop exits."""
        if self._closed and self._inbox.empty():
            return _DISCONNECT
        return await self._inbox.get()

    # -- outbound ----------------------------------------------------------------------------------------------

    async def _send_text(self, payload: str) -> bool:
        async with self._send_lock:
            if self._closed:
                return False
            try:
                await self._ws.send_text(payload)
                return True
            except Exception:  # noqa: BLE001 - a dead socket means the caller hung up
                self._closed = True
                return False

    async def _send_bytes(self, data: bytes) -> bool:
        async with self._send_lock:
            if self._closed:
                return False
            try:
                await self._ws.send_bytes(data)
                return True
            except Exception:  # noqa: BLE001
                self._closed = True
                return False

    def _release_gate_now(self) -> None:
        """A reply that could not be played must not leave the agent waiting for a 'finished playing' that never comes."""
        self._inbox.put_nowait({"type": "websocket.receive", "text": json.dumps({"type": "playback_done"})})

    async def send_bytes(self, wav_bytes: bytes) -> None:
        """Where every spoken reply leaves. Flow: WAV -> 16 kHz PCM16LE (worker thread, cached for repeat clips) ->
        a run of small binary frames -> MARK_MEDIA so Asterisk tells us when the clip has actually finished playing.

        Chunked, not one frame: a whole clip's PCM (easily 100+ KB) sent as a single WebSocket binary frame makes
        Asterisk's res_http_websocket client log "Cannot fit huge websocket frame" and close the connection with
        1009 (Message too big), killing the call before any audio plays -- confirmed live, this is not a guess.
        _SEND_CHUNK_BYTES keeps every frame well under that ceiling."""
        if self._closed or not self.channel_id or not wav_bytes:
            return
        try:
            pcm = await asyncio.to_thread(wav_to_pcm16_agent_rate_cached, wav_bytes)
        except Exception as e:  # noqa: BLE001 - wave.Error, ValueError, anything odd in a fallback clip
            logger.warning("could not convert a reply clip for Asterisk (%s) -- skipped", e)
            self._release_gate_now()
            return
        if not pcm:
            self._release_gate_now()
            return
        for offset in range(0, len(pcm), _SEND_CHUNK_BYTES):
            if not await self._send_bytes(pcm[offset : offset + _SEND_CHUNK_BYTES]):
                return
        self.frames_out += 1
        self._mark_seq += 1
        name = f"clip{self._mark_seq}"
        self._pending_marks.add(name)
        await self._send_text(asterisk_media.encode_mark_media(name))

    async def send_text(self, text: str) -> None:
        """The browser protocol also carries JSON text (transcript lines, pings, config, handoff notices). The one
        that matters today is stop_playback (the caller talked over the agent): FLUSH_MEDIA drops what Asterisk has
        queued. handoff_human only records the reason here -- the actual PBX transfer request is deferred to
        close(), which runs once the spoken handoff notice has finished playing (see module docstring)."""
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, AttributeError):
            return
        kind = payload.get("type")
        if kind == "stop_playback":
            self._pending_marks.clear()
            await self._send_text(asterisk_media.encode_flush_media())
        elif kind == "handoff_human":
            self._pending_transfer_reason = str(payload.get("reason") or "")
            logger.info(
                "handoff_human queued on asterisk channel %s (caller %s) (%s), transfer requested at close",
                self.channel_id, self.caller_channel_id, self._pending_transfer_reason,
            )

    async def close(self, code: int = 1000) -> None:
        """The agent hangs up (goodbye said, idle, handed to a human). Callers of close() already wait for their own
        audio to finish; this adds a short bounded wait for the last MARK_MEDIA ack, then -- if a handoff_human
        frame was queued (send_text) and the channel is still alive -- asks the Oracle VM's PBX to redirect the
        caller to the human queue, before tearing down, which ends the Dial() and so this WebSocket leg.

        Uses caller_channel_id, NOT channel_id: the Oracle-side AMI watcher (deploy/asterisk/ami_dtmf_transfer.py)
        tracks the CALLER's own channel (its Newexten watcher sees that channel entering extension 7000), never
        this media leg's channel -- confirmed live (see caller_channel_id's own docstring). Without
        caller_channel_id (extensions.conf not yet updated with __CALLER_CHANNEL, or an old call predating it),
        this is skipped rather than sent with the wrong id, which would only draw a harmless but noisy 404."""
        deadline = time.monotonic() + DRAIN_CLOSE_S
        while self._pending_marks and not self._closed and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if self._pending_transfer_reason is not None and not self._closed:
            if self.caller_channel_id:
                await _request_pbx_transfer(self.caller_channel_id, self._pending_transfer_reason)
            else:
                logger.warning(
                    "handoff_human on asterisk channel %s could not be requested -- no caller_channel_id "
                    "(extensions.conf's __CALLER_CHANNEL not seen in this call's MEDIA_START)",
                    self.channel_id,
                )
        await self.aclose(code)

    async def aclose(self, code: int = 1000) -> None:
        """Immediate, idempotent teardown used by the route's finally block: HANGUP the channel, stop the reader,
        make any receive() return a disconnect, close the real socket."""
        first = not self._closed
        self._closed = True
        if first:
            with contextlib.suppress(Exception):
                await self._ws.send_text(asterisk_media.encode_hangup())
            self._inbox.put_nowait(_DISCONNECT)
        if self._reader is not None and not self._reader.done():
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
        with contextlib.suppress(Exception):
            await self._ws.close(code)


# ============================================================================================================ routes


def install(app, ws_audio_handler) -> None:
    """Registers the Asterisk route on the FastAPI app. Called once from main_pcm.py (before the static-files
    mount, which would otherwise swallow this path), passing the agent's own ws_audio so a phone call through the
    lab PBX runs the identical turn loop as every other transport. ASTERISK_BRIDGE=0 skips it.

    WS /asterisk/media  chan_websocket connects here (via websocket_client.conf, proxied by the gateway's
                         /asterisk-media/ location, auth_basic protected -- see module docstring)."""
    if os.environ.get("ASTERISK_BRIDGE", "1").strip().lower() in ("0", "false", "no", "off"):
        logger.info("Asterisk bridge disabled by ASTERISK_BRIDGE")
        return

    @app.websocket("/asterisk/media")
    async def asterisk_media_ws(ws: WebSocket):
        # Flow: accept the socket -> wrap it in the adapter -> run the agent's normal ws_audio on it. ws_audio's own
        # first line (adapter.accept) does the chan_websocket handshake; a rejected stream is closed with 1008.
        await ws.accept()
        adapter = AsteriskStreamAdapter(ws)
        try:
            await ws_audio_handler(adapter)
        except AsteriskStreamRejected as e:
            logger.warning("Asterisk stream refused: %s", e)
            await adapter.aclose(1008)
        except Exception:  # noqa: BLE001
            logger.exception("Asterisk stream crashed")
        finally:
            await adapter.aclose()
            logger.info("asterisk stream ended (frames in %d, out %d)", adapter.frames_in, adapter.frames_out)

    logger.info("Asterisk bridge route registered: WS /asterisk/media")
