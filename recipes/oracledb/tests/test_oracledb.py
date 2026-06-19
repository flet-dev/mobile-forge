def test_import_and_thin_mode():
    """Loads all four Cython extensions — oracledb/__init__.py does
    `from . import base_impl, thick_impl, thin_impl` (and arrow) at import, so
    this proves every .so cross-compiled and loads. thick_impl loads WITHOUT the
    Oracle Instant Client (ODPI-C dlopens it lazily, only on thick init), and the
    default THIN mode needs no Oracle client libraries at all."""
    import oracledb

    assert oracledb.__version__
    assert oracledb.is_thin_mode() is True


def test_thin_connect_errors_cleanly():
    """No DB server here — prove the thin driver's Cython network/protocol path
    actually RUNS on-device by connecting to an unreachable listener and getting
    a clean `oracledb.Error` (DB-API base), not an ImportError or native crash."""
    import oracledb

    try:
        oracledb.connect(
            user="x",
            password="x",
            dsn="127.0.0.1:1521/FREEPDB1",
            tcp_connect_timeout=3,
        )
    except oracledb.Error:
        pass  # expected: nothing is listening, thin driver reports it cleanly
    else:
        raise AssertionError("expected a connection error against an unreachable DB")
