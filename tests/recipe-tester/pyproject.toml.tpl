[project]
name = "recipe-tester"
version = "0.1.0"
description = "Generic in-app pytest runner for mobile-forge recipe wheels."
requires-python = ">=3.10"

dependencies = [
    "flet",
    "pytest",
    # `stage_recipe.sh` rewrites the line below to pin the recipe under test (e.g. `"numpy==2.2.2"`),
    # and replaces the token line after it with any test-only deps declared in
    # the recipe's tests/requirements.txt (nothing emitted when the file is absent).
    "__RECIPE_DEP__",
    __TEST_DEPS__
]

[dependency-groups]
dev = [
    "flet[all]",
]

[tool.flet]
artifact = "recipe-tester"

[tool.flet.app]
path = "."
