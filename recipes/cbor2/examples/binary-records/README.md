# cbor2 binary records

A handful of Python values are encoded one at a time, and the app shows the tag number CBOR
wrote in front of each, what came back out, and what `json` did with the same value. Then a
journal of device records — timestamps, decimals, UUIDs, sets, serials wider than 64 bits and
raw digests — is encoded both ways at a size you pick, with the bytes and the milliseconds side
by side.

What it demonstrates:

- **The tag is the whole idea.** A [`Decimal`](https://www.rfc-editor.org/rfc/rfc8949.html#name-decimal-fractions-and-bigfl)
  goes out as `c4 82 21 19 07 cf`: tag 4, then a two-element array of exponent and mantissa.
  The app reads that leading tag off the wire itself — seven lines, no library call — because a
  self-describing type marker is what [RFC 8949](https://www.rfc-editor.org/rfc/rfc8949.html)
  adds over a bare binary format. Everything in the top table is
  [tagged automatically](https://cbor2.readthedocs.io/en/latest/usage.html#encoder-semantic-tag-support);
  none of it needed a hook.
- **What json does instead** — five of the seven sample values raise `TypeError`, and the
  80-bit integer is the interesting one: Python writes and reads all 25 digits, but JSON has
  one number type, so a receiver that parses numbers into doubles silently returns a different
  integer. CBOR gives it tag 2 and a byte string that cannot be widened by accident.
- **The two hooks, and what happens without them** — a `Coordinate` has no tag of its own, so
  a [`default=`](https://cbor2.readthedocs.io/en/latest/customizing.html#customizing-the-encoder)
  hook wraps it in tag 27, IANA's registered shape for an object plus constructor arguments,
  and a [`tag_hook=`](https://cbor2.readthedocs.io/en/latest/customizing.html#customizing-the-decoder)
  rebuilds it. Decode the same bytes without the hook and nothing fails: you get a `CBORTag`
  holding the number and the payload, so a reader that has never heard of your type still
  parses the document.
- **Compute off the UI thread** — the journal is encoded in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button disabled and a spinner up, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. The slider fires on
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  drag runs the benchmark once rather than once per pixel travelled.

Read the decode row twice. `json.loads` beats cbor2 outright — and it has not finished: every
timestamp, decimal, UUID and digest is still a string. The bracketed figure adds the code that
turns them back into objects, and that code is in `records.py`, twenty lines you would have to
write, ship and keep in step with the sender. The CBOR document is also about a third smaller,
and `string_referencing` takes roughly a fifth off that again by replacing each repeat of a
field name with a back reference.

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
