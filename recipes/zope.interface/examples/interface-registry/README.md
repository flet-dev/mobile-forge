# zope.interface interface registry

Three records, one interface, and a registry that decides at run time which adapter each record
gets. Underneath, five candidate classes are put to `verifyObject` and four of them fail, each
carrying the message zope.interface itself produced. The header line reports which
implementation of the lookup machinery is actually running, and the button times two hundred
thousand lookups on the device in your hand.

What it demonstrates:

- **Which implementation is live**, which is not a thing to assume. The wheel ships a C
  accelerator for
  [adapter lookup](https://zopeinterface.readthedocs.io/en/latest/api/adapters.html#zope.interface.adapter.AdapterRegistry),
  but zope.interface substitutes it in silently and falls back just as silently, so the app
  reads `LookupBase.__module__` and prints where the class it is really using came from.
- **Lookup by interface rather than by type.** Three registrations —
  [`register`](https://zopeinterface.readthedocs.io/en/latest/api/adapters.html#zope.interface.interfaces.IAdapterRegistry.register)
  against `IRecord`, `IUser` and `IOrder` — serve three records, because the Event resolves
  through the base interface it extends. Nothing anywhere matches on a class.
- **A registration that changes the answer while the app runs.** The
  [switch](https://flet.dev/docs/controls/switch/) registers an `IEvent` adapter and withdraws
  it again by registering `None`, and only the Event row moves.
- **Verification that says what is wrong**, not just that something is.
  [`verifyObject`](https://zopeinterface.readthedocs.io/en/latest/verify.html#zope.interface.verify.verifyObject)
  meets a missing attribute, a missing method, a `detail()` that will not take the argument
  `ISummary` promised, and a class that satisfies everything but never declared it. That is four
  distinct messages across three exception types — `BrokenImplementation` covers both missing
  members, then `BrokenMethodImplementation` and `DoesNotImplement`.
- **Compute off the UI thread** — the benchmark runs in
  [`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread) with the
  button disabled and a spinner up, and the worker ends with the explicit
  [`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) a background thread
  needs, whether it finished or raised.

Flip the switch and nothing about the records changes — only the registry does. That is the
whole argument for keeping one: the decision lives somewhere you can edit while the program is
running, instead of in the branch you wrote at the call site.

The project name here contains a dot, and `flet build` strips it rather than converting it, so
`zope.interface-interface-registry` becomes the identifier `zopeinterface_interface_registry`.
Pass `--project` if you want something else.

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
