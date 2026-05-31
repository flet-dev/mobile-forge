def test_geod_distance():
    """pyproj wraps PROJ (the C cartographic projection library). The
    Geod (geodesic) API operates directly on the WGS-84 ellipsoid and
    doesn't need PROJ's database (proj.db) — perfect for mobile, where
    the recipe doesn't bundle that ~9 MB sqlite file. Paris → London is
    ~344 km along the WGS-84 geodesic."""
    from pyproj import Geod

    g = Geod(ellps="WGS84")
    _, _, dist = g.inv(2.3522, 48.8566, -0.1276, 51.5074)
    km = dist / 1000.0
    assert 340 < km < 350


def test_geod_forward():
    """The forward problem: given a start point, azimuth, and distance,
    where do you end up? Also database-free."""
    from pyproj import Geod

    g = Geod(ellps="WGS84")
    # Start at the equator/prime meridian, head due east 1000 km.
    lon, lat, back_az = g.fwd(0.0, 0.0, 90.0, 1_000_000)
    # Should still be on the equator (within precision), longitude ~9°.
    assert abs(lat) < 0.01
    assert 8.9 < lon < 9.1
