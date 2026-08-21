# zope.interface

[`zope.interface`](https://zopeinterface.readthedocs.io/) writes down what an object promises
and checks the promise while the program runs. An interface is a class body of attribute
declarations and method signatures, a class claims one with `@implementer`, and `verifyObject`
confirms the claim, naming the attribute or the method that does not fit. Alongside it comes an
adapter registry, which answers "give me something that provides `ISummary` for this object" at
run time rather than at the call site.

That pairing suits plugin-shaped code and per-object capabilities, where the alternative grows
into a chain of `isinstance` checks at every call site. Import it as `zope.interface`.

## Install

Add zope.interface to your `pyproject.toml`:

```toml
dependencies = [
    "flet",
    "zope.interface",
]
```

## Examples

See runnable Flet apps in [`examples/`](examples):

- [`interface-registry`](examples/interface-registry) — verifies five candidate classes against
  one interface and resolves an adapter for each of three records out of a registry.

## Usage in a Flet app

Declare what an object has to provide, claim it, and check the claim:

```python
from zope.interface import Attribute, Interface, implementer
from zope.interface.verify import verifyObject

class ISummary(Interface):
    headline = Attribute("Single line, already formatted.")

    def detail(width):
        """Return the long form, clipped to `width` characters."""

@implementer(ISummary)
class OrderSummary:
    def __init__(self, order):
        self.order = order
        self.headline = f"{order.total:.2f} {order.currency}"

    def detail(self, width):
        return f"Order {self.order.identifier}"[:width]

verifyObject(ISummary, OrderSummary(order))  # True, or raises Invalid
```

### Threading

The interface machinery is computation, not I/O, so a worker thread earns its keep only for a
loop large enough to stall a frame — and then the usual Flet shape applies:
[`page.run_thread(...)`](https://flet.dev/docs/controls/page/#flet.Page.run_thread), the
exception caught inside the worker, an explicit
[`page.update()`](https://flet.dev/docs/controls/page/#flet.Page.update) at the end.

A registry is process-wide mutable state, as is the global `adapter_hooks` list, and a lookup
fills a cache inside the registry rather than being a pure read. Build the registry during
import and treat `register()` as a main-thread operation; registering while a worker thread
resolves is an unguarded race nothing will report.

### Verification

An [interface](https://zopeinterface.readthedocs.io/en/latest/api/specifications.html#zope.interface.Interface)
body declares rather than defines: `headline` is an
[`Attribute`](https://zopeinterface.readthedocs.io/en/latest/api/specifications.html#zope.interface.interface.Attribute)
with no value, and `detail` omits `self` because the signature describes how a caller invokes
it. [`@implementer`](https://zopeinterface.readthedocs.io/en/latest/api/declarations.html#zope.interface.implementer)
makes the claim; without it, verification fails on the declaration alone.

[`verifyObject`](https://zopeinterface.readthedocs.io/en/latest/verify.html#zope.interface.verify.verifyObject)
checks three things: that the object declares the interface, that every method is present
with a compatible signature, and that every non-method attribute exists.
[`verifyClass`](https://zopeinterface.readthedocs.io/en/latest/verify.html#zope.interface.verify.verifyClass)
skips that last part, because `__init__` may be what sets those attributes — a class missing
only `headline` passes `verifyClass` and fails `verifyObject`. Both raise a subclass of
[`Invalid`](https://zopeinterface.readthedocs.io/en/latest/verify.html#zope.interface.Invalid):
`BrokenImplementation` for a missing attribute or method, `BrokenMethodImplementation` for a
signature mismatch, `DoesNotImplement` for a missing declaration, and `MultipleInvalid` where
one object has several faults.

Each message names the object, then the interface qualified by its defining module, then the
fault — one line, wrapped here, for an `ISummary` living in `summaries.py`:

```
The object <NoDetail> has failed to implement interface summaries.ISummary:
  The summaries.ISummary.detail(width) attribute was not provided.
```

A signature mismatch is as specific: `The contract of summaries.ISummary.detail(width) is
violated because 'WrongArity.detail()' doesn't allow enough arguments.`

Verification costs real work, so call it where the cost does not matter: in tests, or once at
start-up over the plugin classes an app has just loaded.

### The adapter registry

```python
from zope.interface.adapter import AdapterRegistry
from zope.interface.interface import adapter_hooks

registry = AdapterRegistry()
registry.register([IRecord], ISummary, "", GenericSummary)
registry.register([IUser], ISummary, "", UserSummary)
adapter_hooks.append(lambda provided, obj: registry.queryAdapter(obj, provided))

ISummary(user)   # UserSummary, the exact registration
ISummary(event)  # GenericSummary, because IEvent extends IRecord
```

[`register`](https://zopeinterface.readthedocs.io/en/latest/api/adapters.html#zope.interface.interfaces.IAdapterRegistry.register)
takes the interfaces adapted *from*, the interface adapted *to*, a name (`""` for the unnamed
registration) and the factory. The most specific registration wins, and an object whose own
interface has nothing registered falls back to whatever is registered for an interface it
extends — that fallback is the reason to keep a registry rather than a dict keyed on type.
Registering `None` withdraws a registration, and the next lookup resolves differently, cache and
all.

`queryAdapter` is the lookup; calling the interface is the ergonomic form, and `adapter_hooks`
connects that spelling to a particular registry. Without a hook installed `ISummary(obj)` raises
`TypeError` however much has been registered, while `registry.queryAdapter(obj, ISummary)` keeps
working.

### Compiled lookups

The wheel carries `_zope_interface_coptimizations`, a C implementation of the registry lookup
and the declaration objects. Nothing you write imports it by name: `zope.interface._compat`
does that once, substituting compiled objects for the Python ones as each module imports and
falling back silently when the import fails. Importing it proves only that it exists — ask
instead where a substituted name ended up living:

```python
from zope.interface.adapter import LookupBase

LookupBase.__module__.endswith("_zope_interface_coptimizations")  # True when compiled
```

The [example](examples/interface-registry) prints that line at the top of its first screen,
which is the only way to read the answer off a device. Setting `PURE_PYTHON` to anything other
than `"0"` forces the fallback — the empty string included, easy to set by accident — which is a
convenient way to price the difference: on desktop the same lookup ran at about 5.4 million
per second compiled against 2.5 million interpreted, a little over twice the speed. Device
figures have to come from a device, and the example has a button that measures them.

### App size

Every published slice is approximately 0.21 MB compressed and 0.95–1.02 MB unpacked, the spread
being the extension: 22 KB on `armeabi-v7a`, 94 KB on an iOS device slice.

Over half of that is dead weight. Upstream ships its own test suite in the wheel — 28 files
under `zope/interface/tests/` and `zope/interface/common/tests/`, 481,826 bytes, 60.5% of all
the Python there — plus a 78,751-byte copy of the extension's C source, and nothing imports any
of it. Flet compiles site-packages to `.pyc` and deletes the sources by default
([`compile.packages`](https://flet.dev/docs/publish/#compilation-and-cleanup)), and compiling
*grows* this package: 796 KB of `.py` becomes 1,148 KB of `.pyc`, 815 KB of it tests. Name the
dead weight in the cleanup globs to drop it:

```toml
[tool.flet.cleanup]
package_files = [
    "**zope/interface/tests/*",
    "**zope/interface/common/tests/*",
    "**_zope_interface_coptimizations.c",
]
```

Two details are load-bearing. There is no slash after the leading `**`: paths are matched
relative to the site-packages root, where nothing precedes `zope`, so `**/zope/...` has nothing
for the `**` to consume and matches nothing at all. And each pattern ends in `*`, not `*.py`,
because cleanup runs *after* compilation has replaced the sources with `.pyc`. Confirm on the
build itself:

```bash
unzip -p build/apk/<app>.apk assets/sitepackages.zip > /tmp/sp.zip && unzip -l /tmp/sp.zip | grep zope
```

### Other considerations

A desktop `flet run` uses PyPI's desktop wheel, built from the same sdist with the same optional
extension. Read `LookupBase.__module__` on both rather than assume they agree — an interpreted
registry behaves identically and only runs slower, so nothing else would show the difference.

`zope` is a namespace package — the wheel holds `zope/interface/__init__.py` and no
`zope/__init__.py` — and the platforms land on that differently. iOS keeps site-packages as a
real directory, so `zope` stays a namespace package and `zope.__file__` is `None`. Android keeps
it as a zip, and serious_python writes a zero-byte `__init__.py` into every parent directory of
a `.py`, `.pyc` or `.soref` entry that lacks one, so `zope` arrives as an ordinary package whose
`__file__` is a path inside the zip. Only introspection of `zope` itself differs.

## Things to know

- **`isinstance` answers `False` for an interface, and says nothing.** `isinstance(summary,
  ISummary)` is `False` even for a class decorated `@implementer(ISummary)` — no exception, just
  a wrong answer that reads like a right one. Use
  [`ISummary.providedBy(obj)`](https://zopeinterface.readthedocs.io/en/latest/api/specifications.html#zope.interface.interfaces.ISpecification.providedBy),
  or `ISummary.implementedBy(cls)` for a class.

- **`ISummary(obj)` raises when nothing resolves.** The error is
  `TypeError: ('Could not adapt', <obj>, <InterfaceClass summaries.ISummary>)`, easy to meet in
  a UI handler where the record arrived from a code path that registered nothing. Pass a
  default — `ISummary(obj, None)` — or call `registry.queryAdapter(obj, ISummary)`, which
  returns `None`.

- **Adapting something that already provides the interface returns it unchanged.**
  `ISummary(summary)` is `summary` itself and the registered factory never runs. Usually that is
  what you want, and it is a surprise when the factory was where the work happened.

- **The alternatives check names, not contracts.** A `@runtime_checkable` `typing.Protocol`
  checks only that members *exist*, so a class whose `detail(self)` was promised as
  `detail(self, width)` still passes `isinstance`; `issubclass` against a protocol with any
  non-method member raises `TypeError` outright (CPython 3.12.13 and 3.14.6). `abc` is no
  stricter — `abstractmethod` fires at instantiation on names only, and `SomeABC.register(cls)`
  makes `isinstance` true with no check at all.

- **Declarations are per object, not only per class.**
  [`alsoProvides(order, IArchived)`](https://zopeinterface.readthedocs.io/en/latest/api/declarations.html#zope.interface.alsoProvides)
  marks one instance, so two objects of the same class can resolve to different adapters.
  Neither `typing.Protocol` nor `functools.singledispatch` has an equivalent; both decide from
  the type.

## Build notes (maintainers)

### Recipe shape

`meta.yaml` is a name and a version: setuptools builds one small C extension straight from the
sdist. What matters is that upstream declares that extension **optional** — `optional_build_ext`
in `setup.py` catches `CCompilerError`, `DistutilsExecError` and `OSError` around
`build_extension`, warns to the build log and carries on. A cross-compile that fails to produce
`_zope_interface_coptimizations` therefore still yields an installable, importable, passing
wheel whose consumers all silently run the pure-Python fallback, and neither the metadata nor
`import zope.interface` distinguishes the two cases.

### Upgrade hazards

The C module supplies exactly ten names — `LookupBase`, `VerifyingBase`, `SpecificationBase`,
`InterfaceBase`, `ClassProvidesBase`, `ObjectSpecificationDescriptor`, `implementedBy`,
`providedBy`, `getObjectSpecification` and `adapter_hooks` — and this page rests on that list.
If a bump stops routing `LookupBase` through `_use_c_impl`, the check readers are told to run
keeps returning a value and stops meaning anything.

The extension's filename differs by leg: cp312 Android slices ship
`_zope_interface_coptimizations.cpython-312.so`, cp313 and cp314 ship
`…cpython-3<minor>-<triplet>.so`, and iOS slices end in `-iphoneos` or `-iphonesimulator`. All
carry the `cpython-<minor>` tag Android's relocation keys on, so match `cpython-*` rather than a
full filename.

### Re-verification checklist

- **The extension exists in every slice.** `unzip -l` each wheel and look for the `.so`; a green
  build is not evidence, because upstream swallows a compile failure. All 18 published 8.5
  slices carry it.
- **It is the implementation in use**, not merely importable: read `LookupBase.__module__` on
  device, not on the build host.
- **iOS filetype.** All nine iOS slices are `MH_DYLIB` (`otool -hv`) at 8.5, so the `MH_BUNDLE`
  conversion other recipes need never engages. Recheck rather than assume.
- **`zope/` still has no `__init__.py` in the wheel.** The consumer note about namespace
  packages stops applying the day upstream adds one.
- **Sizes, the test-suite share and the cleanup globs.** Every figure above is quoted from the
  wheels and all of them move with any upstream file change.

### Coverage gaps

The device tests declare an interface, declare a provider, call `verifyObject` and import the
extension module. They do not assert that `LookupBase` came from it, nor exercise the adapter
registry, `adapter_hooks`, `verifyClass`, `MultipleInvalid` or per-instance declarations, and
nothing on device inspects the namespace-package layout. The `typing.Protocol` and `abc`
comparisons, the lookup rates and the cleanup-glob behaviour were established on desktop, not on
a phone.
