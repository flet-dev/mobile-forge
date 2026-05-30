"""Generic recipe-tester app — runs bundled pytest tests and emits the EXIT
sentinel to console.log (which Flet redirects via $FLET_APP_CONSOLE).

How this works on a CI runner:
  1. `stage_recipe.sh <recipe>` copies `recipes/<recipe>/test_*.py` (or the
     `recipes/<recipe>/test/` dir with assets) into `./recipe_tests/`, and
     generates `pyproject.toml` from `pyproject.toml.tpl` with the recipe
     pinned as a dependency.
  2. `flet build apk` / `flet build ios-simulator` bundles this app + the
     staged tests + the recipe wheel into a deployable.
  3. The CI installs and launches the app on an emulator/simulator. The
     `_run_pytest()` thread runs pytest, prints a Toga-shaped EXIT sentinel
     to stdout. Flet's launcher has rebound `sys.stdout`/`sys.stderr` to a
     line-buffered file at $FLET_APP_CONSOLE, so the sentinel and any
     pytest output land in that file within ~1ms of being written.
  4. The host pulls `console.log` (Android: `adb pull` from the app cache
     dir; iOS sim: read directly from `xcrun simctl get_app_container`),
     greps for `>>>>>>>>>> EXIT N <<<<<<<<<<`, sets N as the job's exit code.

Local dev usage:
  cd tests/recipe-tester
  ./stage_recipe.sh <recipe-name> [<version>]
  uv sync --dev
  PIP_FIND_LINKS=$(pwd)/../../dist uv run --no-sync flet build apk --arch arm64-v8a
  adb install -r build/apk/recipe-tester.apk
  adb shell monkey -p com.flet.recipe_tester -c android.intent.category.LAUNCHER 1

See `playground/test-recipes-on-mobile-PLAN.md` (§2c) for the full design.
"""

import threading
import time

import flet as ft

# Module-level state the GUI thread inspects to render "done" once pytest exits.
EXIT_CODE: int | None = None
DONE = False


def _run_pytest() -> None:
    """Run bundled tests in a background thread; emit Toga-shaped EXIT sentinel.

    Runs OFF the GUI thread so Flet's event loop keeps turning and the
    line-buffered console.log writes flush within ~1ms. If we ran pytest
    synchronously in `main()`, the event loop wouldn't yield until after
    pytest returned, and the sentinel might sit in a Python-level buffer
    until the next loop iteration.
    """
    global EXIT_CODE, DONE
    import pytest

    # Defensive flags rationale (plan §5 Q8):
    #   --rootdir recipe_tests : don't walk the bundled stdlib zip looking
    #                            for conftest.py
    #   -p no:cacheprovider    : don't try to write .pytest_cache/ on a
    #                            potentially read-only mobile FS
    #   --capture=no           : let test prints reach console.log too
    #                            (default pytest capture hides stdout)
    #   --no-header --tb=short : compact output for console.log
    EXIT_CODE = pytest.main(
        [
            "-v",
            "--rootdir", "recipe_tests",
            "-p", "no:cacheprovider",
            "--capture=no",
            "--no-header",
            "--tb=short",
            "recipe_tests/",
        ]
    )

    # Repeat the sentinel six times with 0.5s sleeps to defeat any buffering
    # in the host log-tailer's catch-up window. Pattern matches BeeWare
    # Briefcase's default `exit_regex` so the same shape works if we ever
    # want to slot this app under Briefcase.
    for _ in range(6):
        print(f">>>>>>>>>> EXIT {EXIT_CODE} <<<<<<<<<<", flush=True)
        time.sleep(0.5)
    DONE = True


def main(page: ft.Page) -> None:
    page.appbar = ft.AppBar(title=ft.Text("recipe-tester"))
    page.add(
        ft.Text(
            "Running pytest on bundled recipe tests…",
            size=14,
            weight=ft.FontWeight.BOLD,
        )
    )
    page.add(
        ft.Text(
            "This screen is informational only. CI reads console.log "
            "directly; the GUI is just the substrate Flet needs to keep the "
            "event loop alive.",
            size=11,
            color=ft.Colors.GREY,
        )
    )

    threading.Thread(target=_run_pytest, daemon=True).start()


ft.run(main)
