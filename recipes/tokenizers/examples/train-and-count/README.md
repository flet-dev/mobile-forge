# tokenizers train and count

One screen that trains a byte-level BPE tokenizer **on the device**, from text generated in
code, and then uses it to answer the questions you actually reach for a tokenizer to answer:
how many tokens is this string, does it survive a round trip, and where in the source does
each token come from. No model is downloaded, no asset is bundled, and nothing here touches
the network.

A slider picks how much text to train on — 500 to 16,000 generated sentences — and releasing
it retrains everything below. The corpus is built from five fixed word lists with no
randomness, so the same slider position produces the same text on every install and two
phones are directly comparable. The stats line reports lines, characters, the milliseconds
this device took, and the vocabulary actually reached against the 2,000 asked for — not the
same number, because corpus variety is the real cap.

What it demonstrates:

- **A round trip that survives characters the corpus never contained.** The probe table
  includes `'Zürich — 42 €'`, a tab/newline string, an emoji and the empty string, and every
  row passes `decode(encode(s)) == s` — because the trainer is seeded with
  [`ByteLevel.alphabet()`](https://huggingface.co/docs/tokenizers/api/pre-tokenizers). Drop
  that one argument and those rows come back *shorter* rather than raising, which is the
  failure the [recipe README](../../README.md#things-to-know) describes. Each row is checked
  twice: beside the decode column it looks every token up in `get_vocab()` and compares those
  ids against the ones `encode` returned, a path that never touches the decoder, so a decoder
  bug and a vocabulary bug show up as different failures.
- **What a token costs, and how to window a document.** The first probe is a sentence built
  from the same word lists as the corpus and the rest are not, so the table shows in-domain
  text at about five characters per token beside out-of-domain text at closer to one. The
  paragraph line chunks a fixed 20-sentence paragraph into windows of 64 ids — the shape that
  works, since `Encoding.overflowing` stays empty under `enable_truncation` and the tail is
  dropped instead. *ids rejoin* is stated rather than tested, because flattening a slicing of
  a list always reproduces the list; *text rejoins* is a real check that goes NO the moment a
  boundary lands inside a multi-byte character. On this corpus it says **yes** every time and
  on every device: the paragraph is pure ASCII and 64 ids is a generous window, so no boundary
  can land mid-character. Read it as a check that is wired up rather than one that fired — it
  is the same 20 sentences at every slider position, on purpose, so the panel stays comparable
  while the rest of the screen moves.
- **Offsets against the literal source slice.** Each row prints a token, its `(start, end)`
  and `original[start:end]`, on a sentence containing an em dash and a euro sign. The rows
  repeat — every token of a multi-byte character carries the same range — which is exactly
  why offsets locate a token but must not be used to rebuild text.
- **Saving and reloading from app storage.** The tokenizer is written to a subdirectory of
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  after an explicit `os.makedirs`, because
  [`save()`](https://huggingface.co/docs/tokenizers/api/tokenizer) will not create the parent
  directory. The footer prints the file size and the full path, then re-encodes every probe
  with the reloaded object; **Reload from disk** re-runs that half without retraining.
- **Compute off the UI thread, where it genuinely helps.** Training runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. Unlike a single `encode`, `train_from_iterator` really does release the GIL — see
  [Threading](../../README.md#threading).

Every call that can fail is caught as broad `Exception`, because everything `tokenizers`
raises — including missing files and malformed JSON — is a bare `Exception` and nothing
narrower catches it, and an unhandled exception in a Flet event handler crashes the session.
An empty vocabulary after training is treated as an error rather than a result, since an
untrained tokenizer encodes to `[]` without complaining. The header prints the
`huggingface_hub` version this device actually resolved, which is not the one a desktop lock
picks.

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
