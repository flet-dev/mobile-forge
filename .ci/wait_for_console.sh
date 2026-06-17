#!/usr/bin/env bash
# Poll the recipe-tester's console.log on a mobile device/simulator, parse
# the EXIT sentinel, write a GitHub Step Summary, and exit with the
# sentinel's code.
#
# Usage:
#   wait_for_console.sh android
#   wait_for_console.sh ios
#
# Environment overrides:
#   TIMEOUT        seconds to wait for the EXIT sentinel (default: 600)
#   INTERVAL       seconds between polls (default: 2)
#   ANDROID_PKG    Android package id (default: com.flet.recipe_tester)
#   IOS_BUNDLE     iOS bundle id     (default: com.flet.recipe-tester)
#
# Exit codes:
#   0   tests passed (sentinel reported EXIT 0)
#   1   tests failed (sentinel reported non-zero)
#   2   timed out — no EXIT sentinel ever appeared in console.log
#   3   environment error (couldn't gain access to console.log)
#
# Side effects:
#   - copies console.log to the current working directory (so the workflow's
#     upload-artifact step can pick it up)
#   - appends a markdown block to $GITHUB_STEP_SUMMARY (when set)
#
# Why a file and not log stream / logcat? Flet's launcher redirects Python
# stdout/stderr to $FLET_APP_CONSOLE = <app temp>/console.log in production
# builds, so raw print() output never reaches `adb logcat` or
# `xcrun simctl log stream` — the file is the only place it lands.

set -euo pipefail

PLATFORM="${1:-}"
if [[ "$PLATFORM" != "android" && "$PLATFORM" != "ios" ]]; then
    echo "usage: $0 <android|ios>" >&2
    exit 3
fi

TIMEOUT="${TIMEOUT:-600}"
INTERVAL="${INTERVAL:-2}"
ANDROID_PKG="${ANDROID_PKG:-com.flet.recipe_tester}"
IOS_BUNDLE="${IOS_BUNDLE:-com.flet.recipe-tester}"
OUT="$PWD/console.log"

# --- platform-specific console.log fetch ------------------------------------

if [[ "$PLATFORM" == "android" ]]; then
    # console.log lives at /data/data/<pkg>/cache/console.log in the app
    # sandbox. Reading it requires either `adb root` (works on userdebug
    # AVDs — the standard ReactiveCircus/android-emulator-runner default)
    # or the app being marked debuggable. We assume userdebug AVD.
    #
    # Retry: under high CI parallelism (~20 emulators sharing the runner
    # pool) `adb root` occasionally fires before adbd is fully ready and
    # reports "permission denied — must be userdebug" even on a userdebug
    # AVD. A short retry loop eats the race.
    adb_root_ok=0
    for attempt in 1 2 3 4 5 6; do
        if adb root >/dev/null 2>&1; then
            adb_root_ok=1
            break
        fi
        sleep 5
    done
    if [[ "$adb_root_ok" != "1" ]]; then
        echo "::error::adb root failed after 6 retries — AVD must be userdebug (or the app debuggable)"
        exit 3
    fi
    # adbd restarts after `adb root`; wait for it to come back.
    adb wait-for-device
    REMOTE="/data/data/$ANDROID_PKG/cache/console.log"
    fetch() { adb pull "$REMOTE" "$OUT" >/dev/null 2>&1 || true; }

elif [[ "$PLATFORM" == "ios" ]]; then
    # On iOS simulator the app sandbox is on the host fs — no copy, no
    # permissions. simctl get_app_container resolves the per-app data path.
    DATA=$(xcrun simctl get_app_container booted "$IOS_BUNDLE" data 2>/dev/null || true)
    if [[ -z "$DATA" ]]; then
        echo "::error::xcrun simctl get_app_container failed — is the app installed and a sim booted?"
        exit 3
    fi
    REMOTE="$DATA/Library/Caches/console.log"
    fetch() { [[ -f "$REMOTE" ]] && cp "$REMOTE" "$OUT" || true; }
fi

# --- poll loop --------------------------------------------------------------

echo "::group::Polling $REMOTE for EXIT sentinel (timeout=${TIMEOUT}s)"

# Truncate any stale local copy.
: > "$OUT"

deadline=$(( $(date +%s) + TIMEOUT ))
attempts=0
while [[ "$(date +%s)" -lt "$deadline" ]]; do
    attempts=$(( attempts + 1 ))
    fetch
    if [[ -s "$OUT" ]] && grep -qE '^>>>>>>>>>> EXIT [0-9-]+ <<<<<<<<<<$' "$OUT"; then
        echo "found EXIT sentinel after ${attempts} polls"
        break
    fi
    sleep "$INTERVAL"
done

echo "::endgroup::"

# --- parse + report ---------------------------------------------------------

if [[ ! -s "$OUT" ]] || ! grep -qE '^>>>>>>>>>> EXIT [0-9-]+ <<<<<<<<<<$' "$OUT"; then
    echo "::error::Timed out after ${TIMEOUT}s without seeing EXIT sentinel"
    if [[ -s "$OUT" ]]; then
        echo "::group::Tail of console.log (last 50 lines)"
        tail -50 "$OUT"
        echo "::endgroup::"
    else
        echo "(console.log is empty or absent — Python may have crashed before any output)"
    fi
    exit 2
fi

# Format:
#   >>>>>>>>>> EXIT 0 <<<<<<<<<<
#   ↑ $1       ↑ $2 ↑ $3 ↑ $4
# `tail -1` defensively picks the last match in case the runner ever
# emits multiple — today it prints exactly once.
EXIT_CODE=$(grep -oE '^>>>>>>>>>> EXIT [0-9-]+ <<<<<<<<<<$' "$OUT" \
            | tail -1 \
            | awk '{print $3}')

# Pull pytest's pass/fail line out of the log too, e.g.
#   ============================== 2 passed in 0.02s ===============================
PYTEST_SUMMARY=$(grep -E '^=+ .* (passed|failed|error|skipped).* =+$' "$OUT" | tail -1 || true)

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    # Annotate non-zero codes with a one-liner so the GH summary is
    # self-explanatory at a glance. EXIT_CODE here is pytest's exit
    # code (carried through the sentinel) — pytest exit codes per
    # https://docs.pytest.org/en/stable/reference/exit-codes.html.
    case "$EXIT_CODE" in
        1) meaning=" (tests failed)" ;;
        2) meaning=" (test execution interrupted)" ;;
        3) meaning=" (internal pytest error)" ;;
        4) meaning=" (pytest usage error)" ;;
        5) meaning=" (no tests collected)" ;;
        *) meaning="" ;;
    esac
    {
        echo "### 🧪 On-device test — ${PLATFORM}"
        echo
        if [[ "$EXIT_CODE" == "0" ]]; then
            echo "**Result:** ✅ exit 0"
        else
            echo "**Result:** ❌ exit ${EXIT_CODE}${meaning}"
        fi
        if [[ -n "$PYTEST_SUMMARY" ]]; then
            echo
            echo "\`${PYTEST_SUMMARY}\`"
        fi
        echo
        echo "<details><summary>Tail of <code>console.log</code> (last 50 lines)</summary>"
        echo
        echo '```'
        tail -50 "$OUT"
        echo '```'
        echo
        echo "</details>"
    } >> "$GITHUB_STEP_SUMMARY"
fi

echo "exit code: $EXIT_CODE"
exit "$EXIT_CODE"
