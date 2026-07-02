import os
import tempfile


# astropy eagerly creates a config dir (~/.astropy) on import; on iOS/Android HOME
# may be unset or non-writable, so point the config/cache dirs at a writable temp
# location before importing astropy.
_cfg = os.path.join(tempfile.gettempdir(), "astropy_cfg")
os.makedirs(_cfg, exist_ok=True)
os.environ.setdefault("XDG_CONFIG_HOME", _cfg)
os.environ.setdefault("XDG_CACHE_HOME", _cfg)
os.environ.setdefault("HOME", _cfg)


def test_time_scale_conversion():
    """Cython time extension + erfa dispatch: J2000 epoch -> JD 2451544.5."""
    from astropy.time import Time

    t = Time("2000-01-01T00:00:00", scale="utc")
    assert abs(float(t.jd) - 2451544.5) < 1e-6
    assert t.tt.iso  # utc->tt conversion runs through erfa


def test_io_fits_roundtrip():
    """Vendored cfitsio C-extension: write then read a small FITS image."""
    import numpy as np
    from astropy.io import fits

    data = np.arange(12, dtype="int32").reshape(3, 4)
    path = os.path.join(tempfile.gettempdir(), "astropy_smoke.fits")
    fits.PrimaryHDU(data).writeto(path, overwrite=True)
    assert np.array_equal(fits.getdata(path), data)


def test_wcs_roundtrip():
    """Vendored wcslib C-extension: pixel <-> world coordinate round-trip."""
    import numpy as np
    from astropy.wcs import WCS

    w = WCS(naxis=2)
    w.wcs.crpix = [1, 1]
    w.wcs.cdelt = [-0.001, 0.001]
    w.wcs.crval = [10.0, 20.0]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    world = w.wcs_pix2world([[1, 1]], 1)
    pix = w.wcs_world2pix(world, 1)
    assert np.allclose(pix, [[1, 1]], atol=1e-6)


def test_coordinates_transform():
    """Runtime erfa path: transform M31's ICRS coordinates to galactic."""
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    c = SkyCoord(ra=10.68458 * u.deg, dec=41.26917 * u.deg, frame="icrs")
    gal = c.galactic
    assert gal.l.deg and gal.b.deg


def test_cosmology_inv_efunc():
    """Directly runs the scalar_inv_efuncs Cython kernel — the exact code the
    Android cpow=True patch modifies. A wCDM dark-energy model routes through
    fwcdm_inv_efunc_norel, whose `opz**(3*(1+w0))` term is what Cython lowered
    to the C complex-power cpow(). Calling the bound Cython function directly
    (needs no scipy): for FlatwCDM(Om0=0.3, w0=-0.9, Tcmb0=0),
    1/E(z=1) = (0.3*2**3 + 0.7*2**0.3)**-0.5 = 0.553696. A broken cpow lowering
    would give a wrong value / NaN / crash here."""
    from astropy.cosmology import FlatwCDM

    cosmo = FlatwCDM(H0=70, Om0=0.3, w0=-0.9, Tcmb0=0)
    val = cosmo._inv_efunc_scalar(1.0, *cosmo._inv_efunc_scalar_args)
    assert abs(val - 0.553696) < 1e-4
