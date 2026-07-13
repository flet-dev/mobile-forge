[project]
name = "recipe-tester"
version = "0.1.0"
description = "Generic in-app pytest runner for mobile-forge recipe wheels."
requires-python = ">=3.10"

dependencies = [
    "flet>=0.86.0.dev0",
    "pytest",
    # `stage_recipe.sh` rewrites the line below to pin the recipe under test (e.g. `"numpy==2.2.2"`),
    # and replaces the token line after it with any test-only deps declared in
    # the recipe's meta.yaml `test.requires` (nothing emitted when none declared).
    "__RECIPE_DEP__",
    __TEST_DEPS__
]

[dependency-groups]
dev = [
    "flet[all]>=0.86.0.dev0",
]

[tool.flet]
artifact = "recipe-tester"

# Flet >=0.86 compiles the app to .pyc and strips the source by default, but pytest
# only collects .py test files — so the bundled recipe_tests would report "0 items"
# (EXIT 5). Keep the app source (main.py + recipe_tests/*.py) as .py. This only
# affects the app; bundled/package dependencies still get compiled.
[tool.flet.compile]
app = false

[tool.flet.app]
path = "."

# Flet 0.86 ships site-packages inside a compressed `sitepackages.zip` (imported
# via zipimport). Packages that read a bundled DATA file through a real `__file__`
# path (rather than `importlib.resources`) then fail on-device with
# `NotADirectoryError` because the parent is a zip, not a directory. List such
# "path-hungry" packages here to ship them extracted to disk instead. Populated
# per-recipe by `stage_recipe.sh` from each recipe's meta.yaml `extract_packages:`
# (empty `[]` — the default — is a no-op).
[tool.flet.android]
extract_packages = [__EXTRACT_PACKAGES__]

# TEMPORARY: pull serious_python from the branch carrying the unreleased iOS fixes
# so recipe tests validate against them BEFORE they ship in a published sp release:
#   - #223 interdependent-dylib framework relocation (reconcile_framework_install_names)
#     — unblocks pyarrow/llama iOS launch (dyld "Library not loaded @rpath/lib*.dylib")
#   - _SorefFinder package-__init__ native resolution (apsw et al.)
# flet merges this into the generated Flutter pubspec's dependency_overrides
# (recursive merge, so the nested `git = { … }` table passes straight through).
# REMOVE this block once serious_python is released with these fixes.
[tool.flet.flutter.pubspec.dependency_overrides]
serious_python = { git = { url = "https://github.com/flet-dev/serious-python.git", ref = "fix/soref-package-init", path = "src/serious_python" } }
serious_python_darwin = { git = { url = "https://github.com/flet-dev/serious-python.git", ref = "fix/soref-package-init", path = "src/serious_python_darwin" } }
serious_python_android = { git = { url = "https://github.com/flet-dev/serious-python.git", ref = "fix/soref-package-init", path = "src/serious_python_android" } }
serious_python_platform_interface = { git = { url = "https://github.com/flet-dev/serious-python.git", ref = "fix/soref-package-init", path = "src/serious_python_platform_interface" } }
