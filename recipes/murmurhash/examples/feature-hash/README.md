# murmurhash feature hash

Five hundred generated documents are cut into 19,582 distinct features — words and adjacent
word pairs — and squeezed into a vector whose width you pick, from 4,096 columns to 262,144.
No vocabulary is built and nothing is fitted: the column a feature lands in is
`murmurhash.hash(feature) & (width - 1)`. The tables report what that costs in collisions,
and what the obvious alternative costs when a word it has never seen turns up.

What it demonstrates:

- **The hashing trick, in one line.**
  [`hash`](https://github.com/explosion/murmurhash) returns a signed 32-bit int, so the low
  bits choose the column and the sign bit comes free as a second hash — add +1 or −1 rather
  than always +1 and collisions stop accumulating in one direction, which is what
  scikit-learn's
  [`FeatureHasher`](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.FeatureHasher.html)
  calls `alternate_sign`. Masking is correct only because the widths are powers of two.
- **Collisions you can watch arrive.** At 262,144 columns 7.0% of features share a bucket;
  at 4,096 it is 99.1% and the fullest bucket holds fourteen. The row underneath is the one
  that matters: of the hundred most frequent features, none collide with each other until
  4,096 columns, where 6% do. Rare features collide constantly and cost nothing, because a
  weight learned from two occurrences was noise anyway.
- **What the vocabulary you avoided would have cost.** The same corpus through a `dict` of
  feature → column needs an entry for every one of those 19,582 features and about 1.5 MB
  for the dict and its keys on desktop, and both passes finish within a millisecond or two
  of each other — a dict lookup is about as cheap as a call into C. The price is elsewhere:
  28% of the feature occurrences in the 200 held-out documents are ones the vocabulary has
  never seen — nine in ten of them word pairs — and they are dropped in silence. The hashed
  vector has no opinion about them.
- **What it is not.** CPython salts
  [`str.__hash__`](https://docs.python.org/3/reference/datamodel.html#object.__hash__) per
  process — relaunch the app and the murmurhash row is unchanged while the builtin row is a
  different number, so any index built on it died with the previous process. And the same
  features through [`hashlib.blake2b`](https://docs.python.org/3/library/hashlib.html) take
  four to five times as long: MurmurHash3 is fast because it defends against nothing.
- **Compute off the UI thread** — the corpus pass runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind
  a [`ProgressRing`](https://flet.dev/docs/controls/progressring/), the body is wrapped so a
  raise cannot leave the [`SegmentedButton`](https://flet.dev/docs/controls/segmentedbutton/)
  disabled forever, and the handler ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background
  thread needs. Only the top table depends on the width, so the two panels below it are
  measured once — recomputing them per press would jitter numbers the width cannot affect.
  The [`TextField`](https://flet.dev/docs/controls/textfield/) at the bottom stays on the UI
  thread, because one hash is one function call.

The corpus comes from a fixed seed rather than a bundled file, so every number above is
reproducible — and generating it is the honest version of the problem: nobody knows in
advance how many distinct word pairs a body of text holds, which is why picking the width
yourself is worth a few thousand collisions.

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
