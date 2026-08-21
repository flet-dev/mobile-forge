# tiktoken

[`tiktoken`](https://github.com/openai/tiktoken) is OpenAI's byte-pair-encoding tokeniser:
the same splitting rules its models are billed and truncated by, as a Rust extension behind a
small Python API. In a Flet app it answers the question you would otherwise guess at — *how
many tokens is this?* — on the device, before a prompt is assembled, sent or paid for.

The wheel carries the code and none of the vocabularies. Constructing an encoding fetches a
file of a few megabytes over HTTPS the first time, so plan where that file lands and what
happens when it cannot be fetched: [Storage](#storage) and
[Working offline](#working-offline) below.

## Install

Add tiktoken to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "tiktoken",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`token-budget`](examples/token-budget) — prices a chat payload against a budget, with the
  vocabulary bundled into the app so the first count works offline.

## Usage in a Flet app

An encoding is loaded once and used everywhere after that:

```python
enc = tiktoken.encoding_for_model("gpt-4o")
label.value = f"{len(enc.encode(prompt, disallowed_special=()))} tokens"
```

[`encoding_for_model`](https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken#2-load-an-encoding)
maps a model name to its encoding and `get_encoding` takes the encoding name directly; both
return the same cached object for the life of the process. `disallowed_special=()` is what
lets `prompt` be arbitrary text rather than only text you wrote yourself.

### Storage

The tokeniser's vocabulary is a file tiktoken downloads and caches. Choose where it lands,
before the first `encoding_for_model` or `get_encoding` call:

```python
cache = os.path.join(os.getenv("FLET_APP_STORAGE_CACHE", "."), "tiktoken")
os.makedirs(cache, exist_ok=True)
os.environ["TIKTOKEN_CACHE_DIR"] = cache
```

[`FLET_APP_STORAGE_CACHE`](https://flet.dev/docs/reference/environment-variables/#flet_app_storage_cache)
is the right home: app-private, durable across launches, and understood by the system as
something it may reclaim — which is what a re-downloadable vocabulary is. A copy you prefetch
and build into the app is an [asset](https://flet.dev/docs/cookbook/assets) instead, read
through
[`FLET_ASSETS_DIR`](https://flet.dev/docs/reference/environment-variables/#flet_assets_dir).

Without `TIKTOKEN_CACHE_DIR`, tiktoken uses a `data-gym-cache` directory under
`tempfile.gettempdir()` and swallows a failure to write there. The symptom is an app that
works but re-downloads several megabytes on every cold start. Setting the variable also makes
write failures loud: tiktoken only stays quiet about the location it chose for itself.

### Threading

Loading an encoding is the slow part — a download on a cold cache, then a merge table built
from a megabyte or more of text. On desktop `o200k_base` took about 150 ms from a warm cache
and two to three seconds when it had to fetch the blob first. Do it in
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
spinner up, catch exceptions inside the worker so a network failure reaches the screen, and
finish with an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update).

Encoding itself is fast enough to run inline: 16,400 characters of English prose took 0.5 ms
on desktop, the same length of Python source 0.8 ms. For a large batch,
`encode_ordinary_batch` and `encode_batch` spread the work over a thread pool and the Rust
code really does release the GIL — 64 strings of 2,000 characters of source measured about
7.6 ms at `num_threads=1` against 2.6 ms at `num_threads=8` on a ten-core desktop, as medians
of a warmed loop; the first call in a process pays a millisecond or two more to start the
pool. One `Encoding` serves concurrent calls, which is how those methods are built.

### Working offline

The first time an encoding is constructed, `tiktoken_ext.openai_public` fetches its
vocabulary from `openaipublic.blob.core.windows.net` over HTTPS with
[`requests`](https://requests.readthedocs.io/), checks a SHA-256, and writes it into the cache
directory under a filename that is the **SHA-1 of the blob URL**. On a device with no route
to the network, that first call raises `requests.exceptions.ConnectionError` — a subclass of
`OSError` — instead of returning a tokeniser.

| Encoding | Used by | Download | Loaded, desktop RSS |
| --- | --- | ---: | ---: |
| `o200k_base` | GPT-5, GPT-4.1, GPT-4o, o1/o3/o4-mini | 3.6 MB | ~85 MB |
| `o200k_harmony` | gpt-oss | 3.6 MB, same blob | ~100 MB |
| `cl100k_base` | GPT-4, GPT-3.5-turbo, `text-embedding-3-*` | 1.7 MB | ~47 MB |
| `gpt2` | GPT-2 | 1.5 MB in two files | ~34 MB |
| `p50k_base`, `p50k_edit`, `r50k_base` | older completion and edit models | 0.84 MB | ~25 MB |

To make the first count work on a plane, prefetch the blob under its cache name and build it
into the app as an asset — `src/assets/tiktoken/` is a good place:

```python
url = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
name = hashlib.sha1(url.encode()).hexdigest()
pathlib.Path("src/assets/tiktoken", name).write_bytes(requests.get(url).content)
```

Then seed the cache from the bundle at startup, before the first load:

```python
bundled = os.path.join(os.getenv("FLET_ASSETS_DIR", ""), "tiktoken", name)
if not os.path.exists(os.path.join(cache, name)) and os.path.exists(bundled):
    shutil.copyfile(bundled, os.path.join(cache, name))
```

A cache hit is a plain file read and performs no write, so `TIKTOKEN_CACHE_DIR` may point
straight at the read-only bundle when every encoding the app uses was shipped. Copying into
writable storage first is what keeps a later miss — a second encoding, a new model — able to
fall back to the network.

Model lookup and the plugin registry need no network: `encoding_name_for_model("gpt-4o")`
returns `"o200k_base"` and `list_encoding_names()` returns all seven names without opening a
socket. Use them to decide which blob to prefetch, and to tell "the vocabulary is missing"
apart from "the package is broken". The download itself works on Android as built, because
`flet build` starts its permission table from `{"android.permission.INTERNET": True}`.

### Memory

An encoding is expensive to hold, roughly in proportion to its vocabulary — the RSS column
above is resident-set growth measured on desktop, per encoding, in a fresh process. More than
half of it is the Python `dict` of merge ranks the `Encoding` keeps alongside the Rust
tokeniser built from it — 48 MB of `o200k_base`'s 85. `get_encoding` caches into a
module-level dictionary that is never evicted, so encodings accumulate: `cl100k_base` then
`o200k_base` measured 45 MB and then 120 MB above the import baseline, and dropping your
reference frees neither. Load the one your model uses.

### App size

The wheel is approximately 0.90–1.04 MB compressed and 2.1–2.9 MB unpacked per architecture,
nearly all of it the single Rust extension, so
[`[tool.flet.cleanup]`](https://flet.dev/docs/publish/#compilation-and-cleanup) has nothing
worth removing. A prefetched vocabulary adds its own download size on top of that; it travels
as an asset rather than as a native library, so a device carries one copy of it however many
ABIs the build targets.

On Android, use an app bundle, split APKs, or narrow
[`target_arch`](https://flet.dev/docs/publish/android/#supported-target-architectures) when
the application does not need every ABI. These figures describe the package payload, not the
exact amount added to the final APK or IPA.

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel and the same Python API, but a development
machine has a writable temp directory, a fast connection and a cache already warm from an
earlier run — so every cache mistake above costs nothing there and surfaces only on a device.
Test the first launch on a device with the network switched off.

## Things to know

- **Text that looks like a special token raises.** `enc.encode("... <|endoftext|>")` fails
  with `ValueError: Encountered text corresponding to disallowed special token
  '<|endoftext|>'`, so a text field, a pasted log or a downloaded file can take a counter
  down with thirteen characters. Pass `disallowed_special=()` to price it as ordinary text,
  or `allowed_special={...}` to let named ones through deliberately.

- **A token count is not a payload count.** `encode` prices a string and knows nothing about
  roles or message boundaries, which the API also charges for. Add the framing yourself;
  [OpenAI's counting recipe](https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken#6-counting-tokens-for-chat-completions-api-calls)
  uses three tokens per message plus three priming the reply for current chat models.

- **Characters are not a proxy for tokens, in either direction.** Across English prose,
  Python, JSON, Japanese and emoji, one desktop `o200k_base` run moved from 4.67 characters
  per token to 0.55 — emoji cost more tokens than they have characters. A "divide by four"
  budget overshoots badly on anything that is not English.

- **A truncated bundled vocabulary becomes a download.** tiktoken checks the SHA-256 of
  whatever it finds cached, deletes a file that does not match and re-fetches, so a blob
  corrupted by the build surfaces as a network error, not as a wrong count.

- **An app-supplied `tiktoken_ext` plugin module is not found on Android.** `tiktoken_ext` is
  a namespace package, and Android's zipped site-packages cannot hold one, so a real
  `__init__.py` is synthesised for it — which stops a second `tiktoken_ext` directory from
  merging in. It still merges on iOS, so the behaviour differs by platform. Construct
  `tiktoken.Encoding(...)` directly instead.

## Build notes (maintainers)

### Recipe shape

A plain sdist build: setuptools with `setuptools-rust`, one PyO3 extension, no patches and
nothing vendored. The property that shapes the page above is that the wheel is code only —
every encoding's data arrives at runtime — so the consumer material is mostly about the cache
rather than the API.

### Upgrade hazards

`tiktoken_ext/openai_public.py` is the source of truth for blob URLs, their hashes and the
set of encodings, and it changes whenever OpenAI adds a tokeniser. Re-read every download
size, encoding name and model mapping quoted above from that file after a bump.

`tiktoken/load.py` owns the cache contract: `TIKTOKEN_CACHE_DIR`, the SHA-1-of-URL filename,
and the rule that a write failure stays silent only for the default directory. Apps ship
assets named by that scheme, so a change there invalidates published guidance and every app
that followed it. The crate also declares Rust edition 2024 and PyO3 0.28, so the toolchain
floor moves with upstream; too old a Rust fails at `cargo` rather than in Python.

### Re-verification checklist

- **Plugin discovery from zipped site-packages:** confirm `pkgutil.iter_modules` still finds
  `tiktoken_ext.openai_public` once serious-python has synthesised the namespace
  `__init__.py`, in both source and compiled-only form. Everything else depends on it.
- **Cache contract:** re-read `load.py` and confirm the filename is still
  `sha1(url).hexdigest()`, and that a cache hit still performs no write — that is what allows
  a read-only assets directory.
- **Runtime dependencies:** `regex` needs a mobile wheel for every Python leg being built,
  and `requests` with its own dependencies must still resolve as pure-Python wheels.
- **Sizes and memory:** re-measure compressed and unpacked wheel sizes and the per-encoding
  RSS figures rather than scaling the old ones; that table is the basis for the advice to
  load exactly one encoding.
- **armeabi-v7a:** confirm the 32-bit slice still builds, which is where the Rust dependency
  set usually breaks.

### Coverage gaps

Both device tests construct an encoding, so both need working network on the emulator or
simulator and neither proves anything about the offline path. Nothing exercises a pre-seeded
`TIKTOKEN_CACHE_DIR`, a read-only cache directory, the `ConnectionError` a disconnected
device produces, or the bundled-asset route — that last was validated on desktop with
`FLET_ASSETS_DIR` set by hand. A test seeding the cache from a blob staged beside the tests
would close most of this, and make the suite runnable without network.
