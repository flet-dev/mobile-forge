# Argon2 password cost

Argon2 is expensive on purpose, and exactly how expensive is a property of the machine
running it. This app measures that on the device in your hand. Choose a memory cost, a
lane count and a time cost, and **Measure** hashes a password and then verifies it twice
— once with the right password, once with a wrong one. **Sweep memory** walks every
memory step at the current settings and names the largest one whose hash still lands
inside a 250 ms budget. The caption at the top says which machine the numbers came from.

What it demonstrates:

- **Calibration as the actual task** — the
  [parameters](https://argon2-cffi.readthedocs.io/en/stable/parameters.html#choosing-parameters)
  that make sense are the strongest ones a user will sit through, and
  [RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html#section-4)'s first recommendation
  is 2 GiB of memory — the figure it gives for when nothing is known about the hardware.
  The sweep replaces guessing with a number from the phone, which is the only number worth
  shipping.
- **Verifying costs what hashing cost** —
  [`argon2_verify`](https://github.com/P-H-C/phc-winner-argon2/blob/master/include/argon2.h)
  re-derives the whole tag from the parameters stored in the encoded string before it
  compares anything, so the right password and a wrong one take the same time. A login
  screen is billed for every attempt, including the ones that fail.
- **The C API with C manners** — `lib.argon2_hash` returns an `int`, never raises, and
  writes into a buffer you size yourself with `lib.argon2_encodedlen`. A failure is a
  negative code you have to look up with `lib.argon2_error_message`, and the salt is
  yours to generate — [`secrets.token_bytes`](https://docs.python.org/3/library/secrets.html)
  here, because libargon2 rejects anything shorter than 8 bytes rather than padding it.
- **Everything needed to verify travels in the hash** — the `m=…,t=…,p=…` field the app
  prints back is read out of the encoded string, which is why raising the cost next year
  does not strand the hashes you stored this year.
- **Compute off the UI thread** — each measurement runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with
  the buttons disabled and a spinner up, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. The ring keeps turning because Flutter draws it, not Python; what the
  worker thread buys is a handler that returns immediately, and what the CFFI call's
  release of the GIL buys is the rest of your Python still running while libargon2 works.

Move the lane count up and the same hash finishes sooner while the `m=` field does not
budge: lanes divide one block of memory rather than adding blocks, so parallelism buys
wall-clock time for free. Memory is the knob that costs something, which is why it is the
one worth spending a budget on — and why a measurement taken on an emulator, whose memory
is its host's, is not a measurement of your phone.

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
