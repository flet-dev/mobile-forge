# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Print the space-joined `package.platforms` list from a recipe's
meta.yaml, or nothing if the field is absent / unparseable.

Used by the build-wheels.yml matrix step to skip per-recipe (platform, pkg)
combinations the recipe explicitly opts out of. Run via:

    uv run --script .ci/read_platforms.py recipes/pyjnius/meta.yaml

Why a standalone script instead of an inline here-doc in the workflow:
  - testable in isolation (`uv run --script ... fixture.yaml`)
  - declares its own deps inline (PEP 723), so no `pip install` step
    or system-package assumption is needed in the runner
  - re-usable from `.ci/common.sh` so other scripts share one source
    of truth for "what platforms does this recipe support?"

Some meta.yamls (numpy, etc.) embed bare Jinja blocks that are not valid
YAML, so we strip Jinja delimiters before parsing. `platforms` is
platform-independent metadata — it must NOT live inside a Jinja
conditional — so the stripped view is enough to read it accurately.

Any failure (file missing, YAML invalid, no `package`, no `platforms`)
prints nothing. The bash caller treats empty output as "no declaration
→ build on every platform"."""

import re
import sys

import yaml


def main(path: str) -> int:
    try:
        with open(path) as f:
            text = f.read()
        text = re.sub(r"\{%.*?%\}", "", text, flags=re.DOTALL)
        text = re.sub(r"\{\{.*?\}\}", '""', text)
        meta = yaml.safe_load(text) or {}
        platforms = (meta.get("package") or {}).get("platforms")
        if platforms:
            print(" ".join(platforms))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: read_platforms.py <recipe-meta.yaml-path>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
