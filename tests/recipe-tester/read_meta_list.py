#!/usr/bin/env python3
"""Print a list-valued field from a recipe meta.yaml, one item per line.

Usage:
    read_meta_list.py <meta.yaml> <dotted.key>

e.g. `extract_packages` or `test.requires`. The meta is rendered
Jinja-then-YAML the way forge loads it (`forge/package.py`), so a
version-templated meta still parses. A missing key (at any level) or a non-list
value prints nothing. Run hermetically so jinja2/pyyaml are present regardless of
the caller's environment::

    uv run --no-project --with jinja2 --with pyyaml python3 read_meta_list.py <meta> <key>
"""

import sys

import jinja2
import yaml

meta_path, dotted_key = sys.argv[1], sys.argv[2]
text = open(meta_path, encoding="utf-8").read()

# Same render inputs forge uses; the fields we read are SDK-independent, but pass
# a concrete context so metas that Jinja-branch on sdk/arch/version still render.
rendered = jinja2.Template(text).render(
    sdk="android",
    sdk_version="24",
    arch="arm64-v8a",
    version=None,
    py_version=sys.version_info,
)

node = yaml.safe_load(rendered) or {}
for key in dotted_key.split("."):
    node = node.get(key) if isinstance(node, dict) else None

if isinstance(node, list):
    for item in node:
        print(item)
