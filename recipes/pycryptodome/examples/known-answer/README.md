# pycryptodome known answers

One screen that checks pycryptodome against constants nobody in this repository chose:
eleven published test vectors from NIST, FIPS and the RFCs, recomputed on the device and
compared side by side, each with a green PASS or a red FAIL. Under that, an AES-256-GCM
round trip you can tamper with, and a slider that measures what a password KDF costs on
the hardware in your hand.

What it demonstrates:

- **Answers you can check** — AES-128-GCM and AES-256-GCM (ciphertext *and* tag) from
  cases 4 and 16 of the [GCM specification McGrew and Viega submitted to NIST](https://web.archive.org/web/2016id_/http://csrc.nist.gov/groups/ST/toolkit/BCM/documents/proposedmodes/gcm/gcm-revised-spec.pdf),
  which is where those numbered vectors live — [NIST SP 800-38D](https://csrc.nist.gov/pubs/sp/800/38/d/final)
  standardised the mode itself and contains no test vectors,
  ChaCha20-Poly1305 from [RFC 8439 section 2.8.2](https://www.rfc-editor.org/rfc/rfc8439#section-2.8.2),
  SHA-256, SHA-512 and SHA3-256 of `"abc"` from
  [NIST's example values](https://csrc.nist.gov/projects/cryptographic-standards-and-guidelines/example-values)
  — FIPS 180-4 and FIPS 202 define those algorithms and, like SP 800-38D, point at that
  page rather than publishing digests of their own,
  [`scrypt`](https://www.pycryptodome.org/src/protocol/kdf#scrypt) from
  [RFC 7914 section 12](https://www.rfc-editor.org/rfc/rfc7914#section-12), and
  [`PBKDF2`](https://www.pycryptodome.org/src/protocol/kdf#pbkdf2) from
  [RFC 6070](https://www.rfc-editor.org/rfc/rfc6070). Printing what pycryptodome computed
  would prove nothing; comparing it against a published constant does.
- **Three facts only the device can tell you**, printed in the header strip:
  `Crypto.Math.Numbers._implementation` (the bignum backend, printed as the dict it is —
  `{'library': 'custom', 'api': 'cffi'}` on device, `custom` because no libgmp can be
  loaded there), `Crypto.Util._raw_api.backend` (`cffi` on device,
  `ctypes` in a desktop install, where the PyPI wheel pulls in no cffi), and
  `Crypto.Util._cpu_features.have_aes_ni()` (`0` on all four ARM slices, whose wheels carry
  no hardware-AES module at all, and a CPUID probe on the two x86_64 ones — the Android
  emulator and an Intel-Mac iOS simulator — which do carry it).
- **A nonce the app never chooses** — the seal panel omits `nonce=` so pycryptodome
  generates one per message, and shows it is 16 bytes rather than the 12 most other
  libraries default to.
- **What tampering actually raises** — *Flip a tag bit* renders
  `builtins.ValueError: MAC check failed`, caught and displayed rather than allowed to
  escape, because an unhandled exception in a Flet event handler ends the session with a
  crash screen.
- **Both halves of a KDF's cost** — the slider sweeps scrypt's `N` from 2^12 to 2^17 and
  reports elapsed milliseconds next to `128*N*r`, the block of memory scrypt asks the OS
  for in one piece, with PBKDF2-HMAC-SHA256 timed underneath at OWASP's recommended
  600,000 iterations. The slider's top stop is OWASP's own first-choice scrypt setting,
  `N=2^17, r=8, p=1` — and on a phone that is 128 MiB in a single allocation, which a
  low-memory device can refuse. The derivation runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread)
  behind a lock, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
