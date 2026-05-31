def test_wgs84_to_utm():
    """pyproj wraps PROJ (the C cartographic projection library).
    Transform Paris from WGS-84 lat/lon to UTM zone 31N."""
    from pyproj import Transformer

    # EPSG:4326 (WGS-84 lat/lon) → EPSG:32631 (UTM 31N)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32631", always_xy=True)
    easting, northing = transformer.transform(2.3522, 48.8566)  # Paris

    # Coarse band — Paris in UTM 31N is around (452_500, 5_412_000).
    # Tolerance keeps the test robust to small datum / grid-shift changes
    # between PROJ versions.
    assert 451_000 < easting < 454_000
    assert 5_410_000 < northing < 5_414_000


def test_geod_distance():
    """Geodetic distance — PROJ-style geodesic calc on the WGS-84 ellipsoid.
    Paris to London is ~344 km."""
    from pyproj import Geod

    g = Geod(ellps="WGS84")
    _, _, dist = g.inv(2.3522, 48.8566, -0.1276, 51.5074)
    km = dist / 1000.0
    assert 340 < km < 350
