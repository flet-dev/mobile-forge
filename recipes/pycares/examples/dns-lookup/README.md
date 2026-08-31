# pycares DNS lookup

Type a hostname, pick a record type, and resolve it — either through whatever resolver
c-ares found by itself or through a public one. The answers appear as they come back; the
footer shows the nameservers c-ares discovered at startup.

What it demonstrates:

- **Asynchronous DNS inside a Flet app.**
  [`aiodns.DNSResolver`](https://github.com/aio-libs/aiodns) is awaited straight from a Flet
  event handler. No thread pool and no `page.run_thread`: c-ares runs its own event thread
  inside the wheel and aiodns hands results back to the loop, so an in-flight lookup never
  blocks the UI.
- **The record types you actually query.** `A`, `AAAA`, `CNAME`, `MX`, `NS` and `TXT` all go
  through the same `query_dns()` call and render from the typed dataclasses pycares 5.x
  returns, so an `MX` answer shows its priority and a `CNAME` chain shows every hop.
- **The Android nameserver problem, on screen.** Run this on Android and the footer reads
  `127.0.0.1:53` in red — c-ares cannot read Android's resolver config, so **System DNS**
  fails with `Could not contact DNS servers` while the public-resolver option works. On iOS
  the footer shows the real system resolvers and both options work. This is the single thing
  to know before shipping pycares in an app; the [recipe README](../../README.md) explains
  why and what to do about it.

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

An emulator or simulator is enough — both need network access, and Android needs the
`INTERNET` permission, which `flet build` grants by default.
