# Free SIP-trunk lab (Asterisk on the pod)

A self-contained Asterisk 22 PBX for testing hospital call flows without a
real Jio/Airtel SIP trunk -- patient softphone (2001) <-> fake hospital
number (7000, press-0 to escalate) <-> human agent softphone (1001). See
the project doc ("Free SIP Trunk dialler with bot Simulation") for the full
rationale; this directory is the runnable half of it.

Everything this needs lives on `/workspace`, so a pod restart (which wipes
`/` per `deploy/env.sh`) only costs you re-running `install_asterisk.sh`
(fast -- it skips the compile if `/workspace/pbx/sbin/asterisk` already
exists) rather than losing the setup.

## Bring it up on a fresh or restarted pod

```bash
cd /workspace/kolkata-care-voice-agent
bash deploy/asterisk/install_asterisk.sh     # ~5-10 min on a cold pod, seconds after that
bash deploy/asterisk/start_asterisk.sh
```

Lab extension passwords are printed at the end of `install_asterisk.sh` and
saved to `/workspace/.asterisk_secrets` (not committed, same pattern as
`.hf_token` / `.clinic_api_token` elsewhere in this repo).

## Softphone setup

| Extension | Who | Client |
|---|---|---|
| 2001 | patient (simulated caller) | Linphone (Android or desktop) |
| 1001 | agent | MicroSIP (Windows) |

SIP account fields (same for both, different username/password):
- Server / domain: the pod's current public IP (`echo $RUNPOD_PUBLIC_IP` on
  the pod -- **this changes every time the pod is recreated**, so re-check
  it before registering)
- Port: 5060 (or whatever `SIP_BIND_PORT` was set to)
- Transport: UDP
- Username / password: from `/workspace/.asterisk_secrets`

## The one thing that is NOT solved by this script: reachability

RunPod's default networking only maps **one TCP port** to the pod (22, for
SSH) plus an HTTP(S) reverse proxy on 8888. **Neither covers SIP, which
needs UDP** for both signaling (port 5060) and audio (RTP, see
`rtp.conf.template`'s range). Until RunPod is told to expose UDP (or extra
TCP ports, if going the SIP-over-TCP/TURN route instead), a phone outside
the pod's own private network cannot reach this Asterisk instance.

Check the pod's edit page on the RunPod dashboard for a UDP port option
before expecting an external softphone (e.g. Linphone on an Android phone
on mobile data) to register. A softphone running on the same machine as
this SSH session's `ssh -L`/port-forward, or on the pod's own private
network, is not affected by this and can be used to validate the dialplan
itself in the meantime.

## Files

- `install_asterisk.sh` -- idempotent build + config render
- `pjsip.conf.template`, `rtp.conf.template` -- rendered with the current
  pod's public IP and generated lab passwords (never hand-edit the
  rendered `.conf` files in `/workspace/pbx/etc/asterisk/`; re-run the
  install script instead so the IP stays current after a pod restart)
- `extensions.conf`, `queues.conf` -- copied in as-is
- `start_asterisk.sh` -- start/reload, same `setsid` + kill-by-port
  discipline as `deploy/start_all.sh`
