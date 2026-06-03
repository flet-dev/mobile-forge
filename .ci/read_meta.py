# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "jinja2"]
# ///
"""Read fields from a recipe's meta.yaml and print them as one
tab-separated line:

    <version>\t<build_number>\t<space-joined-platforms>

Examples:

    2.2.2\t0\t                    # numpy (no platforms, no build override)
    1.6.1\t0\tandroid             # pyjnius
    1.2.3\t0\tios                 # pyobjus
    8.11.0\t1\t                   # flet-libcurl (uses Jinja `{% set %}`)

Used by the build-wheels.yml matrix step to (a) skip per-recipe
(platform, pkg) combinations that the recipe opts out of, and (b)
include the version + build number in each job's display name.

A standalone PEP 723 script rather than an inline here-doc in the
workflow — testable in isolation, declares its own pyyaml/jinja2 deps
so the runner doesn't need them preinstalled.

meta.yaml is a Jinja template (forge renders it before YAML-parsing).
We render it the same way, with a generic SDK context — the fields we
read here are platform-independent, so any plausible render values
work. Picking `sdk='android'` is arbitrary and convenient.

On any failure (file missing, template invalid, YAML invalid,
schema-shape unexpected) we print a blank-but-tab-aligned line so the
bash caller's `IFS=$'\\t' read -r ver build platforms` doesn't blow up
— the caller treats empty fields as "unknown, fall back to whatever
the package spec or workflow defaults already say."""

import sys

import jinja2
import yaml


def main(path: str) -> int:
    version = ""
    build_number = ""
    platforms = ""
    try:
        with open(path) as f:
            tpl = f.read()
        rendered = jinja2.Template(tpl).render(
            sdk="android",
            sdk_version=24,
            arch="arm64-v8a",
            version=None,
            py_version=(3, 12, 12),
        )
        meta = yaml.safe_load(rendered) or {}
        pkg = meta.get("package") or {}
        if "version" in pkg:
            version = str(pkg["version"])
        plat = pkg.get("platforms")
        if plat:
            platforms = " ".join(plat)
        # build.number defaults to 0 in the schema, but raw meta.yaml may
        # omit it. Match the schema default rather than treating it as
        # unknown.
        build = (meta.get("build") or {}).get("number", 0)
        build_number = str(build)
    except Exception:
        pass
    print(f"{version}\t{build_number}\t{platforms}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: read_meta.py <recipe-meta.yaml-path>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
