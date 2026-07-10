"""Generic recipe-tester app — runs bundled pytest tests and emits the EXIT
sentinel to console.log (which Flet redirects via $FLET_APP_CONSOLE).

How this works on a CI runner:
  1. `stage_recipe.sh <recipe>` copies `recipes/<recipe>/tests/` (test files
     plus any asset files) into `./recipe_tests/`, and
     generates `pyproject.toml` from `pyproject.toml.tpl` with the recipe
     pinned as a dependency.
  2. `flet build apk` / `flet build ios-simulator` bundles this app + the
     staged tests + the recipe wheel into a deployable.
  3. The CI installs and launches the app on an emulator/simulator. The
     `_run_pytest()` thread runs pytest, then prints the EXIT sentinel
     to stdout. Flet's launcher has rebound `sys.stdout`/`sys.stderr` to a
     line-buffered file at $FLET_APP_CONSOLE, so the sentinel and any
     pytest output land in that file within ~1ms of being written.
  4. The host pulls `console.log` (Android: `adb pull` from the app cache
     dir; iOS sim: read directly from `xcrun simctl get_app_container`),
     greps for `>>>>>>>>>> EXIT N <<<<<<<<<<`, sets N as the job's exit code.

Local dev usage:
  cd tests/recipe-tester
  ./stage_recipe.sh <recipe-name> [<version>]
  PIP_FIND_LINKS=$(pwd)/../../dist uvx --with flet-cli flet build apk --arch arm64-v8a --yes
  adb install -r build/apk/recipe-tester.apk
  adb shell monkey -p com.flet.recipe_tester -c android.intent.category.LAUNCHER 1
"""

import threading

import flet as ft

# Module-level state the GUI thread inspects to render "done" once pytest exits.
EXIT_CODE: int | None = None
DONE = False


def _run_pytest() -> None:
    """Run bundled tests in a background thread; emit EXIT sentinel.

    Runs OFF the GUI thread so Flet's event loop keeps turning and the
    line-buffered `console.log` writes flush within ~1ms. If we ran pytest
    synchronously in `main()`, the event loop wouldn't yield until after
    pytest returned, and the sentinel might sit in a Python-level buffer
    until the next loop iteration.
    """
    global EXIT_CODE, DONE
    import pytest

    EXIT_CODE = pytest.main(
        [
            "-v",
            "--rootdir",
            "recipe_tests",  # don't walk the bundled stdlib zip looking for conftest.py
            "-p",
            "no:cacheprovider",  # don't try to write .pytest_cache/ on a potentially read-only mobile FS
            "--capture=no",  # let test prints reach console.log too (default pytest capture hides stdout)
            "--no-header",
            "--tb=short",  # compact output for console.log
            "recipe_tests/",
        ]
    )

    # Single emit is enough: stdout is rebound to $FLET_APP_CONSOLE opened
    # with `buffering=1`, so the line is in the kernel page cache as soon
    # as `print(..., flush=True)` returns; the host's wait_for_console.sh
    # polls the file every 2s and grep-matches on a complete line. The
    # 6×0.5s loop this replaces was a cargo-culted Toga pattern that
    # defended against logcat/NSLog stream buffering — neither of which
    # is in our IO path.
    print(f">>>>>>>>>> EXIT {EXIT_CODE} <<<<<<<<<<", flush=True)
    DONE = True


def main(page: ft.Page) -> None:
    page.appbar = ft.AppBar(title=ft.Text("Mobile-Forge Recipe Tester"))
    page.add(
        ft.Text(
            "Running pytest on bundled recipe tests…",
            size=14,
            weight=ft.FontWeight.BOLD,
        ),
        ft.Text(
            "This screen is informational only. CI reads console.log directly; "
            "the GUI is just the substrate Flet needs to keep the event loop alive.",
            size=11,
            color=ft.Colors.GREY,
        ),
    )

    # Run pytest in a background thread
    threading.Thread(target=_run_pytest, daemon=True).start()


ft.run(main)
