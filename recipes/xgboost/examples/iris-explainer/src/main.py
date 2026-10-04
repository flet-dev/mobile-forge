import flet as ft
from classifier import FEATURES, SPECIES, describe, load, predict


def main(page: ft.Page):
    model = None

    def start():
        """Load the bundled model on a worker thread, then show the first prediction.

        run_thread only logs a worker's exception, never showing it in the UI, and
        does not carry an automatic update, so this catches its own failures and
        ends with page.update().
        """
        nonlocal model
        try:
            model = load()
            header.value = describe(model)
            show()
        except Exception as exc:
            header.value = (
                f"Could not load or run the model: {type(exc).__name__}: {exc}"
            )
        page.update()

    def show(_=None):
        """Predict for the slider values and redraw the verdict, odds and reasons."""
        if model is None:
            return
        result = predict(model, [slider.value for slider in sliders])
        verdict.value = f"{result.species} · {max(result.probabilities):.0%}"
        for bar, label, p in zip(bars, odds, result.probabilities):
            bar.value = p
            label.value = f"{p:.0%}"
        for bar, label, c in zip(pushes, scores, result.contributions):
            bar.width = min(abs(c), 4) * 30
            bar.bgcolor = ft.Colors.GREEN if c >= 0 else ft.Colors.RED
            label.value = f"{c:+.2f}"
        why.value = f"Why {result.species}: how each measurement moved its score"
        timing.value = f"predicted and explained in {result.elapsed_ms:.1f} ms"
        page.update()

    sliders = [
        ft.Slider(
            min=low,
            max=high,
            value=start,
            divisions=round((high - low) * 10),
            round=1,
            label="{value} cm",
            on_change=show,
        )
        for _, low, high, start in FEATURES
    ]
    bars = [ft.ProgressBar(value=0, expand=True) for _ in SPECIES]
    odds = [ft.Text("", width=44) for _ in SPECIES]
    pushes = [ft.Container(height=12, width=0) for _ in FEATURES]
    scores = [ft.Text("", width=52) for _ in FEATURES]

    page.appbar = ft.AppBar(title="Iris explainer", center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    header := ft.Text("Loading iris_xgb.joblib…", size=12),
                    *(
                        ft.Column(spacing=0, controls=[ft.Text(f"{name} (cm)"), slider])
                        for (name, *_), slider in zip(FEATURES, sliders)
                    ),
                    verdict := ft.Text("", size=24, weight=ft.FontWeight.BOLD),
                    *(
                        ft.Row(controls=[ft.Text(name, width=90), bar, label])
                        for name, bar, label in zip(SPECIES, bars, odds)
                    ),
                    why := ft.Text("", size=12),
                    *(
                        ft.Row(controls=[ft.Text(name, width=90), label, bar])
                        for (name, *_), bar, label in zip(FEATURES, pushes, scores)
                    ),
                    timing := ft.Text("", size=12),
                ],
            ),
        )
    )
    page.run_thread(start)


ft.run(main)
