import time

import flet as ft
from bus import CHUNK, JOB_COUNT, VERSION, control, job_queue, results, submit, worker

NAMES = "ABCD"


def line(label, *cells):
    """One row of the worker table: a name, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=2), *(ft.Text(c, expand=3) for c in cells)]
    )


def main(page: ft.Page):
    """Own the two sockets the UI sends on, and keep one collector thread running.

    `job_queue()` and `control()` are called here, on the thread Flet runs this
    function and its handlers on, and what they return is never touched from
    anywhere else.
    """
    queue = job_queue()
    stopper = control()
    state = {"started": 0.0, "sent": 0, "back": 0, "workers": 0}
    tally = {}

    def draw():
        """Repaint the summary line and the per-worker table."""
        elapsed = (time.perf_counter() - state["started"]) * 1000
        moved = state["back"] * CHUNK / 1e6
        if state["sent"]:
            summary.value = (
                f"{state['back']} / {state['sent']} jobs back · {elapsed:.0f} ms · "
                f"{moved / max(elapsed, 1) * 1000:.0f} MB/s"
            )
        elif state["workers"]:
            summary.value = f"Workers ready: {state['workers']}."
        else:
            summary.value = "Nothing is listening — slide up to start a worker."
        table.controls = [
            line("", "jobs", "busy"),
            ft.Divider(height=1),
            *(
                line(f"worker {name}", jobs, f"{busy:.0f} ms")
                for name, (jobs, busy) in sorted(tally.items())
            ),
        ]
        page.update()  # auto-update does not reach background threads

    def collect():
        """Put finished jobs on screen; runs for the life of the app.

        The generator blocks in `recv()` between jobs, so this thread costs a
        slot in the page executor and no CPU. It is started once and never
        restarted, for the reason `results()` gives.
        """
        try:
            for job in results():
                jobs, busy = tally.get(job["worker"], (0, 0.0))
                tally[job["worker"]] = (jobs + 1, busy + job["ms"])
                state["back"] += 1
                if state["workers"] and state["back"] >= state["sent"]:
                    run.disabled = False
                    spinner.visible = False
                draw()
        except Exception as exc:  # page.run_thread swallows what it is handed
            summary.value = repr(exc)
            page.update()

    def restart():
        """Stop whatever is running and start the number of workers now selected.

        One `send()` clears the old set however many there were, and at zero on
        the slider that is all this does. The replacements connect after the
        message has gone and never see it, because PUB keeps no history.
        """
        stopper.send(b"stop")
        state.update(workers=int(workers.value), sent=0, back=0)
        tally.clear()
        for name in NAMES[: state["workers"]]:
            page.run_thread(worker, name)
        run.disabled = not state["workers"]
        spinner.visible = False
        draw()

    def send():
        """Push a batch and let the workers race for it.

        The count comes from `submit()` rather than from `JOB_COUNT`, because a
        batch that found no worker sends nothing, and the spinner has to stay
        down when there is nothing to wait for.
        """
        tally.clear()
        state.update(started=time.perf_counter(), back=0, sent=0)
        state["sent"] = submit(queue)
        run.disabled = spinner.visible = state["sent"] > 0
        draw()

    page.appbar = ft.AppBar(title=ft.Text("inproc bus"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=11),
                    workers := ft.Slider(
                        min=0,
                        max=len(NAMES),
                        value=1,
                        divisions=len(NAMES),
                        round=0,
                        label="{value} workers",
                        # on_change would restart the workers once per step the
                        # thumb passes through; on_change_end does it once, and
                        # zero workers is how the app stops them all.
                        on_change_end=restart,
                    ),
                    ft.Row(
                        controls=[
                            run := ft.Button(
                                f"Run {JOB_COUNT} jobs",
                                icon=ft.Icons.PLAY_ARROW,
                                on_click=send,
                            ),
                            spinner := ft.ProgressRing(
                                width=18, height=18, visible=False
                            ),
                        ]
                    ),
                    summary := ft.Text(size=12),
                    table := ft.Column(spacing=4),
                ],
            ),
        )
    )

    page.run_thread(collect)
    restart()


if __name__ == "__main__":
    ft.run(main)
