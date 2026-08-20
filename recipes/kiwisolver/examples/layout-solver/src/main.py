import flet as ft
from kiwisolver import UnsatisfiableConstraint
from layout import (
    BENCH_COLUMNS,
    MARGIN,
    RULES,
    VERSION,
    benchmark,
    current,
    resize,
    toggle,
)

BAND = 116
TINTS = (
    (ft.Colors.PRIMARY_CONTAINER, ft.Colors.ON_PRIMARY_CONTAINER),
    (ft.Colors.SECONDARY_CONTAINER, ft.Colors.ON_SECONDARY_CONTAINER),
    (ft.Colors.TERTIARY_CONTAINER, ft.Colors.ON_TERTIARY_CONTAINER),
)


def box(name, left, width, tint):
    """One solved column, drawn at the coordinates the solver just produced."""
    fill, ink = tint
    return ft.Container(
        left=left,
        top=MARGIN,
        width=width,
        height=BAND - 2 * MARGIN,
        bgcolor=fill,
        border_radius=6,
        alignment=ft.Alignment.CENTER,
        content=ft.Text(
            f"{name}\n{width:.0f}", size=10, color=ink, text_align=ft.TextAlign.CENTER
        ),
    )


def main(page: ft.Page):
    """Wire the drawing, the width slider and the rule switches to one live solver."""

    def show(solution):
        """Move the drawing onto the geometry the solver just produced."""
        frame.width = solution.width
        stack.controls = [
            box(name, left, width, TINTS[index])
            for index, (name, left, width) in enumerate(solution.boxes)
        ]
        yielded = solution.yielded
        caption.value = (
            f"asked {solution.asked:.0f} · solved {solution.width:.0f} · "
            f"{yielded} equal-width preference{'' if yielded == 1 else 's'} "
            f"yielded · re-solved in {solution.micros:.0f} µs"
        )

    def on_width(e):
        """Slider release: swap the strong width preference and re-solve."""
        show(resize(e.control.value))
        page.update()

    def on_rule(e):
        """Add or drop one rule; a refused rule puts its own switch back off.

        layout.toggle rebuilds the solver when a rule is refused, and a rebuild
        can settle on a different -- equally optimal -- assignment than the one
        already drawn, so the boxes are refreshed from the rebuilt solver
        instead of being left alone.
        """
        try:
            show(toggle(e.control.data, e.control.value))
            note.value = ""
        except UnsatisfiableConstraint as refusal:
            e.control.value = False
            note.value = f"UnsatisfiableConstraint: {refusal.constraint}"
            show(current())
        page.update()

    def on_bench(e):
        """Lock the button and hand the benchmark to a background thread."""
        run.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(measure)

    def measure():
        """Report a from-scratch build against one incremental edit, on device."""
        constraints, build_ms, edit_ms = benchmark()
        bench.value = (
            f"{BENCH_COLUMNS} columns, {constraints} constraints: built in "
            f"{build_ms:.0f} ms, one edit re-solved in {edit_ms:.1f} ms"
        )
        run.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Layout solver"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=11),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            frame := ft.Container(
                                height=BAND,
                                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                                border_radius=8,
                                content=(stack := ft.Stack()),
                            )
                        ],
                    ),
                    caption := ft.Text(size=11),
                    ft.Text("Frame width", size=12),
                    asked := ft.Slider(
                        min=160,
                        max=280,
                        value=280,
                        divisions=6,
                        round=0,
                        label="{value}",
                        # on_change would re-solve for every pixel the thumb
                        # travels; on_change_end re-solves once, on release.
                        on_change_end=on_width,
                    ),
                    *(
                        ft.Switch(label=label, data=rule, on_change=on_rule)
                        for rule, (label, _) in RULES.items()
                    ),
                    note := ft.Text(size=11, color=ft.Colors.ERROR),
                    ft.Row(
                        controls=[
                            run := ft.Button(
                                f"Solve {BENCH_COLUMNS} columns",
                                icon=ft.Icons.SPEED,
                                on_click=on_bench,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    bench := ft.Text(size=11),
                ],
            ),
        )
    )

    show(resize(asked.value))


if __name__ == "__main__":
    ft.run(main)
