def test_list_drivers():
    """pyogrio is a Cython wrapper for GDAL/OGR's vector I/O. Listing
    drivers is the smallest C-call we can make to confirm libgdal is
    loaded; it runs through the `_ogr` extension, so it says nothing
    about whether `_io` can actually open a dataset."""
    import pyogrio

    drivers = pyogrio.list_drivers()
    assert isinstance(drivers, dict)
    # Universal drivers — present in any GDAL build with vector support.
    assert "ESRI Shapefile" in drivers
    assert "GeoJSON" in drivers


def test_gdal_version():
    """Confirms the GDAL C library version is reported. `get_gdal_version`
    lives in `_ogr`, so this reaches the same extension as the driver
    list, not a separate one."""
    import pyogrio

    v = pyogrio.__gdal_version__
    # `__gdal_version__` is a 3-tuple of ints.
    assert isinstance(v, tuple)
    assert len(v) == 3
    assert all(isinstance(x, int) for x in v)
    assert v[0] >= 3  # GDAL ≥ 3.0
