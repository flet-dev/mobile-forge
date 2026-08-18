# tokenizers train and count

One screen that trains a byte-level BPE tokenizer **on the device**, from text generated in
code, and then uses it to answer the questions you actually reach for a tokenizer to answer:
how many tokens is this string, does it survive a round trip, and where in the source does
each token come from. No model is downloaded, no asset is bundled, and nothing here touches
the network.

A slider picks how much text to train on — 500 to 16,000 generated sentences. Releasing it
retrains and rebuilds everything below.

What it demonstrates:

- **Training as a normal in-app operation.** The corpus is built from five fixed word lists
  with no randomness, so the same slider position produces the same text on every install
  and two phones are directly comparable. The stats line reports lines, characters, the
  milliseconds this device took, and the vocabulary actually reached against the 2,000
  asked for — they are not the same number, because corpus variety is the real cap, not
  `vocab_size`.
- **A round trip that survives characters the corpus never contained.** The probe table
  includes `'Zürich — 42 €'`, a tab/newline string, an emoji and the empty string, and every
  row passes `decode(encode(s)) == s` — because the trainer is seeded with
  [`ByteLevel.alphabet()`](https://huggingface.co/docs/tokenizers/api/pre-tokenizers). Drop
  that one argument and those rows come back *shorter* rather than raising, which is the
  failure the [recipe README](../../README.md#things-to-know) describes and this table is
  built to catch.
- **A second, independent check per row.** Beside the decode column each row also looks
  every token up in `get_vocab()` and compares the ids that gives against the ids `encode`
  returned — a path that never goes near the decoder. Two confirmations mean a decoder bug
  and a vocabulary bug show up as different failures rather than one plausible-looking pass.
- **What a token actually costs, in both directions.** The first probe is a sentence built
  from the same word lists as the corpus and the rest are not, so the table shows in-domain
  text at about five characters per token next to out-of-domain text at closer to one — the
  answer to "will this fit in *N* tokens" is `len(tokenizer.encode(s).ids)`, and it depends
  on what the tokenizer was trained on far more than on the string's length.
- **Context windows by slicing ids, not by `Encoding.overflowing`.** The paragraph line
  chunks a fixed 20-sentence paragraph into windows of 64 ids — the shape that works, since
  `overflowing` stays empty under `enable_truncation` and drops the tail instead. Read the two
  clauses differently: *ids rejoin* is stated rather than tested, because flattening a slicing
  of a list always reproduces the list, while *text rejoins* is a real check that goes NO the
  moment a window boundary lands inside a multi-byte character. This paragraph is ASCII and 64
  is generous, so it says yes here; the [recipe README](../../README.md#things-to-know) has the
  input that makes it say no. The paragraph is also the one panel the slider does not move —
  it is the same 20 lines at every position, on purpose, so its cost per token is comparable
  across runs while the vocabulary above it changes.
- **Offsets against the literal source slice.** The offsets table prints each token, its
  `(start, end)` and `original[start:end]` beside it, on a sentence containing an em dash and
  a euro sign. Those rows repeat — every token of a multi-byte character carries the same
  range — which is exactly why offsets locate a token but must not be used to rebuild text.
- **Saving and reloading from app storage.** The trained tokenizer is written to a
  subdirectory of
  [`FLET_APP_STORAGE_DATA`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_data)
  after an explicit `os.makedirs`, because
  [`save()`](https://huggingface.co/docs/tokenizers/api/tokenizer) will not create the parent
  directory. The footer prints the file size and the full path, then reloads it with
  `Tokenizer.from_file` and re-encodes every probe with the reloaded object. A **Reload from
  disk** button re-runs only that half, so `from_file` is exercisable without retraining.
- **Which `huggingface_hub` this device got.** The second header line prints its version, or
  `not installed`. It arrives as a hard dependency of the tokenizers wheel and this app never
  calls it — and the version `flet build` resolves for a phone is not the one a desktop
  `uv.lock` picks, so reading it off the screen is the only reliable way to know.
- **Compute off the UI thread, where it genuinely helps.** Training runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up, started from the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) so one
  gesture means one run, and it ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. Unlike a single `encode`, `train_from_iterator` really does release the GIL — see
  [Threading](../../README.md#threading). The worker body is wrapped in `try/except` because
  `run_thread` discards whatever it raises, and it clears the panels on the way out so the
  previous run's rows cannot sit under this run's error.

Every call that can fail is caught as broad `Exception`, because everything `tokenizers`
raises — including missing files and malformed JSON — is a bare `Exception` and nothing
narrower catches it, and an unhandled exception in a Flet event handler crashes the session.
An empty vocabulary after training is treated as an error rather than a result, since an
untrained tokenizer encodes to `[]` without complaining.

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

`pyproject.toml` pins `flet` and `tokenizers`, which is the combination that was verified.
`requires-python` stays at `>=3.10` — the tokenizers wheel declares exactly that floor, so
every split uv resolves for is satisfiable — checked the way a consumer meets it, by copying
that `pyproject.toml` alone into an empty directory and running `uv lock` there. The lock it
writes is a desktop lock and resolves `huggingface-hub` 1.x; the phone gets 0.31.4 instead,
which is why the app prints the version it actually loaded.
