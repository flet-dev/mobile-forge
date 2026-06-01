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

    import pytest

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
