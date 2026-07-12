#!/usr/bin/env python3
"""Print a recipe meta.yaml's top-level ``extract_packages`` list, one per line.

Used by ``stage_recipe.sh`` to feed ``[tool.flet.android].extract_packages`` in
the generated recipe-tester ``pyproject.toml``. The meta is Jinja-then-YAML like
forge loads it (``forge/package.py``), so a version-templated meta still parses.
Run hermetically, e.g.::

    uv run --no-project --with jinja2 --with pyyaml python3 read_extract_packages.py <meta.yaml>
"""
import sys

import jinja2
import yaml

meta_path = sys.argv[1]
text = open(meta_path, encoding="utf-8").read()

# Same render inputs forge uses; extract_packages is SDK-independent, but pass a
# concrete context so metas that Jinja-branch on sdk/arch/version still render.
rendered = jinja2.Template(text).render(
    sdk="android",
    sdk_version="24",
    arch="arm64-v8a",
    version=None,
    py_version=sys.version_info,
)
meta = yaml.safe_load(rendered) or {}

for entry in meta.get("extract_packages") or []:
    print(entry)
