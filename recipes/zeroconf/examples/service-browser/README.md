# zeroconf service browser

Everything on the Wi-Fi network that answers to mDNS — printers, AirPlay receivers,
Chromecasts, router web interfaces, and any other phone running this app — listed with its
hostname, port, addresses and TXT record as it arrives. The app advertises itself too, so the
first entry is the device you are holding, marked **this device**. Read the status line above
the list first: it says what this platform does to multicast before your code gets a vote.

What it demonstrates:

- **One browser, several service types.**
  [`ServiceBrowser`](https://python-zeroconf.readthedocs.io/en/latest/api.html) takes a list
  of types and calls the handler for each change. Every argument is passed by keyword, so the
  first parameter must be named `zeroconf` — and the call arrives on the browser's own thread,
  where `get_service_info` is free to block while it fetches the SRV and TXT records behind
  the name. `discovery.py` then trims what comes back: empty TXT keys, and the IPv6 addresses
  a V4-only instance is still handed.
- **Advertising, and what the round trip proves.**
  [`register_service`](https://python-zeroconf.readthedocs.io/en/latest/api.html) publishes a
  `ServiceInfo` and blocks about 1.7 s probing for a name clash — measured on a macOS desktop,
  which is why it runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) behind a
  spinner. A second `Zeroconf` instance browses, so the advertisement leaves a multicast socket
  and comes back in: that proves the sockets work, not that another device can reach you, since
  a host loops its own multicast back internally.
- **The Android multicast lock, taken in code.** `discovery.py` reaches
  `WifiManager.createMulticastLock` through [`pyjnius`](../../../pyjnius) and says on screen
  whether it got it. The [permission](https://flet.dev/docs/publish/android/#permissions) it
  needs is declared in `pyproject.toml`; the lock itself cannot be.
- **What the platform admits about itself.** The status line prints the multicast lock
  result on Android, and on iOS the fact that a simulator does not enforce the multicast
  entitlement while a device does — so a clean run in the simulator is not a result.
- **Getting back onto a Flet thread.** The zeroconf callback carries no Flet context, so it
  calls `page.run_thread(rebuild)` rather than touching a control, and `rebuild` ends with
  the explicit [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) that
  a background thread never gets for free. `run_thread` is a pool, so `start` and `stop` are
  serialised behind a lock: two quick flips of the switch would otherwise leave an
  advertisement running with the switch off.

The opening screen is not blank while that registration runs — `ifaddr`, the interface
enumerator zeroconf is built on, reads this device's address from the C library in about a
millisecond. After that an empty list means three different things: the network is quiet,
this device cannot receive multicast, or discovery never started. They look identical, which
is what the `own advertisement seen` counter is for — it separates "nobody answered" from
"nothing works".

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
