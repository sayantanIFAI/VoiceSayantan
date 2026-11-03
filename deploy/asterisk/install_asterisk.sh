#!/bin/bash
# Installs and configures Asterisk 22 for the free SIP-trunk lab (no Twilio,
# no carrier trunk -- see "Free SIP Trunk dialler with bot Simulation" doc).
#
# Everything that must survive a pod restart lives under /workspace, same
# rule as the rest of this repo (deploy/env.sh): RunPod wipes "/" on every
# restart. Asterisk is therefore built with --prefix=/workspace/pbx, so the
# compiled binary, modules, sounds and configs all live on the persistent
# volume. apt packages (build-essential, etc.) are ephemeral and get
# reinstalled by this script every time -- that is expected and cheap.
#
#   bash /workspace/kolkata-care-voice-agent/deploy/asterisk/install_asterisk.sh
#
# Idempotent: skips the compile step if /workspace/pbx/sbin/asterisk already
# exists, and never overwrites configs/secrets that are already in place.
set -eu

PBX=/workspace/pbx
SRC=/workspace/src
CONF_DIR="$PBX/etc/asterisk"
SECRETS=/workspace/.asterisk_secrets
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== build dependencies (apt, ephemeral) =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq wget curl git tar build-essential pkg-config \
    python3 python3-venv openssl libedit-dev libjansson-dev \
    libxml2-dev libsqlite3-dev uuid-dev libssl-dev >/dev/null

if [ -x "$PBX/sbin/asterisk" ]; then
    echo "== asterisk already built at $PBX/sbin/asterisk, skipping compile =="
else
    echo "== fetching asterisk 22 source =="
    mkdir -p "$SRC"
    cd "$SRC"
    if [ ! -f asterisk-22-current.tar.gz ]; then
        wget -q https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-22-current.tar.gz
    fi
    rm -rf asterisk-22.*/ 2>/dev/null || true
    tar xzf asterisk-22-current.tar.gz
    cd asterisk-22.*/

    echo "== install_prereq (asterisk's own dependency installer) =="
    ./contrib/scripts/install_prereq install

    echo "== configure (prefix=$PBX, bundled pjproject) =="
    ./configure --prefix="$PBX" --with-pjproject-bundled

    echo "== compile (this takes several minutes) =="
    make -j"$(nproc)"

    echo "== install =="
    make install
    make samples     # only safe because this is a disposable lab install
    make config DESTDIR=/tmp/ast-systemd-unused  # don't touch the pod's real systemd (there isn't one -- container)
fi

mkdir -p "$CONF_DIR" /workspace/logs/asterisk /workspace/pbx/var/spool/asterisk

echo "== lab credentials =="
mkdir -p "$(dirname "$SECRETS")"
if [ ! -f "$SECRETS" ]; then
    {
        echo "AGENT_1001_PASS=$(openssl rand -hex 16)"
        echo "CALLER_2001_PASS=$(openssl rand -hex 16)"
    } > "$SECRETS"
    chmod 600 "$SECRETS"
    echo "  generated new lab passwords in $SECRETS"
else
    echo "  reusing existing $SECRETS"
fi
# shellcheck disable=SC1090
source "$SECRETS"

echo "== writing pjsip.conf / extensions.conf / queues.conf =="
PUBLIC_IP="${RUNPOD_PUBLIC_IP:-$(curl -s -m 5 ifconfig.me || echo 127.0.0.1)}"
sed -e "s/REPLACE_WITH_AGENT_PASSWORD/${AGENT_1001_PASS}/" \
    -e "s/REPLACE_WITH_CALLER_PASSWORD/${CALLER_2001_PASS}/" \
    -e "s/REPLACE_WITH_BIND_PORT/${SIP_BIND_PORT:-5060}/" \
    -e "s/REPLACE_WITH_PUBLIC_IP/${PUBLIC_IP}/" \
    "$HERE/pjsip.conf.template" > "$CONF_DIR/pjsip.conf"
sed -e "s/REPLACE_WITH_RTP_START/${SIP_RTP_START:-10000}/" \
    -e "s/REPLACE_WITH_RTP_END/${SIP_RTP_END:-10020}/" \
    "$HERE/rtp.conf.template" > "$CONF_DIR/rtp.conf"
cp "$HERE/extensions.conf" "$CONF_DIR/extensions.conf"
cp "$HERE/queues.conf" "$CONF_DIR/queues.conf"

echo
echo "Done. Lab extensions:"
echo "  2001 (patient / Linphone) password: ${CALLER_2001_PASS}"
echo "  1001 (agent / MicroSIP)   password: ${AGENT_1001_PASS}"
echo
echo "Start it with: bash $HERE/start_asterisk.sh"
echo "Secrets file (not in git):          $SECRETS"
