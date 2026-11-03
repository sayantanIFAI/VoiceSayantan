#!/bin/bash
# Installs Asterisk 22 on the local lab VM (Hospital-Asterisk-Lab, VirtualBox) -- a real persistent
# VM disk, not an ephemeral RunPod container, so standard paths + systemd are used directly (no
# /workspace indirection like deploy/asterisk/install_asterisk.sh needs on the pod).
#
#   sudo bash install_asterisk_local_vm.sh
set -eu

SRC=/usr/local/src
CONF_DIR=/etc/asterisk
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS=/root/.asterisk_secrets

export DEBIAN_FRONTEND=noninteractive
echo "== apt dependencies =="
apt-get update -qq
apt-get install -y -qq wget curl git tar build-essential pkg-config \
    python3 python3-venv openssl libedit-dev libjansson-dev \
    libxml2-dev libsqlite3-dev uuid-dev libssl-dev >/dev/null

if [ -x /usr/sbin/asterisk ]; then
    echo "== asterisk already installed, skipping compile =="
else
    echo "== fetching asterisk 22 source =="
    mkdir -p "$SRC"
    cd "$SRC"
    [ -f asterisk-22-current.tar.gz ] || wget -q https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-22-current.tar.gz
    rm -rf asterisk-22.*/ 2>/dev/null || true
    tar xzf asterisk-22-current.tar.gz
    cd asterisk-22.*/
    ./contrib/scripts/install_prereq install
    ./configure --with-pjproject-bundled
    make -j"$(nproc)"
    make install
    make samples
    make config
    ldconfig
fi

mkdir -p "$CONF_DIR"

echo "== lab credentials =="
if [ ! -f "$SECRETS" ]; then
    {
        echo "AGENT_1001_PASS=$(openssl rand -hex 16)"
        echo "CALLER_2001_PASS=$(openssl rand -hex 16)"
    } > "$SECRETS"
    chmod 600 "$SECRETS"
fi
# shellcheck disable=SC1090
source "$SECRETS"

LAPTOP_IP="${1:-}"
if [ -z "$LAPTOP_IP" ]; then
    echo "!! Usage: sudo bash install_asterisk_local_vm.sh <laptop-LAN-IP>"
    echo "   (the Windows laptop's own IP on your WiFi -- softphones/SIPp reach Asterisk through"
    echo "    NAT port-forwarding rules on that address, not the VM's own 10.0.2.15)"
    exit 1
fi

echo "== writing pjsip.conf / rtp.conf (external address: $LAPTOP_IP) =="
sed -e "s/REPLACE_WITH_AGENT_PASSWORD/${AGENT_1001_PASS}/" \
    -e "s/REPLACE_WITH_CALLER_PASSWORD/${CALLER_2001_PASS}/" \
    -e "s/REPLACE_WITH_BIND_PORT/5060/" \
    -e "s/REPLACE_WITH_PUBLIC_IP/${LAPTOP_IP}/" \
    /tmp/pjsip.conf.template > "$CONF_DIR/pjsip.conf"
sed -e "s/REPLACE_WITH_RTP_START/10000/" \
    -e "s/REPLACE_WITH_RTP_END/10010/" \
    /tmp/rtp.conf.template > "$CONF_DIR/rtp.conf"
cp /tmp/extensions.conf "$CONF_DIR/extensions.conf"
cp /tmp/queues.conf "$CONF_DIR/queues.conf"
cp /tmp/chan_websocket.conf "$CONF_DIR/chan_websocket.conf"
cp /tmp/manager.conf "$CONF_DIR/manager.conf"

echo "== installing keypad-0 -> human-queue AMI redirector =="
cp /tmp/ami_dtmf_transfer.py /opt/ami_dtmf_transfer.py
cp /tmp/ami-dtmf-transfer.service /etc/systemd/system/ami-dtmf-transfer.service
systemctl daemon-reload
systemctl enable --now ami-dtmf-transfer.service

echo "== starting asterisk via systemd =="
systemctl enable --now asterisk
sleep 2
systemctl status asterisk --no-pager | head -5

echo
echo "Done. Lab extensions:"
echo "  2001 (patient / Linphone) password: ${CALLER_2001_PASS}"
echo "  1001 (agent / MicroSIP)   password: ${AGENT_1001_PASS}"
echo "Point softphones at: $LAPTOP_IP : 5060 UDP (via NAT port-forward, not the VM's own IP)"
