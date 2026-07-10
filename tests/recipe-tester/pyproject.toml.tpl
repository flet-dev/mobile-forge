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
    # the recipe's tests/requirements.txt (nothing emitted when the file is absent).
    "__RECIPE_DEP__",
    __TEST_DEPS__
]

[dependency-groups]
dev = [
    "flet[all]>=0.86.0.dev0",
]

[tool.flet]
artifact = "recipe-tester"

# Flet 0.86 compiles the app to .pyc and strips the source by default, but pytest
# only collects .py test files — so the bundled recipe_tests would report "0 items"
# (EXIT 5). Keep the app source (main.py + recipe_tests/*.py) as .py. This only
# affects the app; `--compile-packages` still compiles the bundled dependencies.
[tool.flet.compile]
app = false

[tool.flet.app]
path = "."
