import flet as ft
from lookup import PUBLIC_NAMESERVERS, RECORD_TYPES, lookup, system_nameservers


async def main(page: ft.Page):
    discovered = system_nameservers()
    # c-ares cannot read Android's resolver config, so it falls back to loopback.
    system_works = not all(s.startswith("127.") for s in discovered)

    async def resolve(_):
        """Run one query and refill the answer list."""
        answers.controls.clear()
        spinner.visible = True
        page.update()

        servers = None if source.value == "system" else PUBLIC_NAMESERVERS
        try:
            lines = await lookup(host.value.strip(), qtype.value, servers)
            answers.controls.extend(
                ft.Text(line, size=12, font_family="monospace")
                for line in lines or ["no answer records"]
            )
        except Exception as e:
            answers.controls.append(
                ft.Text(f"{type(e).__name__}: {e}", color=ft.Colors.ERROR)
            )
        spinner.visible = False
        page.update()

    page.appbar = ft.AppBar(title="DNS lookup", center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            host := ft.TextField(
                                label="Host", value="pypi.flet.dev", expand=True
                            ),
                            qtype := ft.Dropdown(
                                value="A",
                                width=110,
                                options=[
                                    ft.DropdownOption(key=t) for t in RECORD_TYPES
                                ],
                            ),
                        ]
                    ),
                    source := ft.RadioGroup(
                        value="system" if system_works else "public",
                        content=ft.Row(
                            controls=[
                                ft.Radio(value="system", label="System DNS"),
                                ft.Radio(
                                    value="public", label=", ".join(PUBLIC_NAMESERVERS)
                                ),
                            ],
                        ),
                    ),
                    ft.Row(
                        controls=[
                            ft.Button("Look up", on_click=resolve),
                            spinner := ft.ProgressRing(
                                visible=False, width=18, height=18
                            ),
                        ]
                    ),
                    ft.Divider(),
                    answers := ft.ListView(expand=True, spacing=6),
                    ft.Text(
                        "c-ares found: " + ", ".join(discovered),
                        size=11,
                        color=None if system_works else ft.Colors.ERROR,
                    ),
                ],
            ),
        )
    )


ft.run(main)
