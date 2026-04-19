# Job Management

The `scripts/` directory contains three Python wrapper scripts that talk to the PanDA
REST API via [panda-client](https://pypi.org/project/panda-client/).

## Prerequisites

```bash
pip install panda-client
```

Set the following environment variables (the dev-stack defaults are shown):

```bash
export PANDA_URL=http://localhost:25080/server/panda
export PANDA_URL_SSL=http://localhost:25080/server/panda
export X509_USER_PROXY=/dev/null   # suppress grid-proxy noise in dev mode
```

## Submit a job

```bash
JOB_ID=$(python3 scripts/pandajob-submit \
    --site  PANDA_COMPOSE_LOCAL \
    --transformation /bin/echo \
    --params "hello world" \
    --name  my-test-job)
echo "Submitted PanDA job $JOB_ID"
```

On success a single integer job ID is printed to stdout.

### Submit options

| Option | Default | Description |
|---|---|---|
| `--site SITE` | `PANDA_COMPOSE_LOCAL` | PanDA compute site / queue name |
| `--transformation PATH` | — | Binary to execute **inside the harvester container** |
| `--script PATH` | — | Script on the **host** filesystem (not available inside container — use `--transformation` instead) |
| `--params STRING` | `""` | Arguments passed to the transformation |
| `--name NAME` | `panda-compose-job` | Human-readable job label |
| `--cores N` | `1` | CPU cores requested |
| `--memory MB` | `2000` | Memory in MB |
| `--walltime S` | `3600` | Wall-clock limit in seconds |

> **Important:** The `--transformation` value must be a path to a binary that exists
> **inside the harvester container**, not on the host. Common safe choices:
> `/bin/echo`, `/bin/true`, `/bin/sleep`. Custom binaries can be provided by building
> a derived harvester image or by bind-mounting a script into the container.

## Query job status

```bash
python3 scripts/pandajob-status $JOB_ID
```

Prints a JSON object to stdout:

```json
{
  "jobID": 7,
  "jobStatus": "finished",
  "exeErrorCode": 0,
  "exeErrorDiag": "",
  "pilotErrorCode": 0,
  "pilotErrorDiag": "",
  "taskBufferErrorCode": 0,
  "taskBufferErrorDiag": ""
}
```

### Known status values

| Status | Description |
|---|---|
| `defined` | Job received by PanDA server; awaiting JEDI activation |
| `waiting` | Held by JEDI pending resource availability |
| `assigned` | Assigned to a site |
| `activated` | Ready to be picked up by Harvester |
| `sent` | Retrieved by Harvester |
| `starting` | Worker process launched |
| `running` | Worker reported in-progress |
| `merging` | Output merging (not used in this stack) |
| `transferring` | Worker finished; adder daemon processing output |
| `finished` | Job completed successfully ✅ |
| `failed` | Job completed with non-zero exit code ❌ |
| `cancelled` | Job killed by user or system |

## Cancel a job

```bash
python3 scripts/pandajob-kill $JOB_ID
```

Exits 0 even if the job is already in a terminal state.

## Job lifecycle timing

A typical job submitted with `/bin/echo` or `/bin/true` follows this state progression:

```mermaid
stateDiagram-v2
    [*] --> defined : submitJob()
    defined --> activated : JEDI JobGenerator\n(30–90 s)
    activated --> sent : Harvester getJobs()\n(~10 s)
    sent --> starting : worker launched
    starting --> running : worker reports in
    running --> transferring : worker completes\n(~5 s)
    transferring --> finished : adder daemon\n(up to 6 min)
    transferring --> failed : non-zero exit code
    finished --> [*]
    failed --> [*]
```

Total end-to-end: **2–8 minutes**. The adder daemon loop that transitions jobs from
`transferring` to `finished` runs every ~6 minutes, which is the dominant factor in
total job time.

## Polling pattern

```bash
TIMEOUT=600   # 10 minutes
DEADLINE=$((SECONDS + TIMEOUT))
while [[ $SECONDS -lt $DEADLINE ]]; do
    STATUS=$(python3 scripts/pandajob-status "$JOB_ID" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['jobStatus'])")
    echo "[$(date -u '+%H:%M:%S')] $STATUS"
    case "$STATUS" in
        finished) echo "Done!"; break ;;
        failed|cancelled) echo "Job ended: $STATUS"; exit 1 ;;
    esac
    sleep 15
done
```
