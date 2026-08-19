"""Coordinate maths on a device that carries no PROJ database, every answer cross-checked."""

import math
import os
import time
from array import array

# PROJ builds no context at all unless some directory holds a file named proj.db, and these
# wheels ship none — so without this every panel below is a DataDirError. An empty file
# satisfies pyproj's existence check, which is all it takes to unlock the "+proj=" strings.
# PROJ itself then rejects the file, which costs one "unable to set PROJ database path"
# warning per context and leaves EPSG-code lookups to fail. PROJ_DATA has to be set before
# the import: pyproj resolves the directory once, on its way through pyproj/__init__.py.
PROJ_DIR = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "proj")
os.makedirs(PROJ_DIR, exist_ok=True)
open(os.path.join(PROJ_DIR, "proj.db"), "ab").close()
os.environ["PROJ_DATA"] = PROJ_DIR
# PROJ's libcurl grid fetcher is compiled in and defaults to off. Assigning rather than
# setdefault is the point: setdefault would leave an inherited PROJ_NETWORK=ON in place and
# quietly turn an offline app into a downloader.
os.environ["PROJ_NETWORK"] = "OFF"

import flet as ft  # noqa: E402
import pyproj  # noqa: E402
from pyproj import CRS, Geod, Transformer  # noqa: E402
from pyproj.geod import geodesic_version_str  # noqa: E402

WGS84 = "+proj=longlat +datum=WGS84 +no_defs"
WGS84_LAT_FIRST = "+proj=longlat +datum=WGS84 +axis=neu +no_defs"
MERCATOR = "+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +units=m +no_defs"
UTM33N = "+proj=utm +zone=33 +datum=WGS84 +units=m +no_defs"
OSGB36 = (
    "+proj=longlat +ellps=airy "
    "+towgs84=446.448,-125.157,542.06,0.15,0.247,0.842,-20.489 +no_defs"
)
BNG = (
    "+proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 +x_0=400000 +y_0=-100000 "
    "+ellps=airy +towgs84=446.448,-125.157,542.06,0.15,0.247,0.842,-20.489 "
    "+units=m +no_defs"
)

WGS84_A, WGS84_F = 6378137.0, 1 / 298.257223563
# PROJ defines Airy 1830 by its two axes rather than a flattening, so derive it the same way.
AIRY_A, AIRY_F = 6377563.396, 1 - 6356256.910 / 6377563.396

CITY_PAIRS = [
    ("Paris - London", 2.3522, 48.8566, -0.1276, 51.5074),
    ("New York - Tokyo", -74.0060, 40.7128, 139.6917, 35.6895),
    ("Sydney - Cape Town", 151.2093, -33.8688, 18.4241, -33.9249),
]
MERCATOR_POINTS = [("Paris", 2.3522, 48.8566), ("Quito", -78.4678, -0.1807)]
# Label, projected CRS, the geographic CRS its datum shift lands on (None where there is no
# shift), place, lon, lat, and the ellipsoid and five parameters of the same projection
# written out for `transverse_mercator`.
TMERC_ROWS = [
    (
        "UTM 33N",
        UTM33N,
        None,
        "Oslo",
        10.7522,
        59.9139,
        (WGS84_A, WGS84_F, 0.0, 15.0, 0.9996, 500000.0, 0.0),
    ),
    (
        "Nat. Grid",
        BNG,
        OSGB36,
        "London",
        -0.1276,
        51.5074,
        (AIRY_A, AIRY_F, 49.0, -2.0, 0.9996012717, 400000.0, -100000.0),
    ),
]

GEOD = Geod(ellps="WGS84")


def spherical_mercator(lon, lat):
    """Web Mercator in two lines of `math`, to check PROJ against something independent."""
    return (
        WGS84_A * math.radians(lon),
        WGS84_A * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
    )


def transverse_mercator(lon, lat, a, f, lat_0, lon_0, k_0, x_0, y_0):
    """Easting and northing by the Ordnance Survey's series expansion of tmerc.

    The second opinion for the two rows that have no closed form: UTM and the British
    National Grid are the same projection on different ellipsoids, so one function checks
    both. A round trip cannot do this job — it returns zero for a projection string with
    the wrong zone, ellipsoid or unit, because the wrong string inverts as cleanly as the
    right one.
    """
    b = a * (1 - f)
    e2 = f * (2 - f)
    n = (a - b) / (a + b)
    lat, lon, lat_0, lon_0 = map(math.radians, (lat, lon, lat_0, lon_0))
    sin_lat, cos_lat, tan_lat = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * k_0 / math.sqrt(1 - e2 * sin_lat**2)
    rho = a * k_0 * (1 - e2) / (1 - e2 * sin_lat**2) ** 1.5
    eta2 = nu / rho - 1
    down, up = lat - lat_0, lat + lat_0
    meridian = (
        b
        * k_0
        * (
            (1 + n + 1.25 * n**2 + 1.25 * n**3) * down
            - (3 * n + 3 * n**2 + 2.625 * n**3) * math.sin(down) * math.cos(up)
            + (1.875 * n**2 + 1.875 * n**3) * math.sin(2 * down) * math.cos(2 * up)
            - 35 / 24 * n**3 * math.sin(3 * down) * math.cos(3 * up)
        )
    )
    p = lon - lon_0
    east = (
        x_0
        + nu * cos_lat * p
        + nu / 6 * cos_lat**3 * (nu / rho - tan_lat**2) * p**3
        + nu
        / 120
        * cos_lat**5
        * (5 - 18 * tan_lat**2 + tan_lat**4 + 14 * eta2 - 58 * tan_lat**2 * eta2)
        * p**5
    )
    term6 = 61 - 58 * tan_lat**2 + tan_lat**4
    north = (
        y_0
        + meridian
        + nu / 2 * sin_lat * cos_lat * p**2
        + nu / 24 * sin_lat * cos_lat**3 * (5 - tan_lat**2 + 9 * eta2) * p**4
        + nu / 720 * sin_lat * cos_lat**5 * term6 * p**6
    )
    return east, north


def vincenty_inverse(lon1, lat1, lon2, lat2):
    """Distance in metres along the WGS-84 ellipsoid by Vincenty's inverse formula.

    An independent second opinion on `Geod.inv`, which uses Karney's algorithm instead.
    Iterates on the longitude difference projected onto the auxiliary sphere; the loop
    is capped because Vincenty converges slowly for near-antipodal pairs.
    """
    minor = WGS84_A * (1 - WGS84_F)
    delta_lon = math.radians(lon2 - lon1)
    u1 = math.atan((1 - WGS84_F) * math.tan(math.radians(lat1)))
    u2 = math.atan((1 - WGS84_F) * math.tan(math.radians(lat2)))
    sin_u1, cos_u1 = math.sin(u1), math.cos(u1)
    sin_u2, cos_u2 = math.sin(u2), math.cos(u2)
    lam = delta_lon
    for _ in range(200):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.hypot(
            cos_u2 * sin_lam, cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam
        )
        if sin_sigma == 0:
            return 0.0
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sigma
        cos2_alpha = 1 - sin_alpha * sin_alpha
        cos_2sm = cos_sigma - 2 * sin_u1 * sin_u2 / cos2_alpha if cos2_alpha else 0.0
        c = WGS84_F / 16 * cos2_alpha * (4 + WGS84_F * (4 - 3 * cos2_alpha))
        previous, lam = (
            lam,
            delta_lon
            + (1 - c)
            * WGS84_F
            * sin_alpha
            * (
                sigma
                + c * sin_sigma * (cos_2sm + c * cos_sigma * (-1 + 2 * cos_2sm**2))
            ),
        )
        if abs(lam - previous) < 1e-12:
            break
    u_sq = cos2_alpha * (WGS84_A**2 - minor**2) / minor**2
    a_coef = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    b_coef = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    term3 = b_coef / 6 * cos_2sm * (-3 + 4 * sin_sigma**2) * (-3 + 4 * cos_2sm**2)
    delta_sigma = (
        b_coef
        * sin_sigma
        * (cos_2sm + b_coef / 4 * (cos_sigma * (-1 + 2 * cos_2sm**2) - term3))
    )
    return minor * a_coef * (sigma - delta_sigma)


def line(text):
    """One monospaced result line.

    Rows are formatted to 50 columns because at this size a phone wraps a little past
    that, and a wrapped column-aligned table is unreadable. `monospace` is a generic
    family name; `Courier` backs it up on platforms that do not map it.
    """
    return ft.Text(
        text, size=11, font_family="monospace", font_family_fallback=["Courier"]
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def main(page: ft.Page):
    """Four panels of coordinate maths, each printing its own disagreement with a check.

    Nothing here asserts that pyproj is right: every projected coordinate is differenced
    against arithmetic done in this file. The numbers on screen are the residuals, in
    millimetres.
    """

    def header():
        """Versions, the data directory actually in use, and PROJ's network switch.

        `show_versions()` would be the obvious call and is the wrong one — it reaches
        for the database and raises here — so each field is read separately.
        """
        rows = [
            line(
                f"pyproj {pyproj.__version__} - PROJ {pyproj.__proj_version__} - "
                f"geodesic {geodesic_version_str}"
            )
        ]
        try:
            rows.append(line(f"data dir: {pyproj.datadir.get_data_dir()}"))
            rows.append(line(f"network: {pyproj.network.is_network_enabled()}"))
        except Exception as err:
            rows.append(line(f"data dir unavailable: {type(err).__name__}: {err}"))
        return rows

    def geodesy_rows():
        """Great-circle distances from `Geod`, checked against the Vincenty above.

        This is the half of pyproj that needs no data whatsoever, so it renders no
        matter what happened to the data directory. The last column closes the loop:
        `Geod.fwd` walks the azimuth and distance `Geod.inv` just returned, and the
        miss distance is how far that lands from the point it started aiming at.
        """
        rows = [line(f"{'pair':<18}{'km':>10}{'Vinc mm':>9}{'fwd mm':>9}")]
        for name, lon1, lat1, lon2, lat2 in CITY_PAIRS:
            try:
                azimuth, _, distance = GEOD.inv(lon1, lat1, lon2, lat2)
                check = vincenty_inverse(lon1, lat1, lon2, lat2)
                end_lon, end_lat, _ = GEOD.fwd(lon1, lat1, azimuth, distance)
                _, _, miss = GEOD.inv(end_lon, end_lat, lon2, lat2)
                rows.append(
                    line(
                        f"{name:<18}{distance / 1000:>10.3f}"
                        f"{abs(distance - check) * 1000:>9.4f}{miss * 1000:>9.4f}"
                    )
                )
            except Exception as err:
                rows.append(line(f"{name}: {type(err).__name__}: {err}"))
        return rows

    def projection_rows():
        """Projected coordinates from proj-strings, each differenced against a formula.

        Web Mercator goes against `spherical_mercator`, UTM and the National Grid against
        `transverse_mercator` — for those two the datum shift is undone first, because a
        `+towgs84` Helmert is the one step with no closed form here. The round trips on
        the last line are what is left over: they measure whether that Helmert inverts,
        and nothing else.
        """
        rows = [
            line(
                f"{'crs':<10}{'point':<7}{'easting':>12}{'northing':>12} {'chk mm':>8}"
            )
        ]
        try:
            to_mercator = Transformer.from_crs(WGS84, MERCATOR, always_xy=True)
            for name, lon, lat in MERCATOR_POINTS:
                x, y = to_mercator.transform(lon, lat)
                check_x, check_y = spherical_mercator(lon, lat)
                rows.append(
                    line(
                        f"{'Mercator':<10}{name:<7}{x:>12.3f}{y:>12.3f} "
                        f"{math.hypot(x - check_x, y - check_y) * 1000:>8.4f}"
                    )
                )
            trips = []
            for label, crs, datum, name, lon, lat, shape in TMERC_ROWS:
                x, y = Transformer.from_crs(WGS84, crs, always_xy=True).transform(
                    lon, lat
                )
                shifted = (
                    (lon, lat)
                    if datum is None
                    else Transformer.from_crs(WGS84, datum, always_xy=True).transform(
                        lon, lat
                    )
                )
                check_x, check_y = transverse_mercator(*shifted, *shape)
                rows.append(
                    line(
                        f"{label:<10}{name:<7}{x:>12.3f}{y:>12.3f} "
                        f"{math.hypot(x - check_x, y - check_y) * 1000:>8.4f}"
                    )
                )
                back = Transformer.from_crs(crs, WGS84, always_xy=True)
                return_lon, return_lat = back.transform(x, y)
                _, _, residual = GEOD.inv(lon, lat, return_lon, return_lat)
                trips.append(f"{label} {residual * 1000:.4f}")
            rows.append(line(f"round trip mm  {'  '.join(trips)}"))
        except Exception as err:
            rows.append(line(f"{type(err).__name__}: {err}"))
        return rows

    def axis_rows():
        """The `always_xy` trap, shown instead of described.

        `+axis=neu` makes a latitude-first CRS — the axis order EPSG:4326 carries, and
        the reason `always_xy` exists. Both lines feed the transformer the same
        (2.3522, 48.8566); only one of them is read as (lon, lat).
        """
        rows = []
        try:
            rows.append(
                line(
                    f"axis order: {[a.abbrev for a in CRS(WGS84_LAT_FIRST).axis_info]}"
                )
            )
            for always_xy in (True, False):
                x, y = Transformer.from_crs(
                    WGS84_LAT_FIRST, MERCATOR, always_xy=always_xy
                ).transform(2.3522, 48.8566)
                rows.append(line(f"always_xy={str(always_xy):<7}{x:>16.3f}{y:>16.3f}"))
        except Exception as err:
            rows.append(line(f"{type(err).__name__}: {err}"))
        return rows

    def epsg_row():
        """What the absent database actually costs: authority codes, and nothing else.

        Every number above came out of an empty proj.db. This is the one call that
        cannot, and it is left to fail rather than guarded, so the boundary is legible on
        the device itself. It prints a CRS name on a desktop, where a database exists,
        and a CRSError on a phone — which is the whole point of running it there.
        """
        try:
            return line(f"CRS.from_epsg(4326) -> {CRS.from_epsg(4326).name}")
        except Exception as err:
            return line(f"CRS.from_epsg(4326) -> {type(err).__name__}: {err}"[:160])

    def benchmark(count):
        """Project `count` points and bring them back, timing both legs.

        Runs in the thread pool because 200k points is long enough to drop frames, and
        that is safe twice over: `Transformer` keeps one Cython transformer per thread
        behind a `threading.local`, and the transform loop releases the GIL. The
        buffers are `array('d')` — pyproj's vectorised path never imports numpy.
        """
        try:
            lons = array("d", [-180 + 360 * i / count for i in range(count)])
            lats = array("d", [-80 + 160 * i / count for i in range(count)])
            forward = Transformer.from_crs(WGS84, MERCATOR, always_xy=True)
            back = Transformer.from_crs(MERCATOR, WGS84, always_xy=True)
            started = time.perf_counter()
            xs, ys = forward.transform(lons, lats)
            projected = time.perf_counter()
            out_lons, out_lats = back.transform(xs, ys)
            finished = time.perf_counter()
            worst = max(
                max(abs(a - b) for a, b in zip(lons, out_lons)),
                max(abs(a - b) for a, b in zip(lats, out_lats)),
            )
            timing.value = (
                f"{count:,} pts  out {(projected - started) * 1000:.1f} ms  "
                f"back {(finished - projected) * 1000:.1f} ms\n"
                f"worst round trip {worst:.2e} deg"
            )
        except Exception as err:
            timing.value = f"{type(err).__name__}: {err}"
        page.update()

    def resize():
        """Re-run the benchmark at the slider's new size, off the UI thread."""
        page.run_thread(benchmark, int(size.value))

    page.appbar = ft.AppBar(title=ft.Text("Control points"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=6,
                controls=[
                    *header(),
                    ft.Divider(),
                    heading("Geodesics on the ellipsoid (no data needed)"),
                    *geodesy_rows(),
                    ft.Divider(),
                    heading("Projections from proj-strings (empty proj.db)"),
                    *projection_rows(),
                    ft.Divider(),
                    heading("Axis order"),
                    *axis_rows(),
                    ft.Divider(),
                    heading("What needs the real database"),
                    epsg_row(),
                    ft.Divider(),
                    heading("Vectorised round trip"),
                    size := ft.Slider(
                        min=10000,
                        max=200000,
                        divisions=19,
                        value=50000,
                        label="{value} points",
                        on_change_end=resize,
                    ),
                    timing := line("measuring..."),
                ],
            ),
        )
    )

    page.run_thread(benchmark, int(size.value))


if __name__ == "__main__":
    ft.run(main)
