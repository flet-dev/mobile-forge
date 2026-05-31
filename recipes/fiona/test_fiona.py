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

    Note: we deliberately AVOID `fiona.crs.from_epsg(4326)` here. That
    call requires PROJ's `proj.db` SQLite database to be present at
    runtime; the mobile-forge fiona/PROJ wheels don't bundle it, so the
    EPSG lookup fails with `Cannot find proj.db`. A bare CRS string
    works without the database — GeoJSON simply records it as a
    coordinate-reference-system metadata field."""
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
