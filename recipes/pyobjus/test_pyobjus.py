"""pyobjus is the Objective-C bridge used to call into iOS frameworks
from Python. It can ONLY run on a real Apple platform — on Android /
Linux there's no Objective-C runtime to bind against. The test below
runs on the iOS simulator job; other platforms skip at import time."""

import pytest


def test_objc_classes():
    """Reach into Foundation's NSDate to read the current epoch. This
    requires:
      - libpyobjus loaded,
      - the Objective-C runtime accessible (CoreFoundation linked),
      - NSDate's class methods resolvable through autoclass."""
    try:
        from pyobjus import autoclass
    except (ImportError, Exception):
        pytest.skip("pyobjus requires the Objective-C runtime (iOS/macOS)")

    NSDate = autoclass("NSDate")
    now = NSDate.alloc().init()
    # `timeIntervalSince1970` returns a float since the epoch — a non-zero
    # plausible value means the bridge fully resolved class + method + return.
    epoch = now.timeIntervalSince1970()
    assert isinstance(epoch, float)
    assert epoch > 1_700_000_000.0  # later than 2023-11-14
