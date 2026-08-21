# ifaddr interface list

Every network interface the device currently has, with its IPv4 and IPv6 addresses, the
prefix length of each one and what kind of address it is. The headline is the answer most
apps actually want — the IPv4 address another machine on this network could reach — and the
line under it reports how long the underlying `getifaddrs` call took. Turn on **Watch for
changes** and toggle Wi-Fi, airplane mode or a VPN: every address that appears or disappears
is logged as it happens.

What it demonstrates:

- **The value of `platform.system()`, printed at the top of the screen.** On iOS it says
  `'iOS'`, not `'Darwin'` — which is the whole reason this package needs a recipe, because
  [`ifaddr`](https://github.com/pydron/ifaddr) chooses its `sockaddr` layout from that
  string. Android says `'Linux'` on Python 3.12 and `'Android'` from 3.13 — neither matches,
  so both correctly take the Linux layout.
- **Two different shapes behind one API.**
  [`get_adapters()`](https://github.com/pydron/ifaddr#lets-get-going) hands back a dict view
  rather than a list, and `IP.ip` is a plain string for IPv4 but an
  `(address, flowinfo, scope_id)` triple for IPv6 — so `interfaces.py` normalises both into
  one `Address` first. A link-local IPv6 address is shown with its scope id attached, because
  it is unusable without it.
- **Classifying an address without interface flags** — ifaddr exposes none, so loopback,
  link-local, private and global are decided by handing the address to the standard
  library's [`ipaddress`](https://docs.python.org/3/library/ipaddress.html) module.
- **Polling as the only way to notice a change** — there is no callback API, so **Watch for
  changes** runs a one-second loop inside
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with an
  activity ring up, catching its own exceptions (a background thread's are discarded) and
  ending with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that auto-update
  never reaches. Each poller carries a generation number, or flicking the switch off and back
  on inside one interval would leave two of them running. The scan itself is a single libc
  call and stays on the UI thread.
- **A [`SegmentedButton`](https://flet.dev/docs/controls/segmentedbutton/) filter** whose
  `selected` is a `list[str]` in Flet 0.86, read as `e.control.selected[0]`.

Watch the counts rather than the names: an interface list is mostly IPv6 and mostly
link-local, and the headline can legitimately read `loopback and link-local only`. It says
`no interfaces at all` for something else entirely, because an empty scan is what a
mismatched `sockaddr` layout looks like, not what a quiet network looks like. An emulator
shows you neither: with airplane mode on, an API 35 emulator still hands the app `eth0` with
`10.0.2.15`, so the headline keeps an address that goes nowhere. An app that assumes a LAN
address exists is an app that crashes on a plane.

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
