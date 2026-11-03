# Local Asterisk lab VM — handover

**For:** a fresh Claude session (or person) picking this up with no memory of how it got here.
**Written:** 2026-11-03, mid-session, after Test A (two-way audio) passed.

Read this before touching anything. It names every credential, every gotcha already
hit, and exactly what's done vs. not.

## 1. What this is

A local VirtualBox VM (`Hospital-Asterisk-Lab`) running Asterisk 22, built to test a
hospital call flow (patient softphone -> PBX -> simulated hospital number -> human
queue) without a real SIP trunk, per the project doc "Free SIP Trunk dialler with bot
Simulation". The eventual goal is wiring this into the existing AI voicebot
(separate repo/pod, see §7) so a real phone call reaches the AI.

## 2. How to reach the VM right now

```
VM name:      Hospital-Asterisk-Lab (VirtualBox, on this Windows laptop)
VM network:   NAT (not bridged -- bridging over WiFi failed, see §6)
VM internal IP: 10.0.2.15 (NAT, not directly reachable)
SSH (from this laptop): ssh -p 2222 pbxlab@127.0.0.1
  - SSH key already installed in ~/.ssh/authorized_keys (passwordless, if using
    the same key as this session: C:\Users\Interviewer\.ssh\id_ed25519)
  - username: pbxlab   password: ifai  (needed for `sudo`)
```

**Start the VM:** VirtualBox -> select "Hospital-Asterisk-Lab" -> Start. Asterisk
auto-starts via systemd. NAT port-forward rules are saved in the VM's own VirtualBox
settings (persist across restarts, no need to re-add).

**The laptop's own WiFi/hotspot IP matters and can change.** Right now it's
`10.55.65.34` (while tethered to an Android phone's hotspot). This IP is what's
baked into Asterisk's `pjsip.conf` as `external_media_address` / what softphones
must dial. If the laptop reconnects to a different network, **this IP changes** and
`install_asterisk_local_vm.sh` (or a manual edit + `pjsip reload`) must be re-run
with the new IP, matching NAT port-forward rules updated too (see below).

## 3. NAT port-forwarding rules (already set, persisted in the VM's own config)

```
ssh:    tcp 127.0.0.1:2222 -> VM:22
sip:    udp  (all ifaces):5060 -> VM:5060
rtp*:   udp  (all ifaces):10000-10010 -> VM:10000-10010  (11 separate rules)
```
Added via `VBoxManage controlvm "Hospital-Asterisk-Lab" natpf1 "name,udp,,PORT,,PORT"`.

**Windows Firewall** also needed explicit inbound allow rules (added by the user,
as Administrator, since this is a security-sensitive action I can't do myself):
```powershell
New-NetFirewallRule -DisplayName "Asterisk Lab SIP" -Direction Inbound -Protocol UDP -LocalPort 5060 -Action Allow
New-NetFirewallRule -DisplayName "Asterisk Lab RTP" -Direction Inbound -Protocol UDP -LocalPort 10000-10010 -Action Allow
```

## 4. Lab extension credentials

| Ext | Who | Password | Auth |
|---|---|---|---|
| 1001 | Agent (MicroSIP, this laptop) | `2f907cb07b53555301f2438a43fe27a0` | **enabled**, works fine |
| 2001 | Patient (Linphone, Android phone) | (irrelevant) | **disabled** — see §6 |

Stored on the VM at `/root/.asterisk_secrets`. Softphone settings:
- **Server/Domain:** the laptop's current WiFi IP (`10.55.65.34` as of writing — verify first, see §2)
- **Port:** 5060, **Transport:** UDP, **Media Encryption:** None (Asterisk has no SRTP configured)

## 5. Status — what's actually been verified (not just "should work")

- ✅ Ubuntu 24.04.5 installed, booted, SSH works.
- ✅ Asterisk 22.11.0 compiled from source, running via systemd, auto-starts on boot.
- ✅ Both extensions (1001, 2001) **registered** — confirmed via `pjsip show contacts`.
- ✅ **Test A passed**: Linphone (2001) called 1001, MicroSIP answered, **real two-way
  audio confirmed** via `pjsip show channelstats` — hundreds of RTP packets each
  direction, 0% loss, after the §6 fix.
- ⬜ Test B (dial 7000, simulated hospital, beep) — not yet tried on this VM.
- ⬜ Test C (press 0 during 7000, routes to human queue) — not yet tried.
- ⬜ SIPp synthetic call test — not yet installed/run on this VM.
- ⬜ Connecting this Asterisk to the AI voicebot — the **bridge code itself already
  exists and is wired in** (see §7), just not yet pointed at this VM.

## 6. Two real bugs hit and fixed — don't re-debug these from scratch

1. **Bridged networking doesn't work for this VM.** VirtualBox bridging over WiFi
   generally fails (most WiFi adapters can't do the promiscuous-mode trick bridging
   needs) — the installer hung completely waiting on DHCP. Fixed by switching to
   **NAT + port-forwarding** instead (§3). Do not re-try Bridged.

2. **No audio despite both phones registering (THE** real **bug, not a red
   herring):** Asterisk was advertising its own internal NAT address (`10.0.2.15`)
   in the SDP/Contact instead of the laptop's real IP, because `pjsip.conf`'s
   `local_net` was set to `10.0.0.0/8` (inherited from a RunPod-pod-specific
   template) — that range is wide enough to **also match the real LAN addresses**
   (`10.55.65.x`), so Asterisk wrongly treated both phones as "local" and skipped
   the external-address rewrite. Fixed by narrowing `local_net` to `10.0.2.0/24`
   (just the VM's own NAT subnet) in `/etc/asterisk/pjsip.conf`'s `[lab-udp]`
   transport block, then `asterisk -rx 'pjsip reload'`. **If audio ever goes silent
   again after an IP change, check this first** — `local_net` must never overlap
   the real network's address range.

3. **Linphone Android (6.2.9, LinphoneSDK 5.5.37) has what looks like a genuine
   digest-auth bug.** Manually recomputed the RFC 2617 MD5 digest by hand (realm,
   nonce, username, password — all independently verified correct on both the
   phone's screen and Asterisk's live config) and it **never matched** what the
   phone sent, while MicroSIP's digest auth worked perfectly with the same
   Asterisk. Root cause unresolved; **workaround**: `auth=auth2001` is commented
   out in `[2001]`'s endpoint block in `pjsip.conf`, so extension 2001 registers
   with **no password check at all**. Acceptable only because this PBX is never
   exposed beyond the private hotspot network. If you want real auth back, try a
   different Android SIP client (e.g. Zoiper) first to confirm it's Linphone-
   specific before spending more time on it.

## 7. The other half: connecting to the AI voicebot

This is a **separate, already-running system** — not part of this VM. The voicebot
lives on a RunPod GPU pod (ephemeral IP/port, get current values from the user or
RunPod console — never trust an old one). Relevant work **already done there**:

- `agent/asterisk_bridge.py` / `agent/asterisk_media.py` — a WebSocket media bridge
  for Asterisk's `chan_websocket` driver, written to the same pattern as the
  existing `agent/twilio_bridge.py`. Protocol verified against Asterisk 22's actual
  source, not guessed.
- Wired into `main_pcm.py` via `tools/make_pcm_variant.py` (same mechanism as the
  Twilio bridge). Confirmed registered and running cleanly on the pod
  (`Asterisk bridge route registered: WS /asterisk/media` in the log).
- nginx route drafted (`deploy/gateway/asterisk_media_location.conf`) but **not
  yet pasted into the live gateway config or reloaded**.
- **DTMF/keypad-0 → human-transfer wiring is intentionally NOT implemented yet** —
  flagged in the code's own docstring as needing a live call + an ARI-based
  approach on the *original caller channel*, not guessed at blind.

**What's left to actually connect a real call to the AI:** point this VM's
Asterisk dialplan (extension 7000, or a new one) at a `Dial(WebSocket/...)` to a
`websocket_client.conf` entry targeting the pod's gateway URL, install the nginx
route, and test end-to-end. Nobody has done this yet — it's the next real step
once Test B/C pass locally.

## 8. Repo files (all already written, reusable as-is)

```
voicebot/deploy/asterisk/
  install_asterisk_local_vm.sh   -- what actually built this VM's Asterisk
  install_asterisk.sh            -- the ORIGINAL pod-oriented version (not used here)
  pjsip.conf.template, rtp.conf.template, extensions.conf, queues.conf
  LOCAL_VM_HANDOVER.md           -- this file
voicebot/agent/asterisk_bridge.py, asterisk_media.py   -- AI bridge (on the pod)
voicebot/deploy/gateway/asterisk_media_location.conf   -- nginx route (drafted, not live)
```
