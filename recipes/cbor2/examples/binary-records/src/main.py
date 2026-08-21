import flet as ft
from records import VERSION, benchmark, custom_roundtrip, tag_table

# "monospace" is a generic family name that Android maps and iOS does not, and the
# hex columns only line up in a real fixed-width face; Courier backs it up there.
MONO = {"font_family": "monospace", "font_family_fallback": ["Courier"]}


def cells(first, *rest):
    """One table line: a wide first column, then a narrow one per value."""
    return ft.Row(
        controls=[first, *(ft.Text(value, size=11, expand=3) for value in rest)],
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def label(text):
    """The first cell of a table line."""
    return ft.Text(text, size=11, expand=4)


def heading(text):
    """The title of one of the three panels."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def kb(count):
    """Bytes as decimal kilobytes, which is how a payload budget is quoted."""
    return f"{count / 1000:.1f} KB"


def sample_row(entry):
    """A sample value, the bytes it encoded to, and what each format decoded back."""
    stacked = ft.Column(
        spacing=1,
        expand=4,
        controls=[
            ft.Text(entry["label"], size=11),
            ft.Text(entry["hex"], size=9, color=ft.Colors.OUTLINE, **MONO),
        ],
    )
    return cells(stacked, entry["tag"], entry["cbor"], entry["json"])


def main(page: ft.Page):
    """Three panels: the tags CBOR knows, a type it does not, and the benchmark.

    The first two are computed once at startup — encoding a handful of values
    costs nothing — and only the journal is re-encoded when the slider moves.
    """
    custom = custom_roundtrip()

    def measure():
        """Lock the controls and hand the encode/decode timings to a thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compare)

    def compare():
        """Encode the journal both ways and fill in the size and time table.

        The decode line is the one to read twice. json.loads alone is quicker
        than cbor2, and it has not finished the job: the timestamps, decimals,
        UUIDs and digests are still strings. The bracketed figure adds the code
        that turns them back into objects, which is what cbor2 did on the way.
        """
        result = benchmark(int(count.value))
        decode = f"{result['json_decode']:.1f} ms ({result['json_typed']:.1f} typed)"
        rows = (
            ("bytes", kb(result["cbor_bytes"]), kb(result["json_bytes"])),
            (
                "encode",
                f"{result['cbor_encode']:.1f} ms",
                f"{result['json_encode']:.1f} ms",
            ),
            ("decode", f"{result['cbor_decode']:.1f} ms", decode),
            (
                "equals the original",
                str(result["cbor_identical"]),
                f"{result['json_identical']}, rehydrated",
            ),
        )
        report.controls = [
            cells(label(""), "cbor2", "json"),
            ft.Divider(height=1),
            *(cells(label(name), ours, theirs) for name, ours, theirs in rows),
            ft.Divider(height=1),
            ft.Text(
                f"json is {result['json_bytes'] / result['cbor_bytes']:.2f}x the size"
                " · string_referencing takes another "
                f"{1 - result['packed_bytes'] / result['cbor_bytes']:.0%} off",
                size=11,
                color=ft.Colors.PRIMARY,
            ),
        ]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Binary records"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(VERSION, size=11, color=ft.Colors.OUTLINE),
                    heading("Tags the format already knows"),
                    cells(label("value"), "tag", "cbor2", "json"),
                    ft.Divider(height=1),
                    *(sample_row(entry) for entry in tag_table()),
                    ft.Divider(height=20),
                    heading("A type it does not"),
                    ft.Text(custom["hex"], size=9, **MONO),
                    ft.Text(f"no tag_hook: {custom['plain']}", size=11),
                    ft.Text(f"with tag_hook: {custom['back']}", size=11),
                    ft.Text(
                        f"same object as the one encoded: {custom['same']}",
                        size=11,
                        color=ft.Colors.PRIMARY,
                    ),
                    ft.Divider(height=20),
                    heading("The same journal, both formats"),
                    count := ft.Slider(
                        min=50,
                        max=2000,
                        value=500,
                        divisions=13,
                        round=0,
                        label="{value} records",
                        # on_change would re-run the benchmark for every pixel
                        # the thumb travels; on_change_end runs it once.
                        on_change_end=measure,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Measure", icon=ft.Icons.SPEED, on_click=measure
                            ),
                            spinner := ft.ProgressRing(
                                width=20, height=20, visible=False
                            ),
                        ]
                    ),
                    report := ft.Column(spacing=4),
                ],
            ),
        )
    )

    measure()


if __name__ == "__main__":
    ft.run(main)
