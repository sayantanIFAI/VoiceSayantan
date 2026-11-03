#!/bin/bash
# Starts/restarts the lab Asterisk, same discipline as deploy/start_all.sh:
# setsid + </dev/null so it survives the SSH session closing, and killed
# by PORT when restarting, never by matching "asterisk" in a process list
# (that pattern is broad enough to catch other things on a shared pod).
#
#   bash /workspace/kolkata-care-voice-agent/deploy/asterisk/start_asterisk.sh
set -u

PBX=/workspace/pbx
LOG=/workspace/logs/asterisk/asterisk.log
mkdir -p /workspace/logs/asterisk

if [ ! -x "$PBX/sbin/asterisk" ]; then
    echo "!! $PBX/sbin/asterisk not found -- run install_asterisk.sh first"
    exit 1
fi

SIP_PORT="${SIP_BIND_PORT:-5060}"
if "$PBX/sbin/asterisk" -rx "core show version" >/dev/null 2>&1; then
    echo "Asterisk already running (re-reading configs)"
    "$PBX/sbin/asterisk" -rx "module reload res_pjsip.so" >/dev/null 2>&1
    "$PBX/sbin/asterisk" -rx "dialplan reload" >/dev/null 2>&1
    exit 0
fi

fuser -k "${SIP_PORT}/udp" >/dev/null 2>&1 || true
sleep 1

setsid "$PBX/sbin/asterisk" -f > "$LOG" 2>&1 < /dev/null &
disown

sleep 2
if "$PBX/sbin/asterisk" -rx "core show version" >/dev/null 2>&1; then
    echo "Asterisk started. SIP UDP port: $SIP_PORT"
    "$PBX/sbin/asterisk" -rx "pjsip show endpoints"
else
    echo "!! Asterisk did not come up -- check $LOG"
    exit 1
fi
