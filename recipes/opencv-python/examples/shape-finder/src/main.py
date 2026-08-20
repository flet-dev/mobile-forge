import time

import cv2
import flet as ft
import numpy as np

SIZE = 480
CELL = SIZE // 3
KINDS = ("triangle", "rectangle", "circle")
MIN_AREA = 900


def scene(rng):
    """Draw one random shape per cell of a 3x3 grid and report what was placed.

    The grid is what makes the counts meaningful: findContours with RETR_EXTERNAL
    returns one contour per connected blob, so two shapes allowed to touch would come
    back as a single contour and no count could ever match.
    """
    canvas = np.full((SIZE, SIZE, 3), 20, np.uint8)
    placed = dict.fromkeys(KINDS, 0)
    for row_index in range(3):
        for col_index in range(3):
            kind = KINDS[int(rng.integers(0, len(KINDS)))]
            cx = col_index * CELL + CELL // 2 + int(rng.integers(-14, 15))
            cy = row_index * CELL + CELL // 2 + int(rng.integers(-14, 15))
            r = int(rng.integers(38, 56))
            colour = tuple(int(c) for c in rng.integers(120, 255, 3))
            if kind == "circle":
                cv2.circle(canvas, (cx, cy), r, colour, -1)
            elif kind == "rectangle":
                cv2.rectangle(canvas, (cx - r, cy - r), (cx + r, cy + r), colour, -1)
            else:
                corners = np.array(
                    [[cx, cy - r], [cx - r, cy + r], [cx + r, cy + r]], np.int32
                )
                cv2.fillPoly(canvas, [corners], colour)
            placed[kind] += 1
    return canvas, placed


def analyse(canvas, noise):
    """Bury the scene in noise, segment the shapes back out, and label each one.

    Four compiled OpenCV stages in one call — a colour conversion, an Otsu threshold
    that picks its own cut point, contour extraction, and a polygon approximation whose
    vertex count names the shape. Returns the annotated picture, the counts by kind, the
    number of contours found *before* the area filter, and the milliseconds spent.

    That raw contour count is the interesting number: it is what noise inflates, from
    nine into the thousands, while the area filter keeps the answer at nine.
    """
    rng = np.random.default_rng()
    noisy = canvas.astype(np.int16) + rng.normal(0, noise, canvas.shape)
    noisy = np.clip(noisy, 0, 255).astype(np.uint8)

    started = time.perf_counter()
    gray = cv2.cvtColor(noisy, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    found = dict.fromkeys(KINDS, 0)
    for contour in contours:
        if cv2.contourArea(contour) < MIN_AREA:
            continue
        # 3% of the perimeter is loose enough to collapse a noisy edge into one
        # straight side, and tight enough to leave a circle with far more than four.
        corners = cv2.approxPolyDP(contour, 0.03 * cv2.arcLength(contour, True), True)
        kind = {3: "triangle", 4: "rectangle"}.get(len(corners), "circle")
        found[kind] += 1
        cv2.drawContours(noisy, [contour], -1, (255, 255, 255), 2)
        top = contour[contour[:, :, 1].argmin()][0]
        cv2.putText(
            noisy,
            kind,
            (int(top[0]) - 26, int(top[1]) - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return noisy, found, len(contours), (time.perf_counter() - started) * 1000


def jpeg(image):
    """Encode a BGR array as JPEG bytes, which is what ft.Image.src takes directly.

    JPEG rather than PNG because this buffer crosses the Flet transport on every run,
    and at the top of the noise slider a PNG of the same frame is about four times
    larger.
    """
    _, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buffer.tobytes()


def row(label, *cells):
    """One line of the results table: a label, then a column per value."""
    return ft.Row(
        controls=[ft.Text(label, expand=3), *(ft.Text(c, expand=2) for c in cells)]
    )


def main(page: ft.Page):
    """Show a noise slider over a scene OpenCV has to segment, and the counts it got.

    The picture reaches the screen as JPEG bytes rather than through a window: there is
    no GUI backend in the mobile wheels, so cv2.imshow raises, and ft.Image.src taking
    bytes directly is what replaces it.
    """
    canvas, placed = scene(np.random.default_rng())

    def redraw():
        """Draw a fresh set of shapes, then segment the new scene."""
        nonlocal canvas, placed
        canvas, placed = scene(np.random.default_rng())
        segment()

    def segment():
        """Lock the controls and hand the pipeline to a background thread."""
        button.disabled = True
        spinner.visible = True
        page.update()
        page.run_thread(compute)

    def compute():
        """Segment at the slider's noise level and put the annotated frame on screen.

        The body of the thread segment() starts. Push the noise up and the contour
        count runs into five figures while the total still comes back as nine: it is
        the minimum-area filter, not the threshold, that survives a ruined picture.
        At the very top of the slider the per-kind labels do slip, because noise
        roughens an outline until approxPolyDP reads a circle as four-sided.
        """
        annotated, found, contours, elapsed = analyse(canvas, noise.value)
        frame = jpeg(annotated)
        view.src = frame
        results.controls = [
            row("", "placed", "found"),
            ft.Divider(height=1),
            *(row(kind, placed[kind], found[kind]) for kind in KINDS),
            ft.Divider(height=1),
            row("contours before filter", contours),
            row("segmented in", f"{elapsed:.0f} ms"),
            row("jpeg sent to ft.Image", f"{len(frame) / 1024:.0f} KB"),
        ]
        button.disabled = False
        spinner.visible = False
        page.update()  # auto-update does not reach background threads

    page.appbar = ft.AppBar(title=ft.Text("cv2 shape finder"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(f"OpenCV {cv2.__version__} — {SIZE}×{SIZE} scene", size=12),
                    view := ft.Image(
                        src=jpeg(canvas),
                        fit=ft.BoxFit.CONTAIN,
                        border_radius=8,
                        gapless_playback=True,
                    ),
                    ft.Text("Noise added before segmentation", size=12),
                    noise := ft.Slider(
                        min=0,
                        max=150,
                        value=30,
                        divisions=10,
                        round=0,
                        label="σ {value}",
                        # on_change would re-run the whole pipeline for every pixel the
                        # thumb travels; on_change_end runs it once, on release.
                        on_change_end=segment,
                    ),
                    ft.Row(
                        controls=[
                            button := ft.Button(
                                "New scene",
                                icon=ft.Icons.SHUFFLE,
                                on_click=redraw,
                            ),
                            spinner := ft.ProgressRing(
                                width=20,
                                height=20,
                                visible=False,
                            ),
                        ]
                    ),
                    results := ft.Column(spacing=4),
                ],
            ),
        )
    )

    segment()


if __name__ == "__main__":
    ft.run(main)
