function publish_to_pypi() {
    # Upload each wheel to Gemfury, capturing the per-wheel result and writing it
    # to the GitHub job summary. Gemfury returns 200/201 on success and 409 (or a
    # "already exists" message) for an already-published version; anything else is
    # a real failure. Duplicates are expected on re-publish, so only real failures
    # make this return non-zero (so the publish step no longer silently swallows
    # upload errors).
    local summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
    local published=0 duplicate=0 failed=0
    {
        echo "### ⬆️ Publish to pypi.flet.dev"
        echo
        echo "| Wheel | Result |"
        echo "| --- | --- |"
    } >> "$summary"
    for wheel in "$@"; do
        local name resp code body result
        name=$(basename "$wheel")
        # -w appends the HTTP status on its own final line; the rest is the body.
        resp=$(curl -sS -w $'\n%{http_code}' -F package=@"$wheel" "https://$GEMFURY_TOKEN@push.fury.io/flet/" 2>&1)
        code=$(printf '%s' "$resp" | tail -n1)
        body=$(printf '%s' "$resp" | sed '$d')
        if [ "$code" = "200" ] || [ "$code" = "201" ]; then
            result="✅ published"; published=$((published + 1))
        elif [ "$code" = "409" ] || printf '%s' "$body" | grep -qiE "already exists|same version|denied"; then
            result="⏭️ already exists"; duplicate=$((duplicate + 1))
        else
            result="❌ failed (HTTP ${code})"; failed=$((failed + 1))
        fi
        echo "publish ${name} -> HTTP ${code}: ${result}"
        echo "| \`${name}\` | ${result} |" >> "$summary"
    done
    { echo; echo "_${published} published · ${duplicate} already-published · ${failed} failed_"; echo; } >> "$summary"
    [ "$failed" -eq 0 ]
}
