"""Write the app's own settings file, then measure the C loader against the pure one."""

import os
import platform
import time

import flet as ft
import yaml

# Importing the C classes by name at module top is deliberate: PyYAML's fallback
# is silent — with the extension missing, `CSafeLoader` is simply absent from the
# namespace and `safe_load` keeps working several times slower. This turns that
# into an ImportError on the first line of the app instead.
from yaml import CSafeDumper, CSafeLoader
from yaml import _yaml as libyaml

EMIT = {"sort_keys": False, "allow_unicode": True}

SNIPPET = "version: 3\nretries:\t3\nlabel: café — edge\ntimeout: 2.5\nenabled: yes\n"

WEIGHTS = (2, 5, 3, 5)


def settings_path():
    """The settings file's home: app-private storage, or the cwd on desktop."""
    return os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "settings.yaml")


def make_settings(blocks):
    """Build a settings document with `blocks` service entries.

    Deterministic, so the same slider position gives the same bytes on every
    device and two phones can be compared directly. The non-ASCII `label` is
    there to make `allow_unicode` visible in the file that lands on disk.
    """
    return {
        "version": 3,
        "label": "café — edge fleet",
        "services": {
            f"service-{index:04d}": {
                "host": f"10.0.{index // 256}.{index % 256}",
                "port": 8000 + index,
                "retries": index % 5,
                "enabled": bool(index % 3),
                "tags": [f"tag-{index % 7}", f"zone-{index % 4}"],
                "timeout": 1.5 + (index % 10) / 10,
            }
            for index in range(blocks)
        },
    }


def fastest(work, reps=3):
    """Best of `reps` calls of `work`, in milliseconds, plus its last result."""
    best, result = None, None
    for _ in range(reps):
        started = time.perf_counter()
        result = work()
        elapsed = (time.perf_counter() - started) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    return best, result


def describe(document):
    """Name what a parse produced.

    Valid YAML is not necessarily a mapping: an emptied editor parses to `None`
    and a stray line of prose parses to a string, both without complaint from
    either loader. Saying so beats asserting a shape the user can delete.
    """
    if isinstance(document, dict):
        return f"{len(document)} key" if len(document) == 1 else f"{len(document)} keys"
    if document is None:
        return "empty document"
    return f"a bare {type(document).__name__}"


def parse_report(text, loader):
    """Parse `text` and describe the outcome the way an editing screen would.

    Returns the outcome, where it happened, and whether the exception's mark
    could produce a source snippet — the one thing the C loader cannot do, since
    libyaml never hands PyYAML the buffer the caret would point into. Marks count
    lines and columns from zero, so both are shifted for display.

    The catch is deliberately everything rather than `yaml.YAMLError`: a loader is
    only exception-safe up to the point where it hands a scalar to
    `SafeConstructor`, and that stage lets plain Python errors through — the
    perfectly ordinary typo `2026-02-30` reaches `datetime` and raises
    `ValueError`, `!!bool 'zzz'` raises `KeyError`, `!!timestamp 'zzz'` raises
    `AttributeError`, and a deeply nested flow collection exhausts the pure
    scanner's stack with `RecursionError`. All four are reachable from a text
    field, none is a `YAMLError`, and Flet reports an unhandled error in an event
    handler by crashing the session — so anything that gets this far belongs in
    the table under its own name, with no position to report.
    """
    try:
        document = yaml.load(text, Loader=loader)
    except Exception as error:
        mark = getattr(error, "problem_mark", None)
        where = f"line {mark.line + 1} col {mark.column + 1}" if mark else "unreported"
        snippet = "yes" if mark is not None and mark.get_snippet() else "none"
        return type(error).__name__, where, snippet
    return describe(document), "—", "—"


def build_line(page):
    """Name the versions, the capability, and how the extension got loaded.

    `_yaml.__file__` is the last field because it is the one expected to differ
    between the two platforms: Flet moves native extensions out of site-packages
    and leaves a marker at the import path, so this reports whatever the import
    system resolved rather than the name in the wheel.
    """
    origin = getattr(libyaml, "__file__", None)
    return (
        f"PyYAML {yaml.__version__} · libyaml {libyaml.get_version_string()} · "
        f"__with_libyaml__ {yaml.__with_libyaml__} · "
        f"Python {platform.python_version()} · {page.platform.value} · "
        f"_yaml.__file__ {os.path.basename(origin) if origin else 'none'}"
    )


def table_row(values):
    """One row of the results table: a `Text` per value, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(value, size=11, expand=weight)
            for value, weight in zip(values, WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """Write a settings file of the chosen size and report what reading it costs.

    Two claims get checked on the device rather than quoted: that the C loader is
    worth switching to, and that it is a drop-in — the C and pure emitters have to
    produce identical bytes and the two loaders identical objects, or the table
    says so instead of showing a speedup nobody can trust.
    """

    def show_count():
        """Report the document size the next run will write, as the slider moves."""
        caption.value = f"{int(size.value)} services per settings file"

    def start():
        """Hand a run to a background thread and lock the controls while it works.

        Driven by the slider's on_change_end, which fires once on release: the run
        writes a file, so a fresh one per pixel of the drag would have several
        writers on one path. The guard is read and set here rather than inside `run`
        because this body is synchronous, where `run_thread` only schedules: a
        `disabled` set inside the worker would not have happened yet when this
        handler returns and Flet pushes the control states, so a second release
        would be accepted. The parse button is disabled alongside it because it is
        the only other thing that rewrites part of this column, and it would be
        doing so from the event-loop thread while the worker writes from the pool.
        """
        if size.disabled:
            return
        size.disabled = True
        parse.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def run():
        """Emit the document, save it, read it back both ways, and fill the table.

        Neither loader releases the GIL, so this thread buys nothing but a handler
        that returns immediately. The try/except is load-bearing:
        `page.run_thread` discards whatever a worker raises, so a mistake in here
        would look like a screen that quietly stopped updating. It empties the
        table as well as writing the message, because timings and byte counts left
        over from the previous run read as though they describe the error.
        """
        try:
            document = make_settings(int(size.value))
            emit_c, text = fastest(
                lambda: yaml.dump(document, Dumper=CSafeDumper, **EMIT)
            )
            emit_pure, pure_text = fastest(
                lambda: yaml.dump(document, Dumper=yaml.SafeDumper, **EMIT)
            )

            path = settings_path()
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            with open(path, encoding="utf-8") as handle:
                on_disk = handle.read()

            load_pure, parsed_pure = fastest(lambda: yaml.safe_load(on_disk))
            load_c, parsed_c = fastest(lambda: yaml.load(on_disk, Loader=CSafeLoader))

            emitted = len(text.encode())
            load_pure, load_c = round(load_pure, 2), round(load_c, 2)
            emit_pure, emit_c = round(emit_pure, 2), round(emit_c, 2)

            summary.value = (
                f"{len(document['services'])} services · {os.path.basename(path)} "
                f"{os.path.getsize(path):,} B on disk"
            )
            results.controls = [
                table_row(("step", "call", "ms", "result")),
                ft.Divider(height=1),
                table_row(
                    (
                        "emit",
                        "yaml.safe_dump",
                        f"{emit_pure:.2f}",
                        f"{len(pure_text.encode()):,} B",
                    )
                ),
                table_row(
                    (
                        "emit",
                        "Dumper=CSafeDumper",
                        f"{emit_c:.2f}",
                        "identical bytes" if pure_text == text else "DIFFERENT BYTES",
                    )
                ),
                table_row(
                    (
                        "load",
                        "yaml.safe_load",
                        f"{load_pure:.2f}",
                        f"{len(parsed_pure['services'])} services",
                    )
                ),
                table_row(
                    (
                        "load",
                        "Loader=CSafeLoader",
                        f"{load_c:.2f}",
                        "same object"
                        if parsed_c == parsed_pure
                        else "DIFFERENT OBJECT",
                    )
                ),
            ]
            verdict.value = (
                f"C is {load_pure / load_c:.1f}x faster reading and "
                f"{emit_pure / emit_c:.1f}x faster writing {emitted:,} B"
                + ("" if parsed_pure == document else " — round trip LOST data")
            )
        except Exception as error:
            summary.value = ""
            results.controls = []
            verdict.value = f"{type(error).__name__}: {error}"

        size.disabled = False
        parse.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def check():
        """Parse whatever is in the editor with each loader and compare verdicts.

        The seeded document has a tab where a space belongs, which the two
        loaders genuinely disagree about — so out of the box this shows one
        rejecting a file the other accepts.
        """
        text = editor.value
        diagnosis.controls = [
            table_row(("loader", "outcome", "where", "caret")),
            ft.Divider(height=1),
            *(
                table_row((name, *parse_report(text, loader)))
                for name, loader in (
                    ("SafeLoader", yaml.SafeLoader),
                    ("CSafeLoader", CSafeLoader),
                )
            ),
        ]

    page.appbar = ft.AppBar(title=ft.Text("PyYAML settings file"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(build_line(page), size=11),
                    ft.Row(
                        controls=[
                            caption := ft.Text(expand=True),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    size := ft.Slider(
                        min=25,
                        max=400,
                        value=100,
                        divisions=15,
                        round=0,
                        label="{value}",
                        on_change=show_count,
                        on_change_end=start,
                    ),
                    summary := ft.Text(),
                    results := ft.Column(spacing=4),
                    verdict := ft.Text(size=11),
                    ft.Divider(),
                    editor := ft.TextField(
                        value=SNIPPET,
                        multiline=True,
                        min_lines=5,
                        max_lines=8,
                        text_size=12,
                        label="edit this and parse it again",
                    ),
                    parse := ft.Button("Parse with both loaders", on_click=check),
                    diagnosis := ft.Column(spacing=4),
                ],
            ),
        )
    )

    show_count()
    check()
    start()


if __name__ == "__main__":
    ft.run(main)
