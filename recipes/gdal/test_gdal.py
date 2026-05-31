def test_in_memory_raster():
    """GDAL's MEM driver creates an in-memory raster — no disk I/O,
    no test data file. Touches the C++ raster band API."""
    from osgeo import gdal

    drv = gdal.GetDriverByName("MEM")
    assert drv is not None
    ds = drv.Create("", 4, 3, 1, gdal.GDT_Byte)
    assert ds.RasterXSize == 4
    assert ds.RasterYSize == 3

    band = ds.GetRasterBand(1)
    band.Fill(7)
    raw = band.ReadRaster(0, 0, 4, 3)  # 4*3*1 byte = 12 bytes
    assert raw == bytes([7] * 12)


def test_version_loaded():
    """Confirms the libgdal C++ runtime is wired through SWIG."""
    from osgeo import gdal

    assert gdal.VersionInfo()
