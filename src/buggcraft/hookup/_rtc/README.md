# DataChannel-only WebRTC

Derived from aiortc **1.15.0** under its BSD-3-Clause license. Copyright (c)
Jeremy Lainé. The full upstream license is in `LICENSE`; `UPSTREAM.json`
records the original and generated SHA-256 for each retained module.

The launcher forwards game TCP streams over ordered, reliable SCTP data
channels. It does not record or transmit audio/video. This subset retains the
upstream ICE adapter, SCTP implementation, DataChannel handling, certificate
generation, DTLS encryption and peer-fingerprint verification. Existing
signaling, stream framing and SSH relay fallback are unchanged.

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
The script refuses a different upstream version or changed source hashes.
It is a maintenance tool and never executes at application startup or build.

Upstream fixes no longer arrive automatically for this vendored subset. Review
aiortc and aioice security/transport changes when updating dependencies, review
the generated diff, and rerun interoperation, fingerprint rejection, real
encrypted room transfer, cancellation and relay-fallback tests before release.
