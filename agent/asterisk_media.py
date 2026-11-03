"""Control-message codec for Asterisk's chan_websocket media channel.

WHY THIS FILE EXISTS
---------------------
agent/asterisk_bridge.py needs to speak chan_websocket's JSON control protocol (commands it sends
Asterisk, events Asterisk sends back) without hand-rolling JSON dicts inline. This is the pure,
dependency-free half -- no FastAPI, no asyncio -- so it is trivial to unit test on its own.

Verified against Asterisk 22.11.0's actual source (channels/chan_websocket.c), not the project doc's
paraphrase of it: field names, which events carry a channel_id, which carry a correlation_id. The
module assumes chan_websocket.conf's control_message_format is "json" (not the legacy "plain-text"
single-line format) -- see deploy/asterisk/chan_websocket.conf in this repo.

Events Asterisk -> us (parse_event):
    MEDIA_START              -- call answered, media flowing; carries format/ptime/channel_variables
    DTMF_END                 -- caller pressed a digit (digit, channel_id)
    MEDIA_MARK_PROCESSED      -- a MARK_MEDIA we sent has finished playing (correlation_id)
    MEDIA_BUFFERING_COMPLETED -- a STOP_MEDIA_BUFFERING we sent was applied (correlation_id)
    STATUS                   -- reply to GET_DRIVER_STATUS (queue_length, queue_full, ...)
    ERROR                    -- something we asked for was rejected (error_text)
    MEDIA_XON / MEDIA_XOFF / QUEUE_DRAINED -- flow control, no extra fields

Commands us -> Asterisk (the encode_* functions): ANSWER, HANGUP, MARK_MEDIA, FLUSH_MEDIA,
GET_DRIVER_STATUS, START_MEDIA_BUFFERING, STOP_MEDIA_BUFFERING.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AsteriskEvent:
    """One decoded control message from Asterisk. `fields` holds whatever else the event carried
    (channel_id, correlation_id, digit, format, ...) -- named attributes would need one dataclass per
    event kind for little benefit, since callers only ever check a couple of fields per event type."""

    kind: str
    fields: dict = field(default_factory=dict)

    def get(self, name: str, default=None):
        return self.fields.get(name, default)


class AsteriskEventError(ValueError):
    """Raised by parse_event() when the text is not a well-formed chan_websocket JSON event."""


def parse_event(text: str) -> AsteriskEvent:
    """Decode one JSON text frame from chan_websocket. Raises AsteriskEventError on anything that
    is not a JSON object with an "event" string -- callers should drop/log, not crash the call on it,
    since a single unparseable control frame must not take down an otherwise-fine audio stream."""
    try:
        obj = json.loads(text)
    except (TypeError, ValueError) as e:
        raise AsteriskEventError(f"not valid JSON: {e}") from e
    if not isinstance(obj, dict) or not isinstance(obj.get("event"), str):
        raise AsteriskEventError("missing or non-string 'event' field")
    fields = {k: v for k, v in obj.items() if k != "event"}
    return AsteriskEvent(kind=obj["event"], fields=fields)


def _command(name: str, **extra) -> str:
    return json.dumps({"command": name, **extra}, separators=(",", ":"))


def encode_answer() -> str:
    """Only needed when the dialplan used Dial(WebSocket/.../n) (don't auto-answer); the default
    behaviour answers the channel as soon as the websocket connects, before our code even runs."""
    return _command("ANSWER")


def encode_hangup() -> str:
    return _command("HANGUP")


def encode_mark_media(correlation_id: str) -> str:
    """The playback-done signal: send this right after writing a reply's audio bytes. Asterisk
    echoes MEDIA_MARK_PROCESSED with the same correlation_id once that audio has actually finished
    playing to the caller -- the same role Twilio's "mark" event plays in agent/twilio_bridge.py."""
    return _command("MARK_MEDIA", correlation_id=correlation_id)


def encode_flush_media() -> str:
    """Drops whatever audio Asterisk has buffered but not yet played -- the barge-in primitive,
    equivalent to Twilio's "clear" event (agent/twilio_bridge.py's stop_playback handling)."""
    return _command("FLUSH_MEDIA")


def encode_get_driver_status() -> str:
    return _command("GET_DRIVER_STATUS")


def encode_start_media_buffering() -> str:
    return _command("START_MEDIA_BUFFERING")


def encode_stop_media_buffering(correlation_id: str) -> str:
    return _command("STOP_MEDIA_BUFFERING", correlation_id=correlation_id)
