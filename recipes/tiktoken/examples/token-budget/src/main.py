import flet as ft
from budget import (
    CACHE_KEY,
    DRAFT,
    ENCODING,
    MODEL,
    PROMPT_BUDGET,
    conversation,
    count_chat,
    prepare,
    ratios,
)


def row(label, *cells):
    """One line of a table: a label on the left, then a column per value."""
    return ft.Row(
        controls=[
            ft.Text(label, expand=4),
            *(ft.Text(c, expand=2, text_align=ft.TextAlign.RIGHT) for c in cells),
        ]
    )


def main(page: ft.Page):
    """Count what a chat payload costs before it is sent, using a local vocabulary."""
    encoding = None

    def count():
        """Lock the controls and hand the whole job to a background thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(work)

    def work():
        """Load the vocabulary if it is not loaded yet, then budget the payload.

        The load is the slow half and the half that can fail: a cold cache pulls
        3.6 MB over HTTPS, and with no route to the network tiktoken raises instead
        of returning a tokeniser. Catching it here is what turns that into a message
        on screen; page.run_thread would otherwise swallow the traceback whole.
        """
        nonlocal encoding
        try:
            if encoding is None:
                encoding, source, elapsed = prepare()
                status.value = f"{ENCODING} for {MODEL} — {source}, {elapsed:.0f} ms"
                status.color = None
                table.controls = [
                    row("", "chars", "tokens", "chars/token"),
                    ft.Divider(height=1),
                    *(
                        row(name, chars, tokens, f"{ratio:.2f}")
                        for name, chars, tokens, ratio in ratios(encoding)
                    ),
                ]
            messages = conversation(draft.value)
            used = count_chat(encoding, messages)
            chars = sum(len(m["content"]) for m in messages)
            meter.value = min(used / PROMPT_BUDGET, 1.0)
            meter.color = ft.Colors.ERROR if used > PROMPT_BUDGET else None
            payload.controls = [
                row("tokens in the payload", used),
                row("budget", PROMPT_BUDGET),
                row("left to spend", PROMPT_BUDGET - used),
                ft.Divider(height=1),
                row("characters", chars),
                row("a chars/4 estimate would say", chars // 4),
            ]
        except Exception as exc:
            status.value = f"{type(exc).__name__}: {exc}"
            status.color = ft.Colors.ERROR
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("Token budget"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    status := ft.Text("loading the vocabulary...", size=12),
                    ft.Text(f"cached as {CACHE_KEY}", size=10, selectable=True),
                    meter := ft.ProgressBar(value=0),
                    payload := ft.Column(spacing=4),
                    ft.Divider(),
                    draft := ft.TextField(
                        label="Next user message",
                        value=DRAFT,
                        multiline=True,
                        min_lines=3,
                        max_lines=6,
                        text_size=13,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "Count",
                                icon=ft.Icons.CALCULATE,
                                on_click=count,
                            ),
                            spinner := ft.ProgressRing(
                                width=20,
                                height=20,
                                visible=False,
                            ),
                        ]
                    ),
                    ft.Divider(),
                    ft.Text("Why characters are not a proxy", size=12),
                    table := ft.Column(spacing=4),
                ],
            ),
        )
    )

    count()


if __name__ == "__main__":
    ft.run(main)
