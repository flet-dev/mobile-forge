# no-model-pipeline

A one-screen [spaCy](https://spacy.io/) pipeline built from
[`spacy.blank("en")`](https://spacy.io/api/top-level#spacy.blank) — no model, no download, no
bundled asset, nothing read from disk — running over a sample document and then checking its own
answers. A slider concatenates 1 to 64 copies of that document, so the per-document cost and
spaCy's memory pool are read across a range rather than at one point.

Four rows say AGREE and one says DISAGREE. The DISAGREE is deliberate, and it is the most useful
thing on the screen.

What it demonstrates:

- **A real pipeline with nothing installed but the wheel** — the tokenizer, plus a
  [`sentencizer`](https://spacy.io/api/sentencizer) and an
  [`EntityRuler`](https://spacy.io/api/entityruler) carrying two literal phrase patterns. The
  header prints what is loaded (2 components) against what merely exists
  (`spacy.util.registry.factories`, 29 of them), because everything else in that list needs a
  model.
- **Checks with a residual, not a vibe** — the token stream is reassembled from
  `text_with_ws` and compared with the source character for character; the sentencizer's spans are
  checked to partition the text exactly; every entity is re-sliced out of the source by its own
  `start_char`/`end_char`. Each row prints the number it measured.
- **An independent reference** — the EntityRuler's entities are recomputed with plain
  `re.finditer(re.escape(phrase))` and the two sorted span lists compared. Nothing else offline
  can corroborate spaCy's answer.
- **The tokenisation trap, as a number** — a
  [`PhraseMatcher`](https://spacy.io/api/phrasematcher) with `attr="LOWER"` and the pattern
  `acme corp.` matches **zero** of the occurrences regex finds, because `Corp.` is an English
  tokenizer exception and `corp.` is not. That is what a silently empty match list looks like.
- **Statistical attributes degrading quietly** — the line under the checks prints `pos_`, `tag_`,
  `lemma_` and `dep_` for the first token. They are empty strings, not errors.
- **Work off the UI thread** — the slider's
  [`on_change_end`](https://flet.dev/docs/controls/slider/#flet.Slider.on_change_end) hands the
  run to [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread),
  which swallows worker exceptions, so the body is guarded and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) auto-update does not do
  for you.
- **The Android `extract_packages` entry** — `pyproject.toml` carries
  `extract_packages = ["spacy", "thinc"]`, without which `import spacy` dies with
  `NotADirectoryError` before any of this runs.

`requires-python` is `>=3.12` because the whole spaCy chain on
[pypi.flet.dev](https://pypi.flet.dev/spacy/) starts at cp312 — a 3.11 resolve finds no wheel at
all.

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
