import flet as ft
import weights


def main(page: ft.Page):
    """One screen that writes a weights file into app storage, then reads it three ways.

    Every stage prints elapsed time and peak resident memory beside its result, and
    every value read back is checked against a fingerprint taken from the arrays
    *before* they were written.
    """

    def work(body, *controls):
        """Run `body` in the thread pool with `controls` disabled and the spinner up."""

        def run():
            """The worker, plus the update a background thread has to issue itself.

            page.run_thread never retrieves the worker's future, so anything the body
            raised would otherwise vanish without a trace; catching it puts it on screen.
            """
            try:
                body()
            except Exception as error:
                status.value = f"{type(error).__name__}: {error}"
            finally:
                for control in controls:
                    control.disabled = False
                spinner.visible = False
                page.update()

        status.value = ""
        for control in controls:
            control.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(run)

    def prepare():
        """Write the file, then read back its header and nothing else."""
        wrote = weights.write_file()
        built.value = (
            f"1 · wrote {wrote['size'] / 1e6:.1f} MB to {weights.MODEL_NAME}, "
            f"peak {wrote['peak']:.0f} MB"
        )
        head = weights.read_header()
        header.value = (
            f"2 · header only: {len(head['tensors'])} tensors declaring "
            f"{head['declared'] / 1e6:.1f} MB of tensor data, metadata={head['meta']} — "
            f"{head['opened']:.3f} ms via safe_open, {head['plain']:.3f} ms with "
            f"struct+json alone, peak {head['peak']:.0f} MB"
        )
        table.value = "\n".join(
            f"{name}  {shape}  {dtype}  {nbytes / 1e3:.0f} KB"
            for name, shape, dtype, nbytes in head["tensors"]
        )

    def slice_one():
        """Read row 0 of whichever block the slider is pointing at."""
        got = weights.read_row(int(slider.value))
        verdict = "matches" if got["matches"] else "DOES NOT MATCH"
        sliced.value = (
            f"3 · {got['name']} row 0: {got['bytes'] / 1e3:.1f} KB out of a "
            f"{got['whole'] / 1e6:.1f} MB tensor, first value {got['first']:+.6f} — "
            f"{verdict} what was written, {got['ms']:.3f} ms, peak {got['peak']:.0f} MB"
        )

    def load_all():
        """Read every tensor at once, which is the reading this example argues against."""
        got = weights.read_all()
        loaded_line.value = (
            f"4 · load_file: {got['matched']}/{got['total']} tensors match what was "
            f"written, {got['ms']:.0f} ms, peak {got['peak']:.0f} MB"
        )

    def damage():
        """Damage a small copy two ways and show that only one of them is detectable."""
        got = weights.damage_probe()
        damaged.value = (
            f"5 · truncated copy: {got['truncated']}\n"
            f"     bit-flipped copy: opened cleanly, probe[0, 0] = "
            f"{got['read_back']:g} where {got['written']:g} was written — "
            f"digest match {got['digest_match']}"
        )

    page.appbar = ft.AppBar(title=ft.Text("safetensors lazy weights"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(f"{weights.VERSION} · {page.platform.value}", size=11),
                    built := ft.Text("1 · building…"),
                    header := ft.Text("2 · waiting for the file"),
                    table := ft.Text("", size=11, font_family="monospace"),
                    ft.Row(
                        controls=[
                            ft.Text("block"),
                            slider := ft.Slider(
                                min=0,
                                max=weights.BLOCKS - 1,
                                divisions=weights.BLOCKS - 1,
                                label="{value}",
                                expand=True,
                                # on_change_end, so one gesture is one read rather
                                # than one read per pixel the thumb travels.
                                on_change_end=lambda: work(slice_one, slider),
                            ),
                            spinner := ft.ProgressRing(
                                width=16, height=16, visible=False
                            ),
                        ]
                    ),
                    sliced := ft.Text("3 · drag the slider to read one row"),
                    loaded_line := ft.Text("4 · not loaded yet"),
                    damaged := ft.Text("5 · not damaged yet"),
                    ft.Row(
                        # Both labels on one line measure 353 dp; a 360 dp-wide phone
                        # (the whole Galaxy S/A range) leaves 340 after page padding.
                        wrap=True,
                        controls=[
                            load_button := ft.Button(
                                "Load every tensor",
                                icon=ft.Icons.DOWNLOAD_FOR_OFFLINE,
                                on_click=lambda: work(load_all, load_button),
                            ),
                            damage_button := ft.Button(
                                "Damage a copy",
                                icon=ft.Icons.BROKEN_IMAGE,
                                on_click=lambda: work(damage, damage_button),
                            ),
                        ],
                    ),
                    status := ft.Text("", color=ft.Colors.ERROR),
                ],
            ),
        )
    )

    work(prepare, slider, load_button, damage_button)


if __name__ == "__main__":
    ft.run(main)
