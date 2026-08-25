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


def test_vector_round_trip(tmp_path):
    """Write features and read them back — the path listing drivers does not cover.

    The two tests above touch `pyogrio._ogr`, which calls `GDALAllRegister()`
    itself. `_io`, where a read or a write actually happens, is a different
    extension — and with a static libgdal it links its own copy of GDAL with
    its own driver registry. So a wheel can list every driver and still be
    unable to open a dataset, which is what made the iOS breakage invisible to
    this suite for as long as it was.

    This asserts the round trip instead: two Points out through the GeoJSON
    driver, both back with their attribute intact.
    """
    import struct

    import numpy as np
    from pyogrio.raw import read, write

    def wkb_point(x, y):
        return struct.pack("<BI2d", 1, 1, x, y)

    path = tmp_path / "round-trip.geojson"
    geometry = np.array([wkb_point(4.35, 50.85), wkb_point(2.35, 48.85)], dtype=object)
    names = np.array(["brussels", "paris"], dtype=object)

    write(
        str(path), geometry=geometry, field_data=[names], fields=["name"],
        driver="GeoJSON", geometry_type="Point", crs="EPSG:4326",
    )
    assert path.exists() and path.stat().st_size > 0

    _meta, _fids, read_geometry, read_fields = read(str(path))

    assert len(read_geometry) == 2, len(read_geometry)
    assert list(read_fields[0]) == ["brussels", "paris"], read_fields[0]
