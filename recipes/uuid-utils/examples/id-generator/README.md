# uuid-utils id-generator

One screen that generates 20,000 ids under a chosen UUID version and answers the four
questions a primary key has to answer: what does one id cost, does a batch come out already
sorted, what instant does an id carry, and can a time window be selected by comparing key
text alone.

Nothing is bundled and nothing is fetched — every number comes from ids made on the device
while you watch, so two phones can be compared with each other and with the desktop figures
below.

What it demonstrates:

- **What each version costs, against the standard library on the same runtime.** The top
  table times both implementations over 20,000 ids, best of three, and prints nanoseconds
  per id and ids per second. On an Apple M4 desktop under CPython 3.14.6 (best of twenty
  loops of 200,000 calls) uuid-utils needs 39 ns for a v4 against `uuid.uuid4`'s 1,052 —
  **27×** — and 65 ns for a v7 against `uuid.uuid7`'s 1,230, **19×**. v3 and v5 are the
  narrow ones at 4–6×, because the stdlib's MD5 and SHA-1 are already C.
- **That v7 comes out sorted and v4 does not.** The ordering line counts adjacent pairs
  that are out of order when the batch is read as *text* — which is how a key column, a
  file name and a document-store key range are all compared. On desktop a 20,000-id v4
  batch has about 10,000 pairs out of order, half of them, and a v7 batch has zero. A
  million v7 ids in one loop also gave zero, at up to 7,151 in a single millisecond.
- **That "time-ordered" is not the same as "monotonic", and this is where v6 loses.** In
  the same test uuid-utils' v6 and v1 batches come out *nearly* sorted — measured on
  desktop, 4–7 inversions per 100,000 v6 ids and 3–7 per 100,000 v1 ids. Every one of them is
  the same thing: two ids sharing a 100-nanosecond tick, where the order falls to the
  14-bit clock sequence, which had just wrapped from 16383 to 0. v7's counter is wider and
  never did. CPython 3.14's own `uuid.uuid6` has no inversions because it bumps its
  timestamp forward instead of letting the sequence wrap. The rate depends entirely on how
  many ids land in one tick, so a phone slow enough to spread 20,000 ids over tens of
  milliseconds can legitimately show zero — verified by slowing the generators to 2 µs a
  call on desktop, where the v6 and v1 lines both read `0 of 19,999`.
- **Why v1 must not be used as a sort key, proved by arithmetic rather than by waiting.**
  For v1 the bottom line builds — without generating anything — the two ids a generator
  *would* produce at two instants 20 ms apart that straddle the moment the low 32 bits of
  the timestamp roll over. v1 writes that low word first, so the later id sorts first, and
  it happens every 429.5 seconds on every device. The v6 line runs the same two instants
  through the v6 layout, where they stay in order; that reordering of the three timestamp
  words is the entire content of the v6 specification.
- **A range scan with no timestamp column.** For v7 the app takes the middle third of the
  batch's millisecond span, computes the two ids that bracket it (`ms << 80` and the next
  millisecond's floor minus one), and counts the batch two ways: by comparing id strings
  against those bounds, and by decoding every timestamp. The two counts have to agree. That
  is a `WHERE id BETWEEN ? AND ?` over the key column, with no second column and no
  secondary index. On a desktop the whole batch fits in one or two milliseconds, so the
  window covers all of it and the line reads `middle 2 ms … 20,000 ids … 20,000` — the
  layout is still being checked, but nothing is being excluded. Slow the generator to 2 µs a
  call and the same code selected 7,422 of 20,000 across a 16 ms window; a phone spreads the
  batch the same way.
- **Which node id each `getnode()` found, and what it cost.** The line prints both, in hex,
  labelled `MAC` or `random` from the multicast bit that RFC 9562 requires on an invented
  node. Only v1 and v6 consult it. The first call is the expensive one — the standard
  library may try to run `ip` and `ifconfig` before giving up — and both implementations
  cache the answer for the life of the process.
- **That the two `UUID` classes are not interchangeable.** The last line builds the same id
  under both and reports that they compare **unequal** while hashing **equal**, so a dict
  given both keeps two keys in one bucket; `sorted([...])` of a mixed list raises
  `TypeError`. It also confirms that `uuid_utils.compat.uuid7()` returns a real
  `uuid.UUID`, which is the way out.
- **Which runtime it is on.** The second header line reports whether the stdlib's optional
  `_uuid` extension is present and therefore whether `uuid.uuid1()` runs in C or in Python.
  Flet's Android runtime ships no `_uuid` and its iOS runtime does, so this line differs
  between the two platforms — while the uuid-utils row of the table, which is Rust and
  needs neither, should not.
- **Degrading instead of crashing.** The import of `uuid_utils` is guarded. Without the
  wheel the header turns red and names what the import raised, the uuid-utils row reads
  `unavailable here`, and every panel is recomputed from the standard library's own batch
  so the screen still says something. On CPython 3.12 and 3.13, where the stdlib has no
  v6/v7/v8 at all, those two schemes then report that nothing on the runtime generates
  them.

All the figures above are **desktop** measurements (Apple M4, macOS 26.6, CPython 3.14.6,
uuid-utils 0.17.0 from PyPI). The point of running the app is to replace them with a
phone's own.

## Try it

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or
emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```

It also runs on the desktop with `uv run flet run`, which is the fastest way to see the
tables before committing to a build.
