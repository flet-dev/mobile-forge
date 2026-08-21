# primp impersonate probe

Pick a browser and an operating system, and the app shows you the request that combination
produces. The top panel is the literal request head, captured by a socket the app opens on
127.0.0.1 — no network, no server, just the bytes primp wrote. The button underneath sends the
same client to [tls.browserleaks.com](https://tls.browserleaks.com/), which answers with the
JA3 and JA4 hashes of the TLS handshake it just completed.

What it demonstrates:

- **What impersonation actually changes.** Chrome sends fourteen headers, opening with a long
  `accept:` and following its `User-Agent` with three `sec-ch-ua` client hints; Firefox sends
  `dnt`, `sec-gpc` and `te: trailers` instead; Safari sends nine and no client hints at all.
  The set, the order and the values all move together, because a plausible request is not
  just a plausible
  [`User-Agent`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/User-Agent).
- **The half you cannot see locally.** JA3 and JA4 hash the TLS ClientHello — cipher suites,
  extensions, curves, ALPN — so only the far end of a handshake can report them. That is why
  the second panel needs the network while the first one does not, and why a matching
  User-Agent alone does not make a client look like Chrome.
- **Choosing the OS on purpose.** Passing
  [`impersonate_os`](https://github.com/deedy5/primp#browser-profiles) is what makes the
  second dropdown work, and leaving it out is not neutral: primp then draws an OS at random
  per client, so one screen would report Chrome on macOS and the next Chrome on an iPhone.
  Select Safari and the dropdown appears to stop working — `android`, `windows` and `linux`
  all leave the macOS `User-Agent` in place, because primp has no such profile and falls back
  without saying so. That silence is the point: an argument that took no effect looks exactly
  like one that did.
- **A request off the UI thread.** Both panels run in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with a
  spinner up and the button locked, and each worker body is wrapped so that an unreachable
  endpoint reports itself in the caption instead of leaving the controls disabled. The handler
  ends with the explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update)
  that a background thread needs.

Set the profile to `off` and the head collapses from fourteen headers to three, with no
`User-Agent` among them — that request is the shape a filter is looking for when it
decides a caller is a script. Run this on the desktop and the first loopback exchange takes
105–115 ms while every one after it takes well under a millisecond. What the first one pays for
is the first `primp.Client(...)` the process builds — the trust store is assembled once, and
the profile you picked makes no difference to it — rather than the request, which costs a
millisecond either way.

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
