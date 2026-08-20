import math

import erfa
import numpy as np
from erfa.version import erfa_version, sofa_version

VERSION = f"pyerfa {erfa.__version__} · ERFA {erfa_version} · SOFA {sofa_version}"

MAS_YR = erfa.DAS2R / 1000.0  # milliarcsec/year -> radians/year

# Hipparcos catalogue rows, ICRS at J2000: name, RA, declination, mu_alpha*
# (mas/yr), mu_delta (mas/yr), parallax (mas), radial velocity (km/s).
STARS = (
    ("Sirius", "06 45 08.917", "-16 42 58.02", -546.01, -1223.07, 379.21, -5.50),
    ("Vega", "18 36 56.336", "+38 47 01.28", 200.94, 286.23, 130.23, -20.60),
    ("Arcturus", "14 15 39.672", "+19 10 56.67", -1093.45, -1999.40, 88.83, -5.19),
    ("Betelgeuse", "05 55 10.305", "+07 24 25.43", 27.54, 11.30, 6.55, 21.91),
    ("Polaris", "02 31 49.095", "+89 15 50.79", 44.48, -11.85, 7.54, -16.42),
)

# name, east longitude (deg), latitude (deg), height above the ellipsoid (m)
SITES = (
    ("Paris", 2.3522, 48.8566, 35.0),
    ("Nairobi", 36.8219, -1.2921, 1795.0),
    ("Tokyo", 139.6917, 35.6895, 40.0),
    ("Sydney", 151.2093, -33.8688, 58.0),
    ("Santiago", -70.6693, -33.4489, 570.0),
)

SCALES = ("UTC", "UT1", "TAI", "TT", "TDB")

# Ambient conditions for ERFA's refraction model: hPa, Celsius, relative humidity
# 0-1, micrometres. A pressure of zero switches refraction off altogether.
WEATHER = (1013.25, 12.0, 0.5, 0.55)

# Polar motion in radians. The real value is a couple of tenths of an arcsecond,
# published daily by the IERS and unknowable offline; zero costs well under an
# arcsecond, which is why this example frets about UT1 and not about this.
POLAR_MOTION = (0.0, 0.0)


def catalogue():
    """Turn the star table into the six ICRS arrays ERFA's atciq wants.

    Two unit traps live here, and each yields a plausible wrong answer rather
    than an error. ERFA takes the RA proper motion as dRA/dt, while catalogues
    publish mu_alpha* = dRA/dt · cos(dec); the divisor runs from 1.01 on
    Betelgeuse to 78 on Polaris, and omitting it moved these five stars by
    0.01 to 1.6 arcsec in a desktop check at the current epoch — growing from
    zero at J2000, so the mistake is cheap now and 4x worse by 2100. The huge
    divisor on Polaris is not a huge error: cos(dec) inflates the divisor and
    then compresses the resulting RA error into a short arc on the sky.

    Parallax is the more expensive trap. It is in arcseconds, not the
    milliarcseconds every modern catalogue prints, and passing mas straight
    through moved the same five stars by 6 to 334 arcsec.
    """
    ra, dec, pr, pd, px, rv = [], [], [], [], [], []
    for _, ra_text, dec_text, pm_ra_star, pm_dec, parallax, radial in STARS:
        hour, minute, second = ra_text.split()
        degree, arcmin, arcsec = dec_text[1:].split()
        ra.append(erfa.tf2a("+", int(hour), int(minute), float(second)))
        dec.append(erfa.af2a(dec_text[0], int(degree), int(arcmin), float(arcsec)))
        pr.append(pm_ra_star * MAS_YR / math.cos(dec[-1]))
        pd.append(pm_dec * MAS_YR)
        px.append(parallax / 1000.0)
        rv.append(radial)
    return tuple(np.array(column) for column in (ra, dec, pr, pd, px, rv))


CATALOGUE = catalogue()


def utc_from(when):
    """Split an aware UTC datetime into ERFA's two-part Julian date.

    Two doubles rather than one because a single float64 Julian date resolves to
    about 40 microseconds near the present epoch, and the split keeps the day
    number and the fraction from competing for the same 53 bits.
    """
    seconds = when.second + when.microsecond / 1e6
    return erfa.dtf2d(
        "UTC", when.year, when.month, when.day, when.hour, when.minute, seconds
    )


def leap_seconds():
    """Report the leap-second table that is compiled into the wheel.

    Nothing is read from disk or the network: the table is C data inside
    erfa/ufunc.abi3.so. `expires` is pyerfa's own heuristic — 180 days past the
    final entry — so it reads as long overdue while the value it returns is
    still correct, because no leap second has been introduced since.
    """
    table = erfa.leap_seconds.get()
    last = table[-1]
    return {
        "entries": len(table),
        "last": f"{int(last['year'])}-{int(last['month']):02d}-01",
        "tai_utc": float(last["tai_utc"]),
        "expires": erfa.leap_seconds.expires.date().isoformat(),
    }


def time_scales(utc, site, dut1):
    """Run one instant through UTC, UT1, TAI, TT and TDB and report the offsets.

    Only two of the four steps are arithmetic. UTC to TAI is a table lookup.
    TT to TDB is a periodic series, mostly the Earth's orbit at about 1.6 ms
    amplitude, plus a diurnal term from the observer's own position — which is
    why the site's geocentric coordinates get computed here, even though that
    term spans under 4 microseconds across these five sites and so never reaches
    the millisecond this table prints. UTC to UT1 is neither kind of step: dut1
    is a measurement of the Earth, and the caller has to supply it.
    """
    _, longitude, latitude, height = site
    east, phi = math.radians(longitude), math.radians(latitude)
    x, y, z = erfa.gd2gc(1, east, phi, height) / 1000.0

    ut1 = erfa.utcut1(*utc, dut1)
    tai = erfa.utctai(*utc)
    tt = erfa.taitt(*tai)
    tdb = erfa.tttdb(*tt, erfa.dtdb(*tt, ut1[1] % 1.0, east, math.hypot(x, y), z))

    rows = []
    for name, (d1, d2) in zip(SCALES, (utc, ut1, tai, tt, tdb)):
        *_, hmsf = erfa.d2dtf(name, 3, d1, d2)
        clock = f"{hmsf['h']:02d}:{hmsf['m']:02d}:{hmsf['s']:02d}.{hmsf['f']:03d}"
        offset = ((d1 - utc[0]) + (d2 - utc[1])) * erfa.DAYSEC
        rows.append((name, clock, offset))
    return rows


def positions(utc, site, dut1):
    """Transform the whole catalogue to observed alt/az, and price the dut1 guess.

    ERFA offers a one-call transform, atco13, but it rebuilds the Earth-rotation
    and aberration context for every star handed to it. Building that context
    once with apco13 and reusing it through atciq and atioq agreed with atco13 to
    better than a nanoarcsecond and ran about 85x faster per star on desktop, so
    the transform here runs twice over and still costs less.

    The second pass is the teaching one: it repeats the transform with dut1 set
    to zero, and the separation between the two answers is what not knowing the
    Earth's rotation angle is worth on the sky.
    """
    _, longitude, latitude, height = site
    east, phi = math.radians(longitude), math.radians(latitude)
    az, alt = _observed(utc, east, phi, height, dut1)
    az0, alt0 = _observed(utc, east, phi, height, 0.0)
    moved = erfa.seps(az, alt, az0, alt0) * erfa.DR2AS

    rows = [
        (
            star[0],
            math.degrees(alt[index]),
            math.degrees(az[index]) % 360.0,
            float(moved[index]),
        )
        for index, star in enumerate(STARS)
    ]
    return sorted(rows, key=lambda row: -row[1])


def _observed(utc, east, phi, height, dut1):
    """Apply one astrometry context to every star, returning azimuth and altitude.

    atioq reports zenith distance rather than altitude, and it is the refracted
    one: the star is where the atmosphere makes it look, not where the geometry
    puts it.
    """
    astrom, _ = erfa.apco13(*utc, dut1, east, phi, height, *POLAR_MOTION, *WEATHER)
    ri, di = erfa.atciq(*CATALOGUE, astrom)
    az, zenith = erfa.atioq(ri, di, astrom)[:2]
    return az, math.pi / 2 - zenith
