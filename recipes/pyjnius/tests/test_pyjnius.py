import os

from jnius import autoclass


def test_framework_class():
    """Read `android.os.Build.BRAND` through JNI, so a JNIEnv must be reachable."""
    assert autoclass("android.os.Build").BRAND


def test_app_class():
    """Load the app's own activity host, which only the app ClassLoader can see."""
    host = autoclass(os.environ["MAIN_ACTIVITY_HOST_CLASS_NAME"])
    assert host.mActivity.getPackageName()
