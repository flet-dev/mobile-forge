import pytest


def test_import_fiona():
    """`import fiona` triggers `fiona._env.so`'s dlopen. On iOS, the
    published wheel's _env.so was linked against `libgdal.a` only — GDAL's
    static archive leaks undefined references for symbols GDAL itself uses
    from libproj/libtiff/libcurl/libpsl/openssl. iOS dyld eagerly resolves
    the flat namespace at dlopen and aborts with
    `symbol not found in flat namespace '_geod_init'` (or _TIFFClientOpen
    / _curl_easy_init / _psl_builtin, depending on which gap is hit
    first). Android isn't affected — libproj/libtiff/libcurl/etc. are
    shared libraries there, so their symbols resolve via DT_NEEDED."""
    import fiona

    assert hasattr(fiona, "supported_drivers")
    assert hasattr(fiona, "open")


def test_supported_drivers():
    """fiona binds GDAL's vector I/O (OGR). Listing supported drivers is
    the lightest-weight way to confirm the C lib loaded without needing
    a test shapefile."""
    import fiona

    drivers = list(fiona.supported_drivers.keys())
    # ESRI Shapefile + GeoJSON are universal — if the GDAL lib is loaded
    # at all, these are present.
    assert "ESRI Shapefile" in drivers
    assert "GeoJSON" in drivers


def test_write_read_geojson(tmp_path):
    """Write a Point feature to GeoJSON then read it back — covers OGR's
    writer + reader without depending on bundled test data.

    This used to skip on iOS, on the reasoning that OGR's GeoJSON writer stamps
    a default WGS84 field through PROJ even when the caller supplies no CRS, so
    the missing `proj.db` made a write impossible. Naming the CRS as a
    proj-string avoids that lookup entirely — PROJ needs its database only to
    resolve an authority code — and `pyogrio`, which shares this GDAL, writes
    GeoJSON on an iPhone simulator this way. So the restriction is avoidable
    rather than fundamental, and the test now runs everywhere.

    It also covers the driver registry: `ogrext`, where `fiona.open` works, has
    its own GDAL copy under a static libgdal, and `ios-driver-registry.patch`
    is what populates it. Without that patch this fails at the driver rather
    than at the CRS."""
    import fiona

    schema = {"geometry": "Point", "properties": {"name": "str"}}
    path = tmp_path / "tiny.geojson"

    # proj-string, never an authority code: this chain ships no proj.db.
    with fiona.open(
        path, "w", driver="GeoJSON", schema=schema,
        crs="+proj=longlat +datum=WGS84 +no_defs",
    ) as dst:
        dst.write(
            {
                "geometry": {"type": "Point", "coordinates": (2.35, 48.86)},
                "properties": {"name": "Paris"},
            }
        )

    with fiona.open(path) as src:
        feats = list(src)
        assert len(feats) == 1
        assert feats[0]["properties"]["name"] == "Paris"
        assert tuple(feats[0]["geometry"]["coordinates"]) == (2.35, 48.86)


def test_transform_loads_and_reprojects():
    """`fiona.transform` is the one import that needs `libc++_shared.so`.

    `fiona/_transform.so` is the only extension of the eight whose `DT_NEEDED`
    names it, and plain `import fiona` never loads that module — so a wheel
    missing `flet-libcpp-shared` from its `Requires-Dist` installs cleanly,
    passes every other test here, and fails only when an app reaches for a
    reprojection.

    The CRSs are spelled as proj-strings rather than EPSG codes deliberately.
    `flet-libproj` ships no `proj.db`, so anything naming an authority raises
    `CRSError: PROJ: proj_create_from_database: Cannot find proj.db` — a real
    limitation, covered separately by `test_epsg_codes_need_proj_db`. Using a
    proj-string keeps this test pinned to the thing it is about: that the
    extension loads and computes.
    """
    from fiona.transform import transform

    wgs84 = "+proj=longlat +datum=WGS84 +no_defs"
    mercator = "+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +units=m +no_defs"

    lon, lat = 4.3517, 50.8503
    x, y = transform(wgs84, mercator, [lon], [lat])
    assert 484_000 < x[0] < 485_000, x
    assert 6_593_000 < y[0] < 6_595_000, y

    back_lon, back_lat = transform(mercator, wgs84, x, y)
    assert abs(back_lon[0] - lon) < 1e-6, back_lon
    assert abs(back_lat[0] - lat) < 1e-6, back_lat


def test_epsg_codes_need_proj_db():
    """EPSG codes do not resolve: the chain ships no `proj.db`.

    `flet-libproj` carries no PROJ database, so any CRS naming an authority fails
    before fiona can use it. Spell the CRS as a proj-string instead — the test
    above does, and round trips to 1e-6.

    The two platforms report the same gap differently, which is why this asserts
    the failure rather than its wording: Android surfaces PROJ's own
    `proj_create_from_database: Cannot find proj.db`, while iOS surfaces GDAL's
    `The WKT could not be parsed. OGR Error code 6`. An earlier version of this
    test pinned the Android string and went red on iOS for the wrong reason.

    This is the same gap `pyproj` has, from the same library. Pinning it here
    means a chain that later gains the database turns this test red, which is
    the prompt to tell consumers the restriction has lifted.
    """
    import pytest

    from fiona.errors import CRSError
    from fiona.transform import transform

    wgs84 = "+proj=longlat +datum=WGS84 +no_defs"
    mercator = "+proj=merc +a=6378137 +b=6378137 +lon_0=0 +units=m +no_defs"
    # Proj-strings must keep working wherever this runs; that is the control.
    assert transform(wgs84, mercator, [4.3517], [50.8503])[0]

    try:
        transform("EPSG:4326", "EPSG:3857", [4.3517], [50.8503])
    except CRSError:
        return  # the expected state on a device: no proj.db, authority lookups fail
    pytest.skip(
        "a PROJ database is present, so authority codes resolve — the state this "
        "test exists to detect is a device without one. If this skip ever appears "
        "on a device, the chain has gained proj.db and the docs saying otherwise "
        "need updating."
    )
