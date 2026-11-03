#!/usr/bin/env python3
"""Keypad-0 -> human escape, implemented at the PBX layer, outside the AI's own media path.

WHY THIS EXISTS
----------------
The project doc and CLAUDE.md both specify "pressing keypad 0 = unconditional PBX-level human
escape", including *while* the caller is bridged into the AI (extension 7000's
Dial(WebSocket/voicebot/...)). That cannot be done from inside agent/asterisk_bridge.py: once
Asterisk's Dial() has bridged the caller's channel into the WebSocket media channel, DTMF digits
on the caller's channel stop being interpreted as dialplan extensions (WaitExten() would do that,
but 7000's real dialplan uses Dial(), not WaitExten() -- see deploy/asterisk/extensions.conf's
docstring and voicebot/deploy/asterisk/LOCAL_VM_HANDOVER.md Sec.7 for why). The AI side only ever
sees DTMF as a logged DTMF_END control event (agent/asterisk_bridge.py); it has no channel-level
power to redirect the caller's own channel out of the bridge it's inside -- that is a PBX
operation, not an application one.

Asterisk's AMI (manager interface) *can* redirect ANY channel to a new dialplan location
regardless of what application currently owns it (Dial, Queue, Stasis, anything) -- a plain old
`Redirect` action, no ARI/Stasis needed. So this script is a small, standalone AMI client that:
  1. Watches Newexten events to know which channels are currently inside extension 7000's AI leg
     (Context=lab-internal, Extension=7000) -- cleared on Hangup or once the channel moves to a
     different extension (e.g. it already left on its own).
  2. On a DTMFEnd event with Digit=0, Direction=Received for a channel that's inside 7000 right
     now, issues Redirect(Context=lab-humans, Exten=s, Priority=1) for that channel -- the AI leg
     gets torn down (Dial() loses its bridge peer) and the ORIGINAL caller channel reappears in
     the human reception queue, exactly like exten 0's own direct-dial path already does.

This process must run continuously (systemd unit alongside Asterisk itself -- see
deploy/asterisk/ami-dtmf-transfer.service). It does nothing else: no media, no audio, just AMI
events in and one Redirect action out when the caller asks for a human.
"""

from __future__ import annotations

import socket
import sys
import time

HOST = "127.0.0.1"
PORT = 5038
USERNAME = "dtmf-bridge"
SECRET = "9d25a88151db63a019927337fa5897d6"  # deploy/asterisk/manager.conf's [dtmf-bridge] secret

WATCHED_CONTEXT = "lab-internal"
WATCHED_EXTEN = "7000"
TARGET_CONTEXT = "lab-humans"
TARGET_EXTEN = "s"
TARGET_PRIORITY = "1"


def _recv_blocks(sock: socket.socket):
    """Yields one dict of headers per AMI event/response block (blocks are CRLF CRLF terminated)."""
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("AMI connection closed")
        buf += chunk
        while b"\r\n\r\n" in buf:
            raw, buf = buf.split(b"\r\n\r\n", 1)
            headers: dict[str, str] = {}
            for line in raw.decode("utf-8", "replace").split("\r\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip()] = v.strip()
            if headers:
                yield headers


def _send_action(sock: socket.socket, **fields: str) -> None:
    payload = "".join(f"{k}: {v}\r\n" for k, v in fields.items()) + "\r\n"
    sock.sendall(payload.encode("utf-8"))


def run() -> None:
    in_ai_leg: set[str] = set()
    already_redirected: set[str] = set()

    while True:
        try:
            sock = socket.create_connection((HOST, PORT), timeout=10)
            sock.settimeout(None)
            sock.recv(4096)  # banner line, e.g. "Asterisk Call Manager/x.x.x"
            _send_action(sock, Action="Login", Username=USERNAME, Secret=SECRET)
            events = _recv_blocks(sock)
            login_reply = next(events)
            if login_reply.get("Response") != "Success":
                print(f"AMI login failed: {login_reply}", file=sys.stderr, flush=True)
                time.sleep(10)
                continue
            print("AMI dtmf-bridge connected and logged in", flush=True)

            for ev in events:
                event = ev.get("Event")
                channel = ev.get("Channel")
                if not event or not channel:
                    continue

                if event == "Newexten":
                    context = ev.get("Context")
                    exten = ev.get("Extension")
                    if context == WATCHED_CONTEXT and exten == WATCHED_EXTEN:
                        in_ai_leg.add(channel)
                    elif channel in in_ai_leg:
                        # moved on to a different extension on its own -- no longer our concern
                        in_ai_leg.discard(channel)
                        already_redirected.discard(channel)

                elif event == "Hangup":
                    in_ai_leg.discard(channel)
                    already_redirected.discard(channel)

                elif event == "DTMFEnd":
                    digit = ev.get("Digit")
                    direction = ev.get("Direction", "Received")
                    if (
                        digit == "0"
                        and direction == "Received"
                        and channel in in_ai_leg
                        and channel not in already_redirected
                    ):
                        already_redirected.add(channel)
                        print(f"keypad 0 on {channel} -- redirecting to human queue", flush=True)
                        _send_action(
                            sock,
                            Action="Redirect",
                            Channel=channel,
                            Context=TARGET_CONTEXT,
                            Exten=TARGET_EXTEN,
                            Priority=TARGET_PRIORITY,
                        )

        except (ConnectionError, OSError, socket.timeout) as e:
            print(f"AMI connection lost ({e}); reconnecting in 5s", file=sys.stderr, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    run()
