#!/usr/bin/env python3
"""Render-check a recipe's meta.yaml for all SDK contexts.

Catches Jinja syntax errors and SDK-conditional logic bugs cheaply, BEFORE
spending minutes on a `forge` build that would reveal them.

Usage: python verify_render.py recipes/<name>/meta.yaml

Output: for each SDK (iphoneos, iphonesimulator, android), prints the rendered
YAML and the parsed dict. If the meta.yaml is well-formed, the three outputs
will match the SDK-conditional structure you intended. Common bugs caught:

- Bare {%...%} that should be commented (# {%...%}): YAML parse error
- sdk == 'iOS' (never matches; should be 'iphoneos' / 'iphonesimulator')
- Missing # before a multi-line {% if %} block: extra blank lines in output
- Forgot to quote a YAML-float-like version (2.0 → 2)

Exit code 0 on success, 1 on any render/parse failure.
"""
from __future__ import annotations

import sys
from pathlib import Path


SDK_CONTEXTS = [
    {"sdk": "iphoneos", "sdk_version": "13.0", "arch": "arm64"},
    {"sdk": "iphonesimulator", "sdk_version": "13.0", "arch": "arm64"},
    {"sdk": "android", "sdk_version": "24", "arch": "arm64-v8a"},
]


def main():
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-to-meta.yaml>", file=sys.stderr)
        sys.exit(2)

    meta_path = Path(sys.argv[1])
    if not meta_path.is_file():
        print(f"ERROR: file not found: {meta_path}", file=sys.stderr)
        sys.exit(2)

    try:
        import jinja2
        import yaml
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). Run from inside the venv3.12 venv.", file=sys.stderr)
        sys.exit(2)

    template_text = meta_path.read_text(encoding="utf-8")
    any_failed = False

    for ctx in SDK_CONTEXTS:
        print(f"--- sdk={ctx['sdk']} arch={ctx['arch']} version={ctx['sdk_version']} ---")
        try:
            rendered = jinja2.Template(template_text).render(
                sdk=ctx["sdk"],
                sdk_version=ctx["sdk_version"],
                arch=ctx["arch"],
                version=None,
                py_version=None,
            )
        except jinja2.exceptions.TemplateError as e:
            print(f"  JINJA ERROR: {e}", file=sys.stderr)
            any_failed = True
            print()
            continue

        try:
            parsed = yaml.safe_load(rendered)
        except yaml.YAMLError as e:
            print(f"  YAML PARSE ERROR: {e}", file=sys.stderr)
            print(f"  Rendered output that failed to parse:")
            print(rendered)
            any_failed = True
            print()
            continue

        # Pretty print the parsed dict
        print(yaml.safe_dump(parsed, sort_keys=False, default_flow_style=False, indent=2).rstrip())
        print()

    if any_failed:
        print("One or more renders failed. Fix the meta.yaml before running forge.", file=sys.stderr)
        sys.exit(1)

    print("All renders parsed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
