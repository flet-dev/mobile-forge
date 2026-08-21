# token budget

A chat payload — a system prompt, two turns of history and whatever you type — priced in
tokens before anything is sent. The meter shows what the payload costs against a budget the
app sets for itself, and the line underneath shows what a "four characters per token" guess
would have said instead. The header states where the vocabulary came from: the copy bundled
with the app, the copy already cached on the device, or the network.

What it demonstrates:

- **Making the first encode work with no network.** [tiktoken](https://github.com/openai/tiktoken)
  fetches its vocabulary on first use and caches it under a filename that is the SHA-1 of the
  blob URL. `budget.py` points `TIKTOKEN_CACHE_DIR` at a directory under
  [`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
  and, when the blob was prefetched into the app, copies it there from
  [`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir)
  first. Skip the prefetch below and the app still builds — it just needs a connection the
  first time it runs.
- **Counting a payload rather than a string.** `encode` prices text and knows nothing about
  roles or message boundaries, so `count_chat` adds the framing from
  [OpenAI's counting recipe](https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken#6-counting-tokens-for-chat-completions-api-calls)
  — three tokens per message, three more priming the reply. It also passes
  `disallowed_special=()`, without which typing `<|endoftext|>` into the field raises
  `ValueError` instead of returning a count.
- **Why a character budget is not a token budget.** The bottom table runs the same encoder
  over English, Python, JSON, Japanese and emoji: on a desktop run the ratio fell from 4.67
  characters per token to 0.55, because emoji cost more tokens than they have characters.
- **Loading off the UI thread.** The load is the slow, failable half, so it runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button disabled and a spinner up, and ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs. The `except` clause is what puts a `ConnectionError` on screen rather than letting
  `run_thread` swallow it.

Swap the draft for a row of emoji of about the same length and press Count. The
characters-divided-by-four line barely stirs — 123, then 126 — while the real count goes from
146 to 373. That gap is the whole reason to ship a tokeniser instead of guessing.

## Try it

Bundle the vocabulary first, so the app never needs a connection (3.6 MB into `src/assets/`):

```bash
uv run python -c "
import hashlib, pathlib, urllib.request
url = 'https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken'
out = pathlib.Path('src/assets/tiktoken'); out.mkdir(parents=True, exist_ok=True)
out.joinpath(hashlib.sha1(url.encode()).hexdigest()).write_bytes(urllib.request.urlopen(url).read())
"
```

[Build](https://flet.dev/docs/publish/) the app, then install it on a device or emulator/simulator:

```bash
# Android
uv run flet build apk

# iOS
uv run flet build ipa

# iOS-Simulator
uv run flet build ios-simulator
```
