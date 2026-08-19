"""An almanac that never touches the network: sky positions, time scales, FITS.

Every number on screen comes from data that shipped inside the wheels, and every
panel states its own verdict instead of just printing a value.
"""

import math
import os
import tempfile

import flet as ft
import numpy as np

# astropy resolves its config directory while `import astropy` is still running, and
# falls back to Path.home() — which raises on the Flet iOS runtime, since that has no
# `pwd` module to fall back to when HOME is unset. astropy 8 also ignores these two
# variables unless the directories already exist, so the makedirs is the load-bearing
# half: setting the variables without it warns once and then crashes anyway.
_TEMP = os.getenv("FLET_APP_STORAGE_TEMP") or tempfile.gettempdir()
_DATA = os.getenv("FLET_APP_STORAGE_DATA") or _TEMP
_CONFIG_DIR = os.path.join(_DATA, "astropy", "config")
_CACHE_DIR = os.path.join(_TEMP, "astropy", "cache")
os.makedirs(_CONFIG_DIR, exist_ok=True)
os.makedirs(_CACHE_DIR, exist_ok=True)
os.environ.setdefault("ASTROPY_CONFIG_DIR", _CONFIG_DIR)
os.environ.setdefault("ASTROPY_CACHE_DIR", _CACHE_DIR)

import astropy  # noqa: E402
import astropy.units as u  # noqa: E402
import astropy.utils.data  # noqa: E402
import astropy_iers_data  # noqa: E402
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body  # noqa: E402
from astropy.io import fits  # noqa: E402
from astropy.time import Time  # noqa: E402
from astropy.utils import iers  # noqa: E402

# Two switches, because they cover different things. Without auto_download=False every
# Earth-orientation lookup re-tries two download URLs at a 10 s timeout each; without
# allow_internet=False the same lookups still emit three warnings apiece. The
# astropy.utils.data import above is what makes the second line legal: plain
# `import astropy` leaves astropy.utils.data unbound.
iers.conf.auto_download = False
astropy.utils.data.conf.allow_internet = False

FITS_PATH = os.path.join(_DATA, "roundtrip.fits")

# Berlin, hard-coded: EarthLocation.of_site downloads a site catalogue that is not in
# the wheel, so it raises offline rather than degrading.
SITE = EarthLocation(lat=52.520008 * u.deg, lon=13.404954 * u.deg, height=34 * u.m)

# ICRS positions with the galactic coordinates SIMBAD publishes for them. Those are
# quoted to four decimal degrees, so agreement closer than 0.36" is all the reference
# can prove.
OBJECTS = [
    ("M31", 10.684708, 41.268750, 121.1743, -21.5733),
    ("Betelgeuse", 88.792939, 7.407064, 199.7872, -8.9586),
    ("Sgr A*", 266.416837, -29.007810, 359.9442, -0.0462),
    ("M1 (Crab)", 83.633083, 22.014500, 184.5575, -5.7844),
]
QUOTING_PRECISION = 0.36

# 1 pc = 648000/pi au and 1 ly = 9460730472580800 m, both exact by IAU definition, so
# the ratio is a reference the app can derive rather than remember.
PC_IN_LYR = (648000 / math.pi * 149597870700) / 9460730472580800

TARGET = SkyCoord(ra=OBJECTS[0][1] * u.deg, dec=OBJECTS[0][2] * u.deg, frame="icrs")


def table_span():
    """Read the coverage of the bundled IERS-A table off the table itself.

    Returns the last MJD it holds and the last row that is a measurement rather than a
    prediction — the two dates that bound how far this build can be trusted.
    """
    tbl = iers.IERS_Auto.open()
    mjd = np.asarray(tbl["MJD"].value, dtype=float)
    measured = mjd[np.asarray(tbl["UT1Flag"]) != "P"]
    return mjd.min(), mjd.max(), measured.max()


def self_checks():
    """Run the checks whose answers are known in advance, and report pass or fail.

    Each exercises a different part of the wheel — the unit machinery, the leap-second
    table, the ERFA-backed frame transforms, the vendored cfitsio writer — against a
    value that comes from a definition or a catalogue rather than from astropy itself.
    """
    lines = []

    ratio = (1 * u.pc).to(u.lyr).value
    ok = math.isclose(ratio, PC_IN_LYR, rel_tol=1e-12)
    lines.append(
        f"{'PASS' if ok else 'FAIL'}  1 pc = {ratio:.10f} lyr (IAU: {PC_IN_LYR:.10f})"
    )

    leap = Time("2016-12-31T23:59:60", scale="utc")
    ok = leap.tai.isot == "2017-01-01T00:00:36.000"
    lines.append(
        f"{'PASS' if ok else 'FAIL'}  leap second 23:59:60 UTC -> {leap.tai.isot} TAI"
    )

    worst, worst_name = 0.0, ""
    for name, ra, dec, gl, gb in OBJECTS:
        got = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs").galactic
        sep = got.separation(
            SkyCoord(l=gl * u.deg, b=gb * u.deg, frame="galactic")
        ).arcsec
        if sep > worst:
            worst, worst_name = sep, name
    ok = worst <= QUOTING_PRECISION
    lines.append(
        f"{'PASS' if ok else 'FAIL'}  ICRS->galactic, worst of {len(OBJECTS)} "
        f'({worst_name}) {worst:.2f}" vs {QUOTING_PRECISION}" quoting precision'
    )

    data = np.linspace(0, 1, 64, dtype="float32").reshape(8, 8)
    hdu = fits.PrimaryHDU(data)
    hdu.header["OBJECT"] = "M31"
    hdu.writeto(FITS_PATH, overwrite=True)
    with fits.open(FITS_PATH) as opened:
        back, header = opened[0].data, opened[0].header
    ok = np.array_equal(back, data) and header["OBJECT"] == "M31"
    lines.append(
        f"{'PASS' if ok else 'FAIL'}  FITS round trip, {os.path.getsize(FITS_PATH)} bytes, "
        f"max|diff| {np.abs(back - data).max():.1f}"
    )

    try:
        1 * u.m + 1 * u.s
        lines.append("FAIL  1 m + 1 s was accepted")
    except Exception as exc:
        lines.append(f"PASS  1 m + 1 s raised {type(exc).__name__}, caught here: {exc}")

    return lines


def main(page: ft.Page):
    """An almanac for one date, with the offline caveats printed next to the answers.

    The slider moves the date past the end of the bundled Earth-orientation table on
    purpose: that is the moment UT1-UTC silently freezes, and the banner is the only
    thing that says so.
    """

    def almanac():
        """Recompute every value that depends on the chosen date.

        Runs in the thread pool because the first call is by far the slowest: opening
        the Earth-orientation table parses ~20,000 rows out of the two bundled files,
        measured at 330 ms on a development machine and cached from then on. Wrapped
        broadly because a failure here should reach the screen rather than vanish into
        the pool.
        """
        try:
            first_mjd, last_mjd, measured_mjd = table_span()
            coverage.value = (
                f"Bundled Earth orientation covers "
                f"{Time(first_mjd, format='mjd').iso[:10]} to "
                f"{Time(last_mjd, format='mjd').iso[:10]}, measured to "
                f"{Time(measured_mjd, format='mjd').iso[:10]}."
            )
            when = Time.now() + float(months.value) * 30.4375 * u.day
            sun, moon = get_body("sun", when), get_body("moon", when)
            alt = TARGET.transform_to(AltAz(obstime=when, location=SITE))
            dut1 = float(np.ravel(np.asarray(when.delta_ut1_utc))[0])
            tai_utc = (when.tai.jd - when.utc.jd) * 86400
            # Read after that first conversion on purpose: until astropy has loaded
            # Leap_Second.dat into ERFA, this still reports pyerfa's compiled-in 2017
            # expiry, which reads as a table nine years stale.
            leap_expires = iers.LeapSeconds.from_erfa().expires.iso[:10]
            sky.value = (
                f"{when.utc.isot[:19]} UTC   TAI-UTC {tai_utc:.0f} s\n"
                f"Leap-second table expires {leap_expires}\n"
                f"Sun    RA {sun.ra.deg:8.3f}  Dec {sun.dec.deg:+7.3f}\n"
                f"Moon   RA {moon.ra.deg:8.3f}  Dec {moon.dec.deg:+7.3f}\n"
                f"M31 from Berlin   alt {alt.alt.deg:+7.3f}  az {alt.az.deg:8.3f}\n"
                f"UT1-UTC {dut1:+.6f} s"
            )
            if when.mjd <= measured_mjd:
                banner.value = "Earth orientation: measured"
                banner.color = ft.Colors.GREEN
            elif when.mjd <= last_mjd:
                left = last_mjd - when.mjd
                banner.value = f"Earth orientation: predicted, {left:.0f} days left"
                banner.color = ft.Colors.AMBER
            else:
                banner.value = (
                    "Earth orientation: PAST THE TABLE. UT1-UTC is frozen at its last "
                    "value with no warning. Leap seconds cap frozen and true at 0.9 s "
                    "each, so they differ by up to 1.8 s, and 1 s of UT1 error is "
                    '15.04" x cos(dec) of sky error — ~11" for M31 here, ~27" on the '
                    "celestial equator."
                )
                banner.color = ft.Colors.RED
        except Exception as exc:
            sky.value = f"{type(exc).__name__}: {exc}"
            banner.value = "Earth orientation: unknown, the almanac did not finish"
            banner.color = ft.Colors.RED
        page.update()  # auto-update does not reach background threads

    def startup():
        """First-launch work: the almanac, then the self-checks, both off the UI thread.

        The self-checks get the same broad guard the almanac has: run_thread drops the
        worker's future, so an unguarded raise here would leave the panel reading
        "running…" for the rest of the session with nothing logged anywhere.
        """
        almanac()
        try:
            checks.value = "\n".join(self_checks())
        except Exception as exc:
            checks.value = f"self-checks did not finish — {type(exc).__name__}: {exc}"
        page.update()

    def on_epoch_change():
        """Recompute on on_change_end, so a drag does not queue one run per pixel."""
        page.run_thread(almanac)

    page.appbar = ft.AppBar(title=ft.Text("Offline almanac"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text(
                        f"astropy {astropy.__version__} · astropy-iers-data "
                        f"{astropy_iers_data.__version__}\n"
                        f"auto_download={iers.conf.auto_download} · "
                        f"allow_internet={astropy.utils.data.conf.allow_internet}",
                        size=11,
                    ),
                    coverage := ft.Text(size=11),
                    months := ft.Slider(
                        min=-12,
                        max=36,
                        divisions=48,
                        value=0,
                        label="{value} months from now",
                        on_change_end=on_epoch_change,
                    ),
                    banner := ft.Text(size=12, weight=ft.FontWeight.BOLD),
                    sky := ft.Text(font_family="monospace", size=12, selectable=True),
                    ft.Divider(),
                    ft.Text("Self-checks", weight=ft.FontWeight.BOLD),
                    checks := ft.Text("running…", size=11, selectable=True),
                    ft.Divider(),
                    ft.Text(
                        "Not attempted, because each is a download with nothing "
                        "bundled behind it: EarthLocation.of_site and "
                        "get_site_names (site catalogue), SkyCoord.from_name "
                        "(Sesame), EarthLocation.of_address (geocoding), and "
                        "solar_system_ephemeris.set('jpl') (needs jplephem, which "
                        "is not installed). Sun and Moon above come from ERFA's "
                        "built-in ephemeris instead.",
                        size=11,
                    ),
                ],
            ),
        )
    )

    # After page.add, so the walrus-bound controls above it exist.
    page.run_thread(startup)


if __name__ == "__main__":
    ft.run(main)
