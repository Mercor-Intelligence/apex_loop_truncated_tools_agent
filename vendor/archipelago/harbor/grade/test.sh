#!/bin/sh
#
# Harbor verifier entrypoint. Runs in the separate verifier container after the
# agent is torn down and the collect hooks have landed their artifacts.
#
set -eu

mkdir -p /logs/verifier /logs/artifacts

grading_rc=0
# POSIX sh has no pipefail, so the grader writes its own log and we keep its code.
python3 /tests/grade.py > /logs/verifier/grade_log.txt 2>&1 || grading_rc=$?
cat /logs/verifier/grade_log.txt

if [ "$grading_rc" -eq 0 ] && [ ! -f /logs/verifier/reward.json ]; then
    printf '{"grading_error": true, "detail": "grader exited 0 without writing a reward"}\n' \
        > /logs/verifier/grading_error.json
    grading_rc=1
fi

# Harbor auto-collects /logs/artifacts/ into the trial dir with a manifest.
for f in reward.txt reward.json grade_details.json grading_error.json grade_log.txt; do
    cp -f "/logs/verifier/$f" /logs/artifacts/ 2>/dev/null || true
done
cp -f /logs/agent/trajectory.json /logs/artifacts/ 2>/dev/null || true
mkdir -p /logs/artifacts/world
cp -f /logs/world/boot.log /logs/artifacts/world/ 2>/dev/null || true

# Grading failure ERRORS the trial; exiting 0 here would score it 0.0.
exit "$grading_rc"
