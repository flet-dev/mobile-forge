# selectolax page scrape

One screen that parses a 1,186-byte HTML page bundled inside `main.py` — no network, no
assets — turns it into records, and reports what the parser had to repair to get there.
A text field runs any CSS selector you type against the tree, six preset chips fill it in,
and a segmented button switches between the two engines the wheel ships, `lexbor` and
`modest`.

The bundled page is broken the way real pages are broken: unquoted attribute values, three
`<li>` and every `<tr>`/`<td>`/`<th>`/`<p>` left unclosed, a `<b>`/`<i>` pair closed in the
wrong order, a bare `<` in running text, a `<table>` with no `<tbody>`, an HTML comment
containing `</div>`, and a `<script>` whose string literal looks exactly like a fourth post.

What it demonstrates:

- **The scrape itself.** Three records with id, title, date, reading time and a draft flag,
  pulled with `li.post`, `a.title` and `span.meta`, plus the footer table read through a
  `<tbody>` that appears nowhere in the source. This is the part worth copying: the `<li>`
  elements are never closed, so "which `<a>` belongs to this post" is a question only a tree
  can answer, and the tree is what gives you `li.post:not(.draft) > a.title` as a one-liner.
- **Six repairs, each verified at run time rather than asserted.** The panel prints what the
  source said and what the tree says, computed on the spot, so a device that parses
  differently prints something different. On a desktop (Apple M4, macOS 26.6, CPython 3.14.6,
  selectolax 0.4.10) it reads:

  | repair | evidence |
  | --- | --- |
  | inserted the missing `tbody` | source has 0 `tbody` start tags, tree has 1, carrying 3 rows |
  | closed what the source leaves open | 35 start tags and 20 end tags: 15 elements closed by the parser |
  | re-nested `<b>and <i>weather</b></i>` | tree says `<b>and <i>weather</i></b>` |
  | kept the bare `<` as text | title 102 reads `'Why 5 < 6 matters'` |
  | did not read the `<script>` string as markup | 0 posts with `data-id` 999, 3 posts in total |
  | the comment's `</div>` did not close `#main` | `#main` still holds 1 footer and 3 posts |

- **What `html.parser` does with the same bytes, stated fairly.** The stdlib parser is a
  tokenizer, not a tree builder, and the screen prints the consequence rather than a verdict:
  35 start tags out of it against 36 elements in selectolax's tree, `0` `tbody` against 3 rows
  readable through one, and the `<b>`/`<i>` sequence handed back verbatim as `b, i, /b, /i`.
  It is not a straw man — `html.parser` gets the character references, the bare `<` and the
  `<script>` contents right, and the app says so in `tokens()`. What it cannot give you is a
  tree, and therefore no selector at all.
- **The speed, measured on whatever you run it on.** The app repeats the post list 40 times
  into a 19,087-byte document and times both parsers over it, best of three timed batches
  each. On that desktop: the engine at **0.34 ms / 56 MB/s** and `html.parser` at
  **1.33 ms / 14.3 MB/s** — about 4× while building a whole tree the tokenizer never builds.
  Both engines measured the same within run-to-run noise (45.7 to 57.6 MB/s across six runs).
  Note that the 56 MB/s is not the ceiling and the reason has nothing to do with the mobile
  build: selectolax's `setup.py` appends `-O0 -g` to `extra_compile_args` on every POSIX
  platform, so every wheel of it — the PyPI one you get from `uv run flet run` included — is
  compiled unoptimised. Rebuilding the Lexbor extension from the sdist with `-O2` on the same
  desktop reached 202–212 MB/s, 3.7–3.9× the shipped build.
- **Where the two engines genuinely differ, via two of the preset chips.** `:is(th, td)`
  matches 6 cells on lexbor and raises `ValueError: Bad CSS Selectors: :is(th, td)` on modest —
  the app prints the error instead of dying, which is the point of catching it. And
  `li.post ~ li` returns 2 nodes on lexbor and 3 on modest, because modest emits one match per
  (earlier sibling, later sibling) pair rather than one per node; on a plain list of five
  matching siblings the same selector returns 4 against 10.
- **The two `page.run_thread` rules, honoured explicitly.** The worker body is wrapped in
  `try/except` because
  [`run_thread`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) never retrieves
  the worker's future and would swallow the exception with no log, dialog or crash; and it
  ends with an explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update),
  because auto-update does not reach a background thread. A pass also locks **all three** of
  the controls that can start one — the engine button, the chip row and the selector field —
  and `rebuild` returns early while one is running, because the `disabled` patch only reaches
  the client a frame later. Both halves are load-bearing: `run_thread` submits to a shared
  pool, so overlapping passes genuinely run at once, and a pass lasts about as long as its
  two timed benchmarks — long enough that tapping two preset chips in a row would otherwise
  hit it. Locking only the engine button does not do it, since a chip and the field are the
  easier ways in.
- **The first pass goes through the worker too.** A synchronous `main` runs on Flet's event
  loop thread, so a pass computed inline there holds the layout `page.add` queued until `main`
  returns. Handing it to `page.run_thread` puts the controls on screen first.
- **Degrading instead of crashing.** The import of `selectolax` is guarded. Without the wheel
  the header turns to `selectolax absent`, the engine button and the selector field disable
  themselves, and the one line that remains is what `html.parser` alone can tell you about
  the same document — start tags, end tags, `0` `tbody`, and no tree to select against.

All the figures above are **desktop** measurements. Running the app on a phone is what
replaces them; only the timings should move, since every other number is a property of the
document and the parser.

## Try it

Runs on the desktop as well as on a phone, because selectolax publishes desktop wheels for
every host you would build from:

```bash
uv run flet run
```

[Build](https://flet.dev/docs/publish/) it for a device with:

```bash
uv run flet build apk
uv run flet build ios-simulator
```

It bundles no assets, writes no files and makes no network requests. Expect the build to be
large: selectolax ships both engines as separate extensions, 7.9 MB of native code per slice
on 64-bit and 4.9 MB on `armeabi-v7a`.
