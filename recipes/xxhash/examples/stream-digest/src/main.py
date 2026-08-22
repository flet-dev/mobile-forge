"""Measure xxhash against the stdlib on this device, then show what it is not.

Four panels: throughput against `crc32`, `md5` and `sha256` at three sizes; the
streaming API checked against the one-shot digest and priced against it; xxHash's
own sanity vectors recomputed here; and two attacks a cryptographic hash survives.
The work itself lives in `digests.py`; this file is the screen and its wiring.
"""

import platform

import flet as ft
from digests import AVAILABLE, BIG_SIZES, CHUNK, HEADER, measure

ROW_WEIGHTS = (4, 3, 3, 3)

MISSING = "xxhash absent - "


def table_row(cells):
    """One line of the speed table: a `Text` per cell, laid out by weight."""
    return ft.Row(
        controls=[
            ft.Text(cell, size=11, expand=weight)
            for cell, weight in zip(cells, ROW_WEIGHTS)
        ]
    )


def main(page: ft.Page):
    """Wire one picker to one background measurement and render what comes back.

    Everything on screen is computed on the device. When the wheel is missing the
    app still runs: the header turns red and names what the import raised, the
    stdlib rows are still measured, and every xxhash cell reads `-`.
    """
    shown = next(iter(BIG_SIZES))  # the big payload the table on screen describes

    def start():
        """Send one measurement to the thread pool and lock the picker while it runs.

        The guard is set here, in the synchronous handler, rather than in the worker:
        `run_thread` only schedules, so a `disabled` set inside the worker would not
        have taken effect before a second tap could start an overlapping run. A tap
        that beat that `disabled` to the client is dropped, and the picker is put back
        to the size being measured - the client moves its own highlight the instant it
        is tapped, so without the reset the button would name one payload while the
        table below described another.
        """
        nonlocal shown
        if picker.disabled:
            picker.selected = [shown]
            page.update()
            return
        shown = picker.selected[0]
        picker.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run, shown)

    def run(big_label):
        """Measure at one payload size and put every panel's text on screen.

        The size is passed in rather than read off the picker, because the worker
        starts after the handler returns and a tap landing in between moves
        `picker.selected` out from under it.

        Wrapped in try/except because `page.run_thread` discards whatever a worker
        raises - without this, a failure would look like a screen that quietly stopped
        updating. The panels are cleared on the error path, since numbers left from the
        previous run would read as though they described the error.
        """
        try:
            result = measure(big_label)
            speeds.controls = [
                table_row(["MB/s", *result["columns"]]),
                ft.Divider(height=1),
                *(
                    table_row(
                        [label, *("-" if r is None else f"{r:,.0f}" for r in rates)]
                    )
                    for label, rates in result["rows"]
                ),
            ]
            if not AVAILABLE:
                summary.value = MISSING + "only the stdlib rows above were measured"
                chunks.value = MISSING + "streaming API not exercised"
                vectors.value = MISSING + "published vectors not checked"
                collisions.value = MISSING + "nothing here to break"
                pair.value = inverted.value = ""
            else:
                fast, over_sha, over_crc = result["ratios"]
                summary.value = (
                    f"at {big_label}: xxh3_64 {fast:,.0f} MB/s is {over_sha:.1f}x "
                    f"sha256 and {over_crc:.2f}x crc32"
                )
                agrees, one_shot, streamed = result["streaming"]
                chunks.value = (
                    f"{big_label} in {CHUNK // 1024} KiB updates "
                    f"{'matches' if agrees else 'DIFFERS FROM'} the one-shot digest - "
                    f"{streamed:,.0f} MB/s streamed against {one_shot:,.0f} one-shot"
                )
                passed, total = result["vectors"]
                vectors.value = (
                    f"{passed}/{total} published xxHash v0.8.2 vectors reproduced - "
                    f"xxh64('') {result['empty'][0]}, "
                    f"xxh3_64('') {result['empty'][1]}"
                )
                collisions.value = "xxh32 collisions after " + " / ".join(
                    "gave up" if tries is None else f"{tries:,} tries in {ms:,.0f} ms"
                    for tries, ms in result["collisions"]
                )
                first, second, digest = result["pair"]
                pair.value = (
                    f"{first[:16]}... and {second[:16]}... both hash to {digest}"
                    if first
                    else ""
                )
                recovered, tried, invert_ms = result["inversion"]
                inverted.value = (
                    f"{recovered:,}/{tried:,} four-byte inputs recovered from their "
                    f"xxh32 digest alone in {invert_ms:,.0f} ms"
                )
        except Exception as error:  # the worker must never let one escape
            speeds.controls = []
            chunks.value = vectors.value = collisions.value = ""
            pair.value = inverted.value = ""
            summary.value = f"{type(error).__name__}: {error}"

        picker.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("xxhash stream digest"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        HEADER,
                        size=11,
                        color=None if AVAILABLE else ft.Colors.ERROR,
                    ),
                    ft.Text(
                        f"Python {platform.python_version()} - {page.platform.value}",
                        size=11,
                    ),
                    ft.Row(
                        controls=[
                            picker := ft.SegmentedButton(
                                expand=True,
                                segments=[
                                    ft.Segment(value=label, label=ft.Text(label))
                                    for label in BIG_SIZES
                                ],
                                # a list, not a set: a set dies in msgpack
                                selected=[next(iter(BIG_SIZES))],
                                on_change=start,
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    speeds := ft.Column(spacing=4),
                    summary := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("streaming, same bytes", size=11),
                    chunks := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("published test vectors", size=11),
                    vectors := ft.Text(size=11),
                    ft.Divider(),
                    ft.Text("what it is not", size=11),
                    collisions := ft.Text(size=11, color=ft.Colors.ERROR),
                    pair := ft.Text(size=11, color=ft.Colors.ERROR),
                    inverted := ft.Text(size=11, color=ft.Colors.ERROR),
                ],
            ),
        )
    )

    start()


if __name__ == "__main__":
    ft.run(main)
