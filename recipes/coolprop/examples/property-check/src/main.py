"""Fluid properties from CoolProp, cross-checked on device against published references."""

import sys
import time

import flet as ft

# A row agrees when its relative error is at or under this. Every row below sits at
# 3e-5 or better on desktop CoolProp 7.2.0, so this leaves better than 3x headroom.
TOLERANCE = 1e-4
SWEEP_POINTS = 200
FLUIDS = ["Water", "R134a", "Ammonia"]

# (label, unit, published value, source, call). The calls take the CoolProp.CoolProp
# module as an argument because CoolProp is imported off the UI thread — see load().
REFERENCES = [
    (
        "Water triple-point temperature",
        "K",
        273.16,
        "ITS-90",
        lambda cp: cp.PropsSI("Ttriple", "Water"),
    ),
    (
        "Water critical temperature",
        "K",
        647.096,
        "IAPWS-95",
        lambda cp: cp.PropsSI("Tcrit", "Water"),
    ),
    (
        "Water critical pressure",
        "Pa",
        22.064e6,
        "IAPWS-95",
        lambda cp: cp.PropsSI("pcrit", "Water"),
    ),
    (
        "Water boiling point at 101325 Pa",
        "K",
        373.1243,
        "IAPWS-95",
        lambda cp: cp.PropsSI("T", "P", 101325, "Q", 0, "Water"),
    ),
    (
        "Water density at 25 °C and 101325 Pa",
        "kg/m³",
        997.047,
        "IAPWS-95",
        lambda cp: cp.PropsSI("D", "T", 298.15, "P", 101325, "Water"),
    ),
    (
        "Nitrogen normal boiling point",
        "K",
        77.355,
        "NIST",
        lambda cp: cp.PropsSI("T", "P", 101325, "Q", 0, "Nitrogen"),
    ),
    (
        "R134a saturation pressure at 25 °C",
        "Pa",
        665400.0,
        "NIST",
        lambda cp: cp.PropsSI("P", "T", 298.15, "Q", 0, "R134a"),
    ),
    (
        "CO₂ triple-point pressure",
        "Pa",
        517950.0,
        "NIST",
        lambda cp: cp.PropsSI("ptriple", "CO2"),
    ),
    (
        "Saturation humidity ratio, moist air at 25 °C and 101325 Pa",
        "kg/kg",
        0.020173,
        "ASHRAE Fundamentals",
        lambda cp: cp.HAPropsSI("W", "T", 298.15, "P", 101325, "R", 1.0),
    ),
]

# Three requests CoolProp should refuse. Two of them it does; the third is the point.
PROBES = [
    (
        "HAPropsSI at 100 K, below the humid-air model's floor",
        lambda cp: cp.HAPropsSI("W", "T", 100, "P", 101325, "R", 0.5),
    ),
    (
        "Saturation pressure of water at 700 K, above its critical point",
        lambda cp: cp.PropsSI("P", "T", 700, "Q", 0, "Water"),
    ),
    (
        "Density of water at 100000 K, fifty times its own declared T_max",
        lambda cp: cp.PropsSI("D", "T", 100000, "P", 101325, "Water"),
    ),
]


def rss_mib():
    """Peak resident set size in MiB, or None where the `resource` module is unavailable.

    `ru_maxrss` is a high-water mark, not the current footprint, so the pair either side
    of the import bounds what the import cost rather than measuring it exactly. It is
    also bytes on Darwin and iOS but kibibytes on Linux and Android, so the raw number
    means nothing until the platform is known.
    """
    try:
        import resource
    except ImportError:
        return None
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / 2**20 if sys.platform in ("darwin", "ios") else raw / 2**10


def main(page: ft.Page):
    """One screen: a cross-check table, a saturation sweep, and three out-of-range requests.

    Nothing is computed before the first frame. `import CoolProp` parses the whole fluid
    database its extension carries, which is the app's single largest cost, so it happens
    in the thread pool with a spinner on screen and its price printed in the footer.
    """
    cp = None  # CoolProp.CoolProp, bound by load() once the import has finished

    def problem(exc):
        """The one way this app reports a failure: the exception class and its message."""
        return ft.Text(f"{type(exc).__name__}: {exc}", color=ft.Colors.ERROR, size=11)

    def render(column, build):
        """Replace `column`'s children with `build()`'s, showing any exception in their place.

        An unhandled exception in a Flet handler ends the session with a crash screen,
        which would hide exactly the failure this app exists to show.
        """
        try:
            column.controls = build()
        except Exception as exc:
            column.controls = [problem(exc)]

    def check_row(label, unit, reference, source, call):
        """One cross-check line: computed value, published value, relative error, verdict.

        Catches its own failure so that one fluid missing on one platform costs one row
        rather than replacing the whole table with a single message.
        """
        try:
            got = call(cp)
            error = abs(got - reference) / abs(reference)
            passed = error <= TOLERANCE
            detail = f"{got:.7g} vs {reference:.7g} {unit} ({source}) — rel {error:.1e}"
        except Exception as exc:
            passed = False
            detail = f"{type(exc).__name__}: {exc}"
        return ft.Column(
            spacing=0,
            controls=[
                ft.Row(
                    spacing=6,
                    controls=[
                        ft.Icon(
                            ft.Icons.CHECK_CIRCLE if passed else ft.Icons.CANCEL,
                            color=ft.Colors.GREEN if passed else ft.Colors.ERROR,
                            size=16,
                        ),
                        ft.Text(label, size=13, expand=True),
                    ],
                ),
                ft.Text(
                    detail,
                    size=11,
                    color=ft.Colors.ON_SURFACE_VARIANT if passed else ft.Colors.ERROR,
                ),
            ],
        )

    def probe_row(label, call):
        """One out-of-range request, reporting whether CoolProp refused it or answered anyway.

        Anything other than the expected `ValueError` is itself worth seeing, and is
        caught here so that it costs this row rather than the other two.
        """
        try:
            answer = f"returned {call(cp):.6g} — no exception"
            colour = ft.Colors.ERROR
        except ValueError as exc:
            answer = f"ValueError: {exc}"
            colour = ft.Colors.GREEN
        except Exception as exc:
            answer = f"{type(exc).__name__}: {exc}"
            colour = ft.Colors.ERROR
        return ft.Column(
            spacing=0,
            controls=[
                ft.Text(label, size=13),
                ft.Text(answer, size=11, color=colour),
            ],
        )

    def check_rows():
        """The whole reference table."""
        return [check_row(*row) for row in REFERENCES]

    def probe_rows():
        """The three probes, under the limits CoolProp itself reports for water."""
        return [
            ft.Text(
                f"CoolProp reports T_max = {cp.PropsSI('Tmax', 'Water'):.0f} K and "
                f"p_max = {cp.PropsSI('pmax', 'Water'):.3g} Pa for water.",
                size=12,
            )
        ] + [probe_row(*probe) for probe in PROBES]

    def dome_rows():
        """Saturation properties at the slider's temperature, timed both ways CoolProp offers.

        `PropsSI` rebuilds its backend on every call, so the same sweep through a reused
        `AbstractState` is far cheaper. How far is the one number a CoolProp app should
        budget against, and only the device can supply it.
        """
        fluid = fluids.selected[0]
        t_min = cp.PropsSI("Ttriple", fluid)
        t_max = cp.PropsSI("Tcrit", fluid)
        temperature = t_min + (t_max - t_min) * position.value / 100

        pressure = cp.PropsSI("P", "T", temperature, "Q", 0, fluid)
        liquid = cp.PropsSI("D", "T", temperature, "Q", 0, fluid)
        vapour = cp.PropsSI("D", "T", temperature, "Q", 1, fluid)
        latent = cp.PropsSI("H", "T", temperature, "Q", 1, fluid) - cp.PropsSI(
            "H", "T", temperature, "Q", 0, fluid
        )

        points = [
            t_min + (t_max - t_min) * (i + 0.5) / SWEEP_POINTS
            for i in range(SWEEP_POINTS)
        ]
        start = time.perf_counter()
        for point in points:
            cp.PropsSI("P", "T", point, "Q", 0, fluid)
        per_call = (time.perf_counter() - start) / SWEEP_POINTS * 1e6

        state = cp.AbstractState("HEOS", fluid)
        start = time.perf_counter()
        for point in points:
            state.update(cp.QT_INPUTS, 0, point)
            state.p()
        per_update = (time.perf_counter() - start) / SWEEP_POINTS * 1e6

        return [
            ft.Text(
                f"{fluid} saturated at {temperature:.2f} K ({temperature - 273.15:.2f} °C)",
                size=13,
            ),
            ft.Text(
                f"p = {pressure / 1000:.4g} kPa · ρ_liq = {liquid:.5g} kg/m³ · "
                f"ρ_vap = {vapour:.5g} kg/m³ · h_fg = {latent / 1000:.5g} kJ/kg",
                size=11,
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.Text(
                f"{SWEEP_POINTS} points up the dome: PropsSI {per_call:.1f} µs/call, "
                f"one reused AbstractState {per_update:.2f} µs/call ({per_call / per_update:.0f}x)",
                size=11,
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
        ]

    def footer_rows(coolprop, import_ms, before, after):
        """What only a device can report: the cost of the import and the size of the databases."""
        cost = f"import CoolProp: {import_ms:.0f} ms"
        if before is not None and after is not None:
            cost += f", peak RSS {before:.0f} → {after:.0f} MiB"
        return [
            ft.Text(cost, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(
                f"CoolProp {coolprop.__version__} on {page.platform.value}, "
                f"Python {sys.version.split()[0]} — {len(coolprop.__fluids__)} fluids, "
                f"{len(coolprop.__incompressibles_pure__)} pure incompressibles, "
                f"{len(coolprop.__incompressibles_solution__)} solutions",
                size=11,
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
        ]

    def refresh():
        """Redraw the sweep. Runs in the thread pool: several hundred short CoolProp calls."""
        render(dome, dome_rows)
        page.update()  # auto-update does not reach background threads

    def on_input_change():
        """Send the sweep off the UI thread whenever the fluid or the temperature changes."""
        page.run_thread(refresh)

    def load():
        """Import CoolProp in the thread pool, then fill every section.

        CoolProp's package `__init__` asks the extension for the full fluid list, which
        forces the embedded database to be decompressed and parsed — hundreds of
        milliseconds and a large allocation that would otherwise delay the first frame.
        """
        nonlocal cp
        before = rss_mib()
        started = time.perf_counter()
        try:
            import CoolProp
            import CoolProp.CoolProp
        except Exception as exc:
            # page.run_thread retrieves no future, so an import that fails on device
            # would otherwise leave the spinner turning with nothing to say why.
            checks.controls = [problem(exc)]
            page.update()
            return

        import_ms = (time.perf_counter() - started) * 1000
        after = rss_mib()
        cp = CoolProp.CoolProp

        render(checks, check_rows)
        render(dome, dome_rows)
        render(probes, probe_rows)
        render(footer, lambda: footer_rows(CoolProp, import_ms, before, after))
        fluids.disabled = position.disabled = False
        page.update()

    def heading(text):
        """A section title."""
        return ft.Text(text, size=14, weight=ft.FontWeight.BOLD)

    page.appbar = ft.AppBar(title=ft.Text("CoolProp property check"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                controls=[
                    heading("Against published values"),
                    checks := ft.Column(spacing=10, controls=[ft.ProgressRing()]),
                    ft.Divider(),
                    heading("Saturation line"),
                    fluids := ft.SegmentedButton(
                        segments=[
                            ft.Segment(value=name, label=ft.Text(name))
                            for name in FLUIDS
                        ],
                        selected=[FLUIDS[0]],
                        disabled=True,
                        on_change=on_input_change,
                    ),
                    position := ft.Slider(
                        min=2,
                        max=98,
                        value=50,
                        divisions=48,
                        label="{value}% up the dome",
                        disabled=True,
                        on_change_end=on_input_change,
                    ),
                    dome := ft.Column(spacing=2),
                    ft.Divider(),
                    heading("Requests CoolProp should refuse"),
                    probes := ft.Column(spacing=10),
                    ft.Divider(),
                    footer := ft.Column(spacing=2),
                ],
            ),
        )
    )

    page.run_thread(load)


if __name__ == "__main__":
    ft.run(main)
