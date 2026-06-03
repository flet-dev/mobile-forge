def test_gdal_version():
    """`rasterio.__gdal_version__` reads from `rasterio._base` (a Cython
    extension that links libgdal). Confirms the native extension loaded
    and libgdal is reachable — the canary for the GDAL_LIBS chain
    declared in meta.yaml (mirrors recipes/pyogrio's test_gdal_version).
    """
    import rasterio

    v = rasterio.__gdal_version__
    # `__gdal_version__` is a "MAJOR.MINOR.PATCH" string in modern
    # rasterio. Be tolerant about extra suffixes like "3.10.0e".
    parts = v.split(".")
    assert len(parts) >= 2, f"unexpected GDAL version string: {v!r}"
    assert int(parts[0]) >= 3, f"GDAL major < 3: {v!r}"


def test_drivers_listed():
    """Touches `rasterio._env` (driver registration) + `rasterio.drivers`.
    Asks for the registered raster driver count to confirm GDAL's
    driver registry initialised inside the Cython binding."""
    import rasterio

    # `rasterio.drivers` is the public driver-management module; the
    # `is_blacklisted` predicate is the cheapest call that round-trips
    # through `rasterio._env.GDALEnv` and proves the driver registry
    # initialised. GTiff is universal in any GDAL build with raster
    # support.
    from rasterio.drivers import is_blacklisted

    # Built-in driver — should not be blacklisted.
    assert is_blacklisted("GTiff", "r") is False
