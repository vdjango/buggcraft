# DataChannel-only WebRTC

Derived from aiortc **1.15.0** under its BSD-3-Clause license. Copyright (c)
Jeremy Lainé. The full upstream license is in `LICENSE`; `UPSTREAM.json`
records the original and generated SHA-256 for each retained module.

The launcher forwards game TCP streams over ordered, reliable SCTP data
channels. It does not record or transmit audio/video. This subset retains the
upstream ICE checks, SCTP implementation, DataChannel handling, certificate
generation, DTLS encryption and peer-fingerprint verification. Signaling and
stream framing retain their existing formats, with SSH relay fallback.

Removed: audio/video tracks, codec negotiation, RTP routing, SRTP sessions,
PyAV, FFmpeg and the native SRTP dependency. SDP parsing retains upstream's
data structures so both modern and legacy SCTP descriptions remain readable.
Only one `m=application` section is accepted. Media track APIs fail explicitly.

DTLS still advertises the standard SRTP protection-profile extension. This
small OpenSSL extension is needed to interoperate with old aiortc clients,
which require an SRTP profile even for a data-only connection. No SRTP library
or RTP processing is present in this subset. Certificate checks and the DTLS
cipher list are preserved from upstream; cryptography and pyOpenSSL remain
dependencies, rather than replacing security primitives with custom code.

## Reproduce

Use a separate development environment with `aiortc==1.15.0`. It is not a
launcher runtime dependency. On Windows, for example:

```powershell
python scripts/vendor_rtc_datachannel.py `
  --source .venv/Lib/site-packages/aiortc `
  --license .venv/Lib/site-packages/aiortc-1.15.0.dist-info/licenses/LICENSE
```

The extraction script uses structural AST transformations for the two modified
transport modules. Other retained modules are copied with attribution; the SDP
parser drops an import needed solely for a reserved payload-type constant.
The ICE adapter imports the scoped `hookup.ice.Connection` subclass, which
filters unusable addresses and addresses on known down interfaces before
binding host candidates with aioice's protocol. Up virtual/VPN interfaces remain
eligible for LAN peers. STUN first probes the OS-selected IPv4 source for the
resolved STUN target, then probes remaining interfaces if the primary fails or
has not replied within one second. A successful mapping ends gathering early;
otherwise the entire gather stays within five seconds and retains LAN hosts.
Missing route information falls back to probing all valid IPv4 interfaces.
All STUN tasks are cancelled and awaited before gathering returns. This
policy is in `hookup/ice.py`, adapted from aioice 0.10.2; its full license is
included in `hookup/THIRD_PARTY_NOTICES.txt`. ICE checks, nomination, DTLS and
SCTP remain upstream's. TURN configuration delegates gathering to upstream.
The room negotiation budget allows 15 seconds for both sides' gathering and
connection setup. Explicit connection/signaling failure wakes the relay
fallback immediately, without waiting for that budget to expire.
The script refuses a different upstream version or changed source hashes.
It is a maintenance tool and never executes at application startup or build.

Upstream fixes no longer arrive automatically for this vendored subset. Review
aiortc and aioice security/transport changes when updating dependencies, review
the generated diff, and rerun interoperation, fingerprint rejection, real
encrypted room transfer, cancellation and relay-fallback tests before release.
