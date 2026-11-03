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
decision. The project doc and CLAUDE.md both treat "press 0 = unconditional PBX-level human escape" as
load-bearing behaviour, not something to improvise here. The architecturally clean way to do it is an
ARI subscription on the ORIGINAL caller channel (so it fires regardless of what this media leg is
doing) rather than this adapter's DTMF_END stream -- that is main.py's "live handoff lifecycle" piece
per the doc's file list, and needs a senior-python-architect pass + a live call to verify, not a guess
written while no VM/pod networking was even up yet. Similarly, send_text's "handoff_human" case is
intentionally a no-op (logged) for the same reason -- see agent/twilio_bridge.py's identical choice to
drop it for phone calls today.

CONFIGURATION
--------------
  ASTERISK_BRIDGE   "0" to not register the route at all (default: on)
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
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._reader: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._pending_marks: set = set()
        self._mark_seq = 0
        self._closed = False
        self.frames_in = 0
        self.frames_out = 0

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
                fmt = str(event.get("format", "")).lower()
                if fmt and fmt not in ("slin16", "sln16"):
                    raise AsteriskStreamRejected(f"unsupported media format {fmt!r}, expected slin16")
        logger.info("asterisk chan_websocket started: channel %s", self.channel_id)
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
        queued. handoff_human is intentionally a no-op here -- see module docstring."""
        try:
            kind = json.loads(text).get("type")
        except (TypeError, ValueError, AttributeError):
            return
        if kind == "stop_playback":
            self._pending_marks.clear()
            await self._send_text(asterisk_media.encode_flush_media())
        elif kind == "handoff_human":
            logger.info("handoff_human requested on asterisk channel %s -- not yet wired to an ARI transfer (see module docstring)", self.channel_id)

    async def close(self, code: int = 1000) -> None:
        """The agent hangs up (goodbye said, idle, handed to a human). Callers of close() already wait for their own
        audio to finish; this adds a short bounded wait for the last MARK_MEDIA ack, then tears down, which ends the
        Dial() and so the phone call."""
        deadline = time.monotonic() + DRAIN_CLOSE_S
        while self._pending_marks and not self._closed and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
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
