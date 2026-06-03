#!/usr/bin/env bash
# Run inside reactivecircus/android-emulator-runner@v2's script: field.
# That action runs each script line through `sh -c` separately, which breaks
# multi-line bash constructs (functions, traps, if blocks). So the whole
# logic lives in this dedicated script file with its own bash shebang;
# the workflow's `script:` field just invokes this file as a one-liner.
#
# Side effects:
#   - installs + launches the recipe-tester APK at
#     tests/recipe-tester/build/apk/recipe-tester.apk
#   - delegates the poll-and-parse to .ci/wait_for_console.sh
#   - on failure, dumps `adb logcat -d` and a screencap into the workspace
#     root so the workflow's upload-artifact step can pick them up
#     (the AVD is alive at trap-time; the post-action phase has already
#     killed it by the time the workflow's failure-conditional steps run)

set -eux

cleanup() {
    rc=$?
    if [ "$rc" -ne 0 ]; then
        adb logcat -d > logcat-on-failure.txt 2>/dev/null || true
        adb exec-out screencap -p > screen-on-failure.png 2>/dev/null || true
    fi
    return $rc
}
trap cleanup EXIT

adb install -r tests/recipe-tester/build/apk/recipe-tester.apk
adb logcat -c
adb shell monkey -p com.flet.recipe_tester -c android.intent.category.LAUNCHER 1

# 15min hard cap on the device-side run; recipe tests should finish in
# <2min, the extra slack absorbs AVD slowness.
TIMEOUT=900 .ci/wait_for_console.sh android
