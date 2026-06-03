import pytest


def test_jvm_classes():
    """Reach into the Android `android.os.Build` static class to read the
    device's BRAND. This requires:
      - the libpyjni .so to have loaded,
      - the embedded VM to be reachable via JNI,
      - the recipe's startup hooks (in mobile-forge/serious_python) to
        have configured the right ClassLoader.
    Three layers in one assert."""
    try:
        from jnius import autoclass
    except (ImportError, Exception):
        # On non-Android hosts the import of jnius raises because no JVM
        # can be located. Skip — this test is meaningful only on device.
        pytest.skip("pyjnius requires an Android JVM at runtime")

    Build = autoclass("android.os.Build")
    brand = Build.BRAND
    # BRAND is a non-empty string on real & emulated devices.
    assert isinstance(brand, str)
    assert len(brand) > 0
