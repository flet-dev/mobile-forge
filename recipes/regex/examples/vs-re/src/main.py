"""Run one pattern through `re` and through `regex` and show where the stdlib stops."""

import platform
import threading

import flet as ft
from patterns import CASES, IMPORT_ERROR, compare, evaluate, measure, runtime


def verdict(index, item):
    """One comparison row: a dot, the label, the pattern, and both engines' answers."""
    dot = ft.Icon(
        ft.Icons.CIRCLE, size=9, color=ft.Colors.GREEN if item.ok else ft.Colors.RED
    )
    lines = [
        ft.Row(controls=[dot, ft.Text(f"{index}. {item.label}", size=11, expand=True)]),
        ft.Text(f"    {item.pattern}", size=10, font_family="monospace"),
        ft.Text(f"    re    {item.stdlib}", size=10),
        ft.Text(f"    regex {item.third}", size=10),
    ]
    if not item.ok:
        lines.append(ft.Text(f"    expected {item.expected}", size=10, italic=True))
    return ft.Column(spacing=1, controls=lines)


def mono(text):
    """One monospaced output line from a probe."""
    return ft.Text(text, size=10, font_family="monospace")


def field(label, value):
    """A field the user types a pattern into, with the phone keyboard's help turned off.

    Without these three settings a keyboard rewrites the pattern as it is typed —
    capitalising, substituting quotes — and the user meets an error for something
    they did not write.
    """
    return ft.TextField(
        label=label,
        value=value,
        autocorrect=False,
        enable_suggestions=False,
        capitalization=ft.TextCapitalization.NONE,
        text_size=12,
    )


def main(page: ft.Page):
    """Show the comparison table at once, and put the three timed probes behind a button.

    The table runs inline: all fifteen rows through both engines cost about 14 ms
    of CPU on a cold desktop cp312 and a tenth of that once the pattern caches are
    warm. The measurements are seconds, so they go to `page.run_thread`.
    """
    running = threading.Event()

    def benchmark():
        """Measure off the UI thread, then redraw.

        `run.disabled` is not the guard against a second tap — it only reaches the
        client a round trip later, and a tap already in flight still arrives. Two
        workers measuring thread contention at once would be measuring each other,
        so the guard is a `threading.Event` checked here.
        """
        if running.is_set():
            return
        running.set()

        def work():
            """The worker body, wrapped because `run_thread` discards what it raises."""
            try:
                numbers.controls = [mono(line) for line in measure()]
            except Exception as error:
                numbers.controls = [ft.Text(f"{type(error).__name__}: {error}", size=11)]
            finally:
                running.clear()
                run.disabled = False
                page.update()  # auto-update does not reach a background thread

        run.disabled = True
        numbers.controls = [ft.Text("measuring…", size=11)]
        page.run_thread(work)

    def play():
        """Show what each engine makes of the typed pattern."""
        stdlib, third = evaluate(query.value or "", text.value or "", version1.value)
        played.controls = [
            ft.Text(f"re    {stdlib}", size=10),
            ft.Text(f"regex {third}", size=10),
        ]

    page.appbar = ft.AppBar(title=ft.Text("regex vs re"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    header := ft.Text(size=11),
                    table := ft.Column(spacing=6),
                    ft.Divider(),
                    run := ft.Button("measure this device", icon=ft.Icons.TIMER),
                    numbers := ft.Column(spacing=1),
                    ft.Divider(),
                    ft.Text("try one yourself", size=11, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "re is compiled here, not run: it has no timeout, and the "
                        "backtracking numbers above are what one typed pattern can "
                        "cost. regex runs with timeout=1.0.",
                        size=10,
                        italic=True,
                    ),
                    query := field("pattern", r"\p{Lu}\p{Ll}+"),
                    text := field("subject", "Καλημέρα from Flet on Android and iOS"),
                    version1 := ft.Checkbox(label="prepend (?V1)", value=False),
                    ft.Button("findall", icon=ft.Icons.PLAY_ARROW, on_click=play),
                    played := ft.Column(spacing=1),
                ],
            ),
        )
    )

    if IMPORT_ERROR is not None:
        header.value = (
            f"{IMPORT_ERROR}\nregex is a compiled extension; the wheel comes from "
            "pypi.flet.dev on a device and from PyPI on a desktop."
        )
        run.disabled = True
        return

    run.on_click = benchmark
    rows = compare()
    table.controls = [verdict(index, item) for index, item in enumerate(rows, 1)]
    engine, where = runtime()
    header.value = (
        f"{engine} · {page.platform.value}/{platform.machine()} · "
        f"{sum(row.ok for row in rows)}/{len(CASES)} rows as expected\n{where}"
    )
    play()


if __name__ == "__main__":
    ft.run(main)
