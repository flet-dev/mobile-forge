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

    Skipped on iOS until the flet-libgdal / flet-libproj recipes stop
    stripping `share/` from the install (and the iOS app launcher sets
    `GDAL_DATA` / `PROJ_DATA` to point at them). Even when the caller
    supplies no CRS, OGR's GeoJSON writer calls into PROJ to stamp a
    default WGS84 metadata field, which fails with `Cannot find
    proj.db` and surfaces as `FionaNullPointerError`. Distinct from
    the linker-level static-cascade fix this recipe already ships —
    that's `import fiona` succeeding; this is runtime data."""
    import sys

    if sys.platform == "ios":
        pytest.skip(
            "iOS: proj.db not bundled — see flet-libgdal/libproj `rm -rf "
            "$PREFIX/share` strip step; needs follow-up recipe change."
        )

    import fiona

    schema = {"geometry": "Point", "properties": {"name": "str"}}
    path = tmp_path / "tiny.geojson"

    with fiona.open(path, "w", driver="GeoJSON", schema=schema) as dst:
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

    `flet-libproj` carries no PROJ database, so any CRS naming an authority
    fails inside PROJ before fiona sees it. Measured on an arm64-v8a Android 14
    emulator: `CRSError: The WKT could not be parsed. PROJ:
    proj_create_from_database: Cannot find proj.db`. Spell the CRS as a
    proj-string instead — the test above does, and round trips to 1e-6.

    This is the same gap `pyproj` has, from the same library. Pinning it here
    means a chain that later gains the database turns this test red, which is
    the prompt to tell consumers the restriction has lifted.
    """
    from fiona.transform import transform

    with pytest.raises(Exception) as excinfo:
        transform("EPSG:4326", "EPSG:3857", [4.3517], [50.8503])
    assert "proj.db" in str(excinfo.value), excinfo.value
