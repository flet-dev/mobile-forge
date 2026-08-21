import flet as ft
from calibrate import (
    BUDGET_MS,
    DEVICE,
    MEMORY_STEPS,
    SAMPLE,
    hash_password,
    parameters,
    sweep,
    verify_password,
)


def row(label, value):
    """One line of the results table: a label on the left, a figure on the right."""
    return ft.Row(controls=[ft.Text(label, expand=3), ft.Text(value, expand=2)])


def choices(values, selected):
    """A row of exclusive choices, pre-selected. `selected` is a list, not a set."""
    return ft.SegmentedButton(
        segments=[ft.Segment(value=str(v), label=ft.Text(str(v))) for v in values],
        selected=[str(selected)],
        show_selected_icon=False,
    )


def main(page: ft.Page):
    """Two jobs over the same three cost parameters: one hash, and a memory sweep.

    Both run on a worker thread and land through finish(), which is the only
    place the controls are released and page.update() is called.
    """

    def settings():
        """Read the three cost parameters off the controls."""
        return int(passes.value), int(memory.selected[0]), int(lanes.selected[0])

    def start(job):
        """Lock the buttons, raise the spinner and hand `job` to a worker thread."""
        for control in (measure_button, sweep_button):
            control.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(guard, job)

    def guard(job):
        """Publish a failure as a row; run_thread would swallow it and hang the UI."""
        try:
            job()
        except Exception as exc:
            finish([row("failed", str(exc))])

    def finish(controls):
        """Publish a finished table and release the controls."""
        results.controls = controls
        for control in (measure_button, sweep_button):
            control.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    def measure():
        """Hash once, verify twice, and report all three timings together."""
        t_cost, mib, parallelism = settings()
        encoded, hash_ms = hash_password(SAMPLE, t_cost, mib, parallelism)
        right, right_ms = verify_password(encoded, SAMPLE)
        wrong, wrong_ms = verify_password(encoded, "hunter2")
        verdict = {True: "accepted", False: "rejected"}
        finish(
            [
                row("hash", f"{hash_ms:.0f} ms"),
                row("verify, right password", f"{right_ms:.0f} ms · {verdict[right]}"),
                row("verify, wrong password", f"{wrong_ms:.0f} ms · {verdict[wrong]}"),
                ft.Divider(height=1),
                row("parameters stored in the hash", parameters(encoded)),
                row("memory held while hashing", f"{mib} MiB"),
            ]
        )

    def run_sweep():
        """Time every memory step and name the strongest one inside the budget."""
        t_cost, _, parallelism = settings()
        rows, chosen = sweep(t_cost, parallelism)
        finish(
            [
                row("memory", "hash"),
                ft.Divider(height=1),
                *(row(f"{mib} MiB", f"{elapsed:.0f} ms") for mib, elapsed in rows),
                ft.Divider(height=1),
                row(
                    f"fits {BUDGET_MS} ms at t={t_cost}, p={parallelism}",
                    f"{chosen} MiB" if chosen else "nothing",
                ),
            ]
        )

    page.appbar = ft.AppBar(title=ft.Text("Argon2 cost"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(DEVICE, size=11),
                    ft.Text("memory_cost, in MiB", size=12),
                    memory := choices(MEMORY_STEPS, 64),
                    ft.Text("parallelism, in lanes", size=12),
                    lanes := choices((1, 2, 4), 1),
                    passes := ft.Slider(
                        min=1,
                        max=5,
                        value=3,
                        divisions=4,
                        round=0,
                        label="time_cost {value}",
                    ),
                    ft.Row(
                        wrap=True,
                        controls=[
                            measure_button := ft.Button(
                                "Measure",
                                icon=ft.Icons.TIMER_OUTLINED,
                                on_click=lambda: start(measure),
                            ),
                            sweep_button := ft.Button(
                                "Sweep memory",
                                icon=ft.Icons.STACKED_LINE_CHART,
                                on_click=lambda: start(run_sweep),
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ],
                    ),
                    results := ft.Column(spacing=4),
                ],
            ),
        )
    )

    start(measure)


if __name__ == "__main__":
    ft.run(main)
