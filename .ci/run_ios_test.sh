#!/usr/bin/env bash
# Mirror of .ci/run_android_test.sh for the iOS Simulator lane.
#
# Boots an iPhone simulator if none is running, installs the recipe-tester
# .app, launches it, then delegates the EXIT-sentinel poll to
# .ci/wait_for_console.sh ios.
#
# Side effects:
#   - on failure, dumps `xcrun simctl spawn booted log show --last 10m`
#     into syslog-on-failure.txt and a screencap into screen-on-failure.png
#     so the workflow's upload-artifact step can pick them up. The simulator
#     is still booted at trap-time (the workflow doesn't shut it down
#     itself), so these calls work.
#
# Why a separate script (not inline `run:`): same reason as the Android
# helper — keep the dash/bash quirks inside a file with a proper bash
# shebang so multi-line constructs survive whatever shell the action
# eventually picks. (Less critical here since the iOS step is a plain
# `run: bash` rather than an action's split-by-line script:, but it's
# consistent and keeps the diff focused.)

set -eux

APP=tests/recipe-tester/build/ios-simulator/recipe-tester.app
IOS_BUNDLE=${IOS_BUNDLE:-com.flet.recipe-tester}

cleanup() {
    rc=$?
    if [ "$rc" -ne 0 ]; then
        xcrun simctl spawn booted log show --last 10m > syslog-on-failure.txt 2>/dev/null || true
        xcrun simctl io booted screenshot screen-on-failure.png 2>/dev/null || true
    fi
    return $rc
}
trap cleanup EXIT

# Pick + boot a simulator if none is currently booted. Robust to the
# specific device names changing between macos image versions: grab the
# first available iPhone in any iOS runtime.
if ! xcrun simctl list devices booted | grep -q "Booted"; then
    UDID=$(xcrun simctl list devices available -j \
        | jq -r '.devices | to_entries[]
                 | select(.key | contains("iOS"))
                 | .value[]
                 | select(.isAvailable == true and (.name | startswith("iPhone")))
                 | .udid' \
        | head -1)
    if [ -z "$UDID" ]; then
        echo "::error::no iPhone simulator available on this runner"
        xcrun simctl list devices available
        exit 3
    fi
    echo "Booting simulator $UDID"
    xcrun simctl boot "$UDID"
fi
xcrun simctl bootstatus booted -b

xcrun simctl install booted "$APP"
xcrun simctl launch booted "$IOS_BUNDLE"

# Same 15-min device-side cap as Android. Tests should finish in <2min;
# the slack absorbs cold-boot + first-launch Python init overhead.
TIMEOUT=900 .ci/wait_for_console.sh ios
