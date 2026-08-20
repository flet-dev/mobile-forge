Mobile Forge
============

This is a forge-like environment that can be used to build wheels for mobile platforms.
It is currently only tested for iOS, but in theory, it should also be usable for
Android. Contributions to verify Android support, and to add more package recipes, are
definitely encouraged.

Usage
-----

Mobile Forge builds wheels against pre-compiled Python "support" packages for the host
platforms (iOS and Android). You no longer need to compile or download those packages
yourself — ``setup.sh`` fetches them for you.

Getting started
~~~~~~~~~~~~~~~

1. Install `uv <https://docs.astral.sh/uv/>`__ (used to create the build virtual
   environment)::

    $ curl -LsSf https://astral.sh/uv/install.sh | sh

2. Clone this repository and source the setup script for the Python version you want to
   use::

    $ git clone https://github.com/flet-dev/mobile-forge.git
    $ cd mobile-forge
    $ source ./setup.sh 3.13

   On first run this downloads the matching mobile-forge support package(s) into
   ``downloads/`` (gitignored), creates a Python virtual environment, installs mobile
   forge, builds the platform dependency wheels, and prints some hints at ``forge``
   commands you can run. Subsequent runs reuse the cached download and the existing
   virtual environment.

   By default, on macOS both iOS and Android packages are downloaded; on Linux only
   Android. To restrict this, pass the platform(s) as a second argument::

    $ source ./setup.sh 3.13 iOS
    $ source ./setup.sh 3.13 android
    $ source ./setup.sh 3.13 iOS,android

Bring your own support package
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you maintain your own support packages (for example, a local
`Python-Apple-support <https://github.com/beeware/Python-Apple-support>`__ build), set
``MOBILE_FORGE_IOS_SUPPORT_PATH`` and/or ``MOBILE_FORGE_ANDROID_SUPPORT_PATH`` to the
extracted trees before sourcing ``setup.sh``. When set, these paths are authoritative —
``setup.sh`` validates them and skips the automatic download. Per-version overrides
(``MOBILE_FORGE_IOS_SUPPORT_PATH_3_13`` etc.) are also honored, so several Python
versions can be configured side-by-side.

Building a package
~~~~~~~~~~~~~~~~~~

The ``recipes`` folder contains recipes for packages. ``lru-dict`` is a good first
package to try::

    $ forge iOS lru-dict

Or, to build a wheel for a single architecture::

    $ forge iphonesimulator:arm64 lru-dict

Once this command completes, there should be a wheel for each platform in the ``dist``
folder. A log for each successful build will be in the ``logs`` folder; a log for each
unsuccessful build (if there are any) will be in the ``errors`` folder.

The special snowflakes
~~~~~~~~~~~~~~~~~~~~~~

Mobile Forge is trying to support multiple packages, building on multiple Python
versions, for multiple architectures; and some of those Python versions were released
before the release of ARM64 macOS hardware. As a result, some versions of some packages
have some quirks that must be taken into account.

Pandas
^^^^^^

Pandas uses a meta-package named ``oldest-supported-numpy`` to ensure ABI compatibility
during compilation. However, this can install a different version of numpy, depending on
the platform. This is especially problematic for Python 3.9, because the minimum
supported version for Python 3.9 on ARM64 is different to the version that is installed
for x86_64. Mobile-forge produces a replacement ``oldest-supported-numpy`` package, tagged
as version 2999.1.1, which ensures that consistent versions are available for build
purposes; however, this wheel *should not* be published.

Cryptography
^^^^^^^^^^^^

Cryptography currently builds a *very* old version (3.4.8). This is the last version
that could be built without a Rust compiler. The recipe works as is on all Python
versions *except* Python 3.8 on ARM64, because there was no ARM64-compatible wheel
published for cffi 1.15.1. However, if you run::

    $ pip wheel -w dist --no-deps cffi==1.15.1

you can build a universal Python3.8 CFFI wheel for CFFI 1.15.1, which can be used to
satisfy this build-time requirement.

What now?
---------

To include these wheels in a test project, you can add the ``dist`` folder as a links
source in your ``requires`` definition in your Briefcase ``pyproject.toml``. For
example, the following will install the ``lru-dict`` wheels you've just compiled::

    requires = [
        "--find-links", "/path/to/mobile-forge/dist",
        "lru-dict",
    ]

Adding your own packages
------------------------

If there's a package that you want that doesn't have an existing recipe, you can add a
recipe for that package.

Create a directory in ``recipes``. The name of the directory must be in PyPI normalized
form (PEP 503). Alternatively, you can create this directory somewhere else, and pass
its path when calling ``forge``.

Inside the recipe directory, add the following files.

* A ``meta.yaml`` file. This supports a subset of Conda syntax, defined in ``meta-schema.yaml``.
* A ``tests`` directory, to run on a target installation. This should contain a pytest suite
  which imports the package and does some basic checks. Every file in it is bundled into the
  on-device test app, so keep it to tests and their fixtures.
* A ``README.md``, documenting the package **for the people who will use it in a Flet app** —
  see `Documenting a recipe`_ below.
* Optionally, an ``examples`` directory of runnable Flet apps — again, see
  `Documenting a recipe`_.
* Optionally, one or more patch files in a folder named ``patches``. These patches will be
  applied when the source code is unpacked for a given platform. **Every patch explains
  itself**: put a plain-text description at the top of the file, above the first ``---``
  line, saying what the patch changes and why it is needed. ``patch(1)`` ignores everything
  before the first ``---``, so this is safe, and it means the explanation travels with the
  patch instead of living in a README that will drift from it.
* For non-Python packages, a ``build.sh`` script. This is the script that will be executed
  in the build environment build the package. This script should invoke any ``configure``,
  ``make``, or any other compilation steps needed to build the package. This script will be
  executed in an environment that defines the following environment variables:

    - ``AR`` - the ``AR`` value used to compile the host Python, as determined from
      ``sysconfig``
    - ``CC`` - the ``CC`` value used to compile the host Python, as determined from
      ``sysconfig``.
    - ``CFLAGS`` - the ``CFLAGS`` value used to compile the host Python, as determined
      from ``sysconfig``, augmented with the include paths for the SDK, and
      ``opt/include`` in the host environment's site-packages.
    - ``LDFLAGS`` - the ``CFLAGS`` value used to compile the host Python, as determined
      from ``sysconfig``, augmented with the library paths for the SDK, and
      ``opt/lib`` in the host environment's site-packages.
    - ``CPU_COUNT`` - The number of CPUs that are available, as determined by
      ``multiprocessing.cpu_count()``
    - ``HOST_TRIPLET`` - the GCC compiler triplet for the host platform (e.g.,
      ``aarch64-apple-ios12.0-simulator``)
    - ``BUILD_TRIPLET`` - the GCC compiler triplet for the build platform (e.g.,
      ``aarch64-apple-darwin``)
    - ``PREFIX`` - a location where the compiled package can be installed in preparation
      for packaging.

  This script should install the package into ``$PREFIX``. Mobile Forge will package any
  content installed into ``$PREFIX`` into a "wheel" that can be installed as a host
  requirement.

Python-based projects
~~~~~~~~~~~~~~~~~~~~~

All Python projects are compiled using ``python -m build``, using a clean `crossenv
<https://github.com/benfogle/crossenv>`__ virtual environment for each platform of a
package. Any PEP518 build requirements will be included in both the host and build
environments.

If you're lucky, all you'll need to do is define a ``meta.yaml`` that describes the
package name and version: e.g.,::

    package:
      name: blis
      version: 0.4.1

If this doesn't result in a successful build, it will likely be for one of the following
reasons:

1. **The build process has a dependency on a system library**. For example, Pillow has a
   dependency on ``libjpeg``. ``libjpeg`` isn't available on PyPI; but it *is* possible
   to build a "wheel" for ``libjpeg``, so it can be specified as a requirement.

   A non-python "wheel" is constructed by compiling the package for your target platform,
   then installing it into a folder named ``opt``. As a result of this "install", you'll
   usually end up with an ``opt/include`` and ``opt/lib`` folder; Mobile Forge will then
   wrap up this ``opt`` folder in a wheel, along with Python wheel metadata.

   When this "wheel" is specified as a host requirement, the "wheel" will be unpacked
   into the site packages folder of your cross-compilation host environment. This path
   the ``include`` and ``lib`` paths will be automatically included in the
   ``CFLAGS``/``LDFLAGS`` environment variables when the Python build is executed.

2. **The build process has a dependency on external tooling**. Mobile Forge will
   configure a C and C++ compiler using the same configuration that was used to compile
   the support libraries; however a package may require addition build tooling (e.g., a
   Fortran compiler) to complete the build. If this is the case, you'll need to find a
   version of the tool that can target mobile platforms, and work out how to modify the
   build process to apply any necessary compiler flags.

3. **The build script has platform-specific logic**. For example,
   if the ``setup.py`` file contain an ``if sys.platform == ...`` clauses, it is unlikely
   that a mobile platform will trigger the right logic.

If you need to make any alterations to a project's source code for a build to succeed,
you can provide those patches by putting them in one or more files in a folder named
``patches`` in the recipe folder. These patches will be applied once the source code
has been unpacked.

Configure-based projects
~~~~~~~~~~~~~~~~~~~~~~~~

If the project includes a ``configure`` script, you will likely need to provide a patch
for ``config.sub``. ``config.sub`` is the tools used by ``configure`` to identify the
architecture and machine type; however, it doesn't currently recognize the host triples
used by Apple. If you get the error::

    checking host system type... Invalid configuration `arm64-apple-ios': machine `arm64-apple' not recognized
    configure: error: /bin/sh config/config.sub arm64-apple-ios failed

you will need to patch ``config.sub``. There are several examples of patched ``config.sub``
scripts in the packages contained in this repository, and in the Python-Apple-support
project; it is quite possible one of those patches can be used for the library you are
trying to compile. The ``config.sub`` script has a datestamp at the top of the file; that
can be used to identify which patch you will need.

Documenting a recipe
--------------------

A recipe produces a wheel, but what a Flet app author actually needs is the knowledge that
came out of building it: which ``pyproject.toml`` entries to add, where a database or cache
belongs on device, which platform behaves differently, what the wheel deliberately leaves
out. That knowledge lives **in the recipe directory**, next to the code it describes, so it
is reviewed in the same pull request and bumped in the same commit as the recipe itself.

``recipes/<name>/README.md``
    Written for the person adding the package to their app — not for the person building the
    wheel. GitHub renders it when someone opens the recipe directory, so it is also the page
    we link to from elsewhere. Sections, in this order, omitting any that do not apply
    (omit — never reorder, and never pad):

    #. An H1 with the pip name, then a short paragraph on what the package is and why you
       would use it on mobile.
    #. ``## Install`` — the ``pyproject.toml`` dependencies snippet, plus any ``[tool.flet.*]``
       tables the package needs. List dependencies bare (``"flet"``, ``"<package>"``): a bare
       requirement resolves to the latest release, and a version in a snippet people paste is
       a pin they will still be carrying two releases later. Where the package really does
       need a minimum Flet version, say so **in prose** next to the snippet, with the symptom
       of getting it wrong — not as a pin in the snippet. (The example's own
       ``pyproject.toml`` is the opposite case and *is* pinned — see below. One is material to
       imitate, the other is a combination to reproduce.)
    #. ``## Examples`` — a **link to** ``examples/`` and a one-line bullet per example, and
       nothing more. No code, not even an excerpt; no run commands; no description of what
       the app demonstrates. All of that lives in the example's own ``README.md``, which is
       the single source of truth for it — anything repeated here is a second copy to keep
       in sync, and it will not be kept in sync.
    #. ``## Usage in a Flet app`` — the heart of the page, written as a manual rather than a
       report. Lead with code the reader can paste: the two or three calls that do the job,
       and the Flet control the result goes into. Then ``###`` subsections, omitting any that
       do not apply — ``Storage`` (where files belong, in terms of Flet's app-storage
       environment variables), ``Threading``, one named for whatever this package actually
       makes you think about (``Rendering and memory``, ``Precision``, ``Model files``),
       ``App size`` (the figure *and* the lever: app bundle, split APKs, ``target_arch``),
       and ``Other considerations`` — where the desktop ``flet run`` wheel differs from the
       mobile one, and what to validate on a device because of it.
    #. ``## Things to know`` — bulleted gotchas and recommendations; the last consumer-facing
       section. State what breaks and the symptom it produces, not just the rule.
    #. ``## Build notes (maintainers)`` — the only maintainer-facing section, and the reason
       it is explicitly labelled: everything above it addresses the app author. Give it
       ``###`` subsections: ``Recipe shape`` (why it is built this way, and what was tried
       and rejected), ``Upgrade hazards``, ``Re-verification checklist`` and ``Coverage
       gaps`` — what the on-device tests do *not* exercise, so nobody mistakes a green run
       for full cover. It does
       **not** explain the patches or the build flags. A patch explains itself in its own
       preamble, and a ``meta.yaml`` setting is explained in a comment next to it; repeating
       either here just creates a third copy to keep in sync. What belongs here is only what
       has no home in those two files: why the recipe has the shape it does, where that is not
       obvious; what was tried and rejected, which no file records; and above all **what to
       re-verify when bumping**, since the sections above make consumer-facing claims that a
       bump can silently invalidate. Written that way the section is a maintenance checklist,
       not a re-explanation — and if nothing qualifies, omit it.

    Link every API reference the first time it appears — Flet controls, methods and
    environment variables to the Flet docs, the package's own API to its upstream docs — so
    a reader can click through instead of searching. Check the anchor resolves; note that
    flet.dev canonicalises to a trailing slash before the fragment
    (``…/environment-variables/#flet_app_storage_data``).

    Cross-link sibling recipes freely, but **never let a sentence's meaning depend on what
    another page currently says**. A link is navigation; it is not a place to keep a fact.
    "The cost is the same one ``psutil``'s page states" and "see that page for the numbers"
    both stop making sense the moment the other page is edited, and nothing here would show
    it had gone stale. State the fact on this page, in full, and let the link be an invitation
    rather than a dependency. Citing a measurement made while documenting another package is
    fine and often valuable — "for the same Flet version ``pydantic-core`` reports no
    ``__file__`` at all on Android" — because that is a claim about the *package*, checkable
    against the wheel, not a claim about the *page*.

    **Sizes are decimal** — MB is 10⁶ bytes, KB is 10³, matching how a wheel's own byte count
    reads and how package indexes report it. ``du`` and the Finder use binary units, so a
    maintainer re-measuring a "1.7 MB" payload with ``du -h`` sees 1.6 M and can mistake a unit
    for a regression. Quote decimal, and where a page invites re-measurement say which tool to
    use — the same care a memory figure needs, since ``sys.getsizeof`` and resident-set growth
    answer different questions and can differ by a factor of four for the same object.

    **Write a manual, not a report.** The reader is adding a package to an app, not auditing
    a wheel. Wheel sizes, symbol tables, ``DT_NEEDED`` lists and byte-exact inventories are
    maintainer material: either they support a piece of consumer advice — a size figure that
    justifies narrowing ``target_arch``, a missing symbol that explains a missing feature — or
    they belong under ``## Build notes (maintainers)``, or nowhere. Prefer a round number and
    a range ("approximately 40–41 MB compressed") to false precision, and spend the words on
    what the reader should *do*. A recipe page that runs much past two hundred lines is
    usually a report wearing a manual's headings.

    Do not restate the recipe version — ``meta.yaml`` is the source of truth and prose goes
    stale on the first bump. Claims about the wheel should be checked against the wheel, and
    claims about on-device behaviour should be backed by a test in ``tests/``.

``recipes/<name>/examples/<example>/``
    A complete, runnable Flet app per example: ``src/main.py`` with
    ``[tool.flet.app] path = "src"``, its own ``pyproject.toml``, a short ``README.md``
    saying what it demonstrates and how to run it, and a ``.gitignore`` for whatever running
    it produces (virtualenv, caches, databases, ``uv.lock``). Use ``src/`` even for a single
    file: ``path = "."`` packages the *whole* directory into the app, so the README,
    the ``pyproject.toml`` and any stray ``__pycache__``/``.ruff_cache`` ship inside it —
    and ``src/assets/`` is where bundled models or images belong when an example needs them.
    One example is the
    default; add another only for a genuinely distinct mode a user would choose between (sync
    versus async, and the like) — two examples that differ only in their SQL or their model
    file are one example. Each app must show a result computed by the package on screen, and
    must build as-is, because the per-example ``pyproject.toml`` is itself part of what is
    being taught.

    **Keep** ``main.py`` **to the app, and put the package's work in its own module.** A
    single file that mixes Flet layout with the library's real code is harder to read than
    the two files it should have been, and the layout ends up burying the part the reader
    came for. ``main.py`` holds the UI and its wiring — the controls, the handlers, the
    background-thread plumbing — and imports what it needs from a sibling module named for
    the domain (``shapes.py``, ``document.py``), which owns the constants and the functions
    that actually use the package and returns plain values. ``src/`` is the package root, so
    the import is flat: ``from shapes import analyse, scene``. As a rule of thumb ``main.py``
    stays around a hundred lines; when it grows past that, the excess is usually domain code
    that wants moving. A genuinely tiny example may stay one file, but reach for the split
    before writing a third screenful.

    **Every function in the example carries a docstring**, including ``main`` and the nested
    handlers. Say what it does and, where it is not obvious, why it is shaped that way — the
    example is teaching material, and a reader should never have to infer a function's job
    from its body. Keep them proportionate: a line for a small helper, a few sentences for
    the one doing the package's real work. The same restraint applies as to comments — a
    docstring that restates the code is noise.

    **Pin the example's dependencies with** ``==`` — both Flet and the recipe's own package.
    The example is the artifact that gets built and run on a device, so its pins are the
    record of a combination that was verified; left floating, it silently drifts onto
    versions nobody tested and the past combination is unrecoverable. Bumping a recipe
    therefore means bumping its example's pin and rebuilding it, which makes the example a
    live regression test of the bump. The one exception is a recipe whose version varies by
    Python (cryptography ships 43.0.1 for cp312/cp313 and 48.0.0 for cp314): a single ``==``
    would fail to resolve on the other legs, so leave that package unpinned and pin only Flet.

    **Raise** ``requires-python`` **to the floor of what you pinned.** ``flet create`` writes
    ``>=3.10``, and uv resolves for every version in that range rather than only the
    interpreter in use — so an ``==`` pin on a package whose own floor is higher makes the
    lowest split unsatisfiable and ``flet build`` fails outright with *No solution found when
    resolving dependencies for split*. At the versions used here ``numpy``, ``pandas`` and
    ``scikit-learn`` need ``>=3.11`` and ``scipy`` needs ``>=3.12``. A stale ``.venv`` or
    ``uv.lock`` hides this completely, so check it the way a consumer meets it: copy the
    ``pyproject.toml`` alone into an empty directory and run ``uv lock`` there. A build that
    reused an existing lock proves nothing.

    Examples belong here and **never** under ``tests/``: everything in ``tests/`` is copied
    into the on-device test app and collected by pytest. Do not put a ``meta.yaml`` in an
    example directory either — that is what marks a directory as a buildable recipe.

Neither path affects the build, and both are excluded from the CI changed-recipe filter, so
a documentation change never rebuilds that recipe. (The workflow itself still runs: with no
recipe detected as changed it falls back to the cheap smoke-test build that any non-recipe
change gets.)

Community
---------

Mobile Forge is part of the `BeeWare suite`_. You can talk to the community through:

* `@beeware@fosstodon.org on Mastodon <https://fosstodon.org/@beeware>`__

* `Discord <https://beeware.org/bee/chat/>`__

* The Mobile Forge `Github Discussions forum <https://github.com/beeware/mobile-forge/discussions>`__

We foster a welcoming and respectful community as described in our
`BeeWare Community Code of Conduct`_.

Contributing
------------

If you experience problems with Mobile Forge, `log them on GitHub`_. If you
want to contribute code, please `fork the code`_ and `submit a pull request`_.

.. _BeeWare suite: http://beeware.org
.. _Read The Docs: https://briefcase.readthedocs.io
.. _BeeWare Community Code of Conduct: http://beeware.org/community/behavior/
.. _log them on Github: https://github.com/beeware/mobile-forge/issues
.. _fork the code: https://github.com/beeware/mobile-forge
.. _submit a pull request: https://github.com/beeware/mobile-forge/pulls

Acknowledgements
----------------

This project draws significantly on the implementation and knowledge developed in the
`Chaquopy package builder
<https://github.com/chaquo/chaquopy/tree/master/server/pypi>`__. Although this is
largely a "clean room" reimplementation of that project, many details from that project
have been used in the development of this one.
