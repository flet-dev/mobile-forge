# uuid-utils id-generator

One screen that generates 20,000 ids under a chosen UUID version and answers the four
questions a primary key has to answer: what does one id cost, does a batch come out already
sorted, what instant does an id carry, and can a time window be selected by comparing key
text alone.

Nothing is bundled and nothing is fetched — every number comes from ids made on the device
while you watch, so two phones can be compared with each other and with a desktop.

What it demonstrates:

- **What each version costs, against the standard library on the same runtime.** The top
  table times both implementations over 20,000 ids, best of three, and prints nanoseconds
  per id and ids per second. The gap is widest on v4 and v7 and narrowest on v3 and v5,
  where the standard library is already calling into C for MD5 and SHA-1.
- **That v7 comes out sorted and v4 does not.** The ordering line counts adjacent pairs
  that are out of order when the batch is read as *text* — which is how a key column, a
  file name and a document-store key range are all compared. A v4 batch has about half its
  pairs out of order; a v7 batch has none.
- **That "time-ordered" is not the same as "monotonic", and this is where v6 loses.** The
  v6 and v1 batches come out *nearly* sorted. Every inversion is the same event: two ids
  sharing one 100-nanosecond tick, where the order falls to the 14-bit clock sequence,
  which had just wrapped. v7's counter is wider and does not. How often it happens depends
  entirely on how many ids land in one tick, so a phone slow enough to spread 20,000 ids
  over tens of milliseconds can legitimately show none — which is exactly why a benchmark
  loop is not evidence that v1 or v6 is safe to sort on.
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
  secondary index. On a fast machine the whole batch lands inside a millisecond or two, so
  the window covers all of it and nothing is excluded — the layout is still being checked.
  A phone spreads the batch out and the window starts selecting a slice of it.
- **Which node id each `getnode()` found, and what it cost.** The line prints both, in hex,
  labelled `MAC` or `random` from the multicast bit that RFC 9562 requires on an invented
  node. Only v1 and v6 consult it. The first call is the expensive one — the standard
  library may try to run `ip` and `ifconfig` before giving up — and both implementations
  cache the answer for the life of the process, so the milliseconds mean something only on
  the first run.
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
