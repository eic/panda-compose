#!/bin/bash
# panda-worker.sh — minimal PanDA worker for the panda-compose dev stack.
#
# Usage: panda-worker.sh <accessPoint>
#
# The SharedFileMessenger writes a CGI-encoded pandaJobData.out file to the
# accessPoint directory.  This script reads it, executes the requested
# transformation, and writes jobReport.json so Harvester can report back.

set -uo pipefail

ACCESS_POINT="${1:?Usage: panda-worker.sh <accessPoint>}"
JOB_DATA="${ACCESS_POINT}/pandaJobData.out"
JOB_REPORT="${ACCESS_POINT}/jobReport.json"

# Wait up to 60 s for the job data file to appear.
for i in $(seq 1 60); do
    [ -f "${JOB_DATA}" ] && break
    sleep 1
done

if [ ! -f "${JOB_DATA}" ]; then
    echo '{"exitCode": 1, "exitMsg": "pandaJobData.out not found after 60s"}' > "${JOB_REPORT}"
    exit 1
fi

# Parse the CGI-encoded key=value pairs (Python is always available in the
# Harvester image where this script runs).
TRANSFORM=$(python3 -c "
import urllib.parse
d = dict(urllib.parse.parse_qsl(open('${JOB_DATA}').read(), keep_blank_values=True))
print(d.get('transformation', ''))
")

JOB_PARS=$(python3 -c "
import urllib.parse
d = dict(urllib.parse.parse_qsl(open('${JOB_DATA}').read(), keep_blank_values=True))
print(d.get('jobPars', ''))
")

echo "[panda-worker] accessPoint=${ACCESS_POINT}"
echo "[panda-worker] transformation=${TRANSFORM}"
echo "[panda-worker] jobPars=${JOB_PARS}"

if [ -z "${TRANSFORM}" ]; then
    echo '{"exitCode": 1, "exitMsg": "transformation not set in pandaJobData.out"}' > "${JOB_REPORT}"
    exit 1
fi

# Execute the job.
EXIT_CODE=0
# shellcheck disable=SC2086
${TRANSFORM} ${JOB_PARS} || EXIT_CODE=$?

echo "[panda-worker] exitCode=${EXIT_CODE}"

# Write the report that Harvester will pick up.
python3 -c "
import json
report = {'exitCode': ${EXIT_CODE}, 'exitMsg': 'worker finished'}
with open('${JOB_REPORT}', 'w') as f:
    json.dump(report, f)
"
