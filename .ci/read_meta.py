# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "jinja2"]
# ///
"""Read fields from a recipe's meta.yaml, rendered the way forge renders it.

Two modes:

  read_meta.py <meta.yaml>
      Print the build-matrix summary line — tab-separated:
          <version>\t<build_number>\t<space-joined-platforms>
      Examples:
          2.2.2\t1\t                 # numpy (no platforms)
          1.6.1\t1\tandroid          # pyjnius
          8.11.0\t2\t                # flet-libcurl (build bump)
      The fields here are platform-independent, so it renders with a generic
      `sdk='android'` context.

  read_meta.py <meta.yaml> <dotted.field> [android|ios]
      Print a single field from the rendered meta (e.g. `build.before_all`):
      one item per line for lists, the value as-is for scalars, empty if absent.
      The optional platform (default `android`) selects the SDK used to render
      Jinja, so platform-dependent fields (like before_all) resolve correctly.

Used by build-wheels.yml: the matrix step reads the summary line (to skip
platforms a recipe opts out of, and to label jobs); the build step reads
`build.before_all` per platform (each recipe's own host build-tool setup),
instead of hardcoding installs in the workflow.

A standalone PEP 723 script — testable in isolation, declares its own deps. On
any failure (missing file, bad template/YAML, absent field) it prints a
blank-but-valid result and exits 0, so the bash callers don't blow up: the
summary line stays tab-aligned, and a field with no value prints empty."""

import sys

import jinja2
import yaml


def _render(path: str, platform: str) -> dict:
    """Render the meta.yaml Jinja template for a platform and parse it."""
    if platform == "ios":
        ctx = dict(sdk="iphonesimulator", sdk_version="13.0", arch="arm64")
    else:
        ctx = dict(sdk="android", sdk_version=24, arch="arm64-v8a")
    with open(path) as f:
        rendered = jinja2.Template(f.read()).render(
            version=None, py_version=sys.version_info, **ctx
        )
    return yaml.safe_load(rendered) or {}


def _dig(meta: dict, dotted: str):
    """Resolve a dotted path (e.g. 'build.before_all') in the meta dict."""
    cur = meta
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def summary_line(path: str) -> str:
    """Return the matrix summary line: tab-separated version, build_number and
    space-joined platforms. These fields are platform-independent, so the meta
    is rendered with the generic android context. Any failure yields a
    blank-but-tab-aligned line so the bash caller's `read -r ...` never blows up."""
    version = build_number = platforms = ""
    try:
        meta = _render(path, "android")
        pkg = meta.get("package") or {}
        if "version" in pkg:
            version = str(pkg["version"])
        if pkg.get("platforms"):
            platforms = " ".join(pkg["platforms"])
        # build.number defaults to 1 in the schema, but raw meta.yaml may omit
        # it. Match the schema default rather than treating it as unknown.
        build_number = str((meta.get("build") or {}).get("number", 1))
    except Exception:
        pass
    return f"{version}\t{build_number}\t{platforms}"


def field_value(path: str, field: str, platform: str) -> str:
    """Return a single `dotted.field` from the meta rendered for `platform`
    (android|ios). Lists are returned newline-joined (one item per line),
    scalars stringified, and a missing/None value as the empty string."""
    try:
        val = _dig(_render(path, platform), field)
    except Exception:
        val = None
    if isinstance(val, (list, tuple)):
        return "\n".join(str(v) for v in val if str(v).strip())
    return "" if val is None else str(val)


def main(argv: list[str]) -> int:
    """CLI dispatch: `<meta.yaml>` alone prints the summary line; a trailing
    `<dotted.field> [platform]` prints that single field instead."""
    path = argv[0]
    if len(argv) == 1:
        print(summary_line(path))
    else:
        field = argv[1]
        platform = argv[2] if len(argv) > 2 else "android"
        print(field_value(path, field, platform))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "usage: read_meta.py <meta.yaml> [<dotted.field> [android|ios]]",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
