# Architecture & Design

## Design goals

panda-compose provides a **self-contained, single-host PanDA deployment** for:

- Development and debugging of tools that integrate with PanDA (executors, plugins, workflow managers)
- CI smoke testing of PanDA-dependent code without a production cluster
- Experimentation with PanDA configuration before deploying to [panda-k8s](https://github.com/PanDAWMS/panda-k8s)

The stack is intentionally minimal: all services run in Docker containers with no
external dependencies (no Rucio, no ATLAS grid services, no token broker).

## Service topology

```
┌─────────────────────────────────────────────────────────────┐
│  Docker Compose network                                     │
│                                                             │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                │
│  │ postgres │   │activemq  │   │ mariadb  │                │
│  │ (PanDA   │   │(STOMP/   │   │(Harvester│                │
│  │  schema) │   │ OpenWire)│   │   DB)    │                │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘                │
│       │              │              │                       │
│  ┌────▼──────────────▼──┐     ┌─────▼──────────────┐       │
│  │    panda-server      │     │      harvester      │       │
│  │  (REST API / httpd)  │◄────┤  (subprocess jobs) │       │
│  └─────────┬────────────┘     └────────────────────┘       │
│            │                                                │
│  ┌─────────▼────────────┐                                   │
│  │      panda-jedi      │                                   │
│  │  (workload manager)  │                                   │
│  └──────────────────────┘                                   │
│                                                             │
│  ┌──────────────────────┐                                   │
│  │   init (one-shot)    │  registers PANDA_COMPOSE_LOCAL    │
│  └──────────────────────┘  queue in schedconfig            │
└─────────────────────────────────────────────────────────────┘
         ▲
         │  http://localhost:25080
    panda-client / tools under test
```

## Service dependency order

| Phase | Services | Condition |
|---|---|---|
| 1 | `postgres`, `activemq`, `mariadb` | health checks pass |
| 2 | `panda-server` | `postgres` + `activemq` healthy |
| 2 | `init` (one-shot) | `postgres` + `panda-server` healthy |
| 3 | `panda-jedi` | `panda-server` healthy + `init` succeeded |
| 3 | `harvester` | `panda-server` + `mariadb` healthy |

## Component descriptions

### postgres — PanDA database

Uses `ghcr.io/pandawms/panda-database:latest`, which ships with the full PanDA + JEDI
PostgreSQL schema pre-installed. On first run the `panda_db_init.sh` entrypoint script
creates the `panda` database role using `PANDA_DB_PASSWORD`.

The schema uses multiple schema namespaces mapped to PostgreSQL schemas:
`DOMA_PANDA`, `DOMA_PANDAMETA`, `DOMA_PANDAARCH`, `DOMA_DEFT`.
An additional `atlas_panda` schema is created by the `init` service as a view alias
over `doma_panda`, satisfying Oracle-legacy references in PanDA/JEDI code.

### activemq — message broker

Uses `ghcr.io/pandawms/panda-activemq:latest`. The `panda-server` and `panda-jedi`
daemons exchange job status events over STOMP (port 61613). OpenWire (port 61616)
is also exposed. The web console is available at `http://localhost:8161/admin/`.

The image `CMD` defaults to `sleep infinity`; we override it to
`/opt/activemq/bin/run-activemq-services`. The `JAVA_TOOL_OPTIONS` env var disables
a JDK 18 cgroup v2 detection bug (JDK-8281631) that would otherwise crash the JVM.

### panda-server — REST API

Uses `ghcr.io/pandawms/panda-server:latest` (Apache httpd + mod_wsgi + PanDA server
Python code). The startup sequence mirrors the panda-k8s StatefulSet pattern:

1. Copy sandbox scripts from `/opt/panda/sandbox/` to `/data/panda/`
2. Run `process_template.py` to expand `${VAR}` in `*.template` config files
3. Remove stale lock/PID files from any previous container run
4. Execute `run-panda-services`

The server is accessible at `http://localhost:25080/server/panda` (HTTP only in dev).
`PANDA_AUTH=None` disables all authentication — no tokens or certificates required.

### panda-jedi — workload manager

Uses `ghcr.io/pandawms/panda-jedi:latest`. JEDI runs several daemons:

- **JediMaster** — process supervisor
- **JobGenerator** — activates `defined` jobs → `activated`
- **TaskBroker** — assigns tasks to sites (may crash on startup due to an argument-order
  bug in `GenJobBroker.__init__`; non-fatal for direct job submission)
- **WatchDog**, **PostProcessor**, etc.

JEDI depends on the `init` service completing successfully to ensure the
`PANDA_COMPOSE_LOCAL` queue is registered and the `pandadb_version` JEDI row exists
before it starts reading schedconfig.

### mariadb — Harvester database

Uses `mariadb:10.11` (standard LTS image). Harvester stores its internal state
(worker records, job mappings, statistics) in MariaDB. The schema is created
automatically by Harvester on first startup via its `make_tables` migration.

### init — queue registration (one-shot)

The `init` service runs `scripts/setup-queue.sh` once after `postgres` and
`panda-server` are healthy, then exits 0. It:

1. Inserts the `PANDA_COMPOSE_LOCAL` site into `schedconfig` and `cloudconfig`
2. Inserts a JEDI version row into `pandadb_version` (required by JEDI startup)
3. Creates the `atlas_panda` schema with 261 VIEWs over `doma_panda` tables

`panda-jedi` has `depends_on: init: service_completed_successfully`, so it will not
start until the init container exits 0.

### harvester — job executor

Uses `ghcr.io/hsf/harvester:latest`. In this stack, Harvester is configured to use
lightweight subprocess plugins (no batch system required):

| Plugin | File | Purpose |
|---|---|---|
| `SubprocessSubmitter` | `scripts/subprocess_submitter.py` | Launches `panda-worker.sh` as a local subprocess |
| `SubprocessMonitor` | `scripts/subprocess_monitor.py` | Checks for `jobReport.json` to detect completion |
| `DummyStager` | *(built-in)* | No-op output staging (no Rucio) |
| `SharedFileMessenger` | *(built-in)* | File-based job description exchange |

The worker script (`scripts/panda-worker.sh`) parses the PanDA job descriptor
(`pandaJobData.out`), runs the requested transformation binary, and writes
`jobReport.json` with the exit code.

## Job lifecycle

```
[client]          [panda-server]     [panda-jedi]    [harvester]
    │                   │                  │               │
    ├── submitJob() ───►│                  │               │
    │                   │ defined          │               │
    │                   │◄─────────────────┤ activates job │
    │                   │ activated        │               │
    │                   │◄─────────────────────────────────┤ getJobs()
    │                   │ sent             │               │
    │                   │                 │               ├── panda-worker.sh
    │                   │                 │               │   (exec transform)
    │                   │◄─────────────────────────────────┤ updateJobs(running)
    │                   │ running          │               │
    │                   │◄─────────────────────────────────┤ updateJobs(transferring)
    │                   │ transferring     │               │
    │                   │ [adder daemon processes jobReport.json]
    │                   │ finished ✓       │               │
    ├── getJobStatus() ►│                  │               │
    │◄── {finished} ────┤                  │               │
```

End-to-end timing for a trivial job (e.g., `/bin/echo`):

| Stage | Typical duration |
|---|---|
| `defined` → `activated` | 30–90 s (JEDI JobGenerator cycle) |
| `activated` → `sent` → `starting` | ~10 s (Harvester getJobs + submit) |
| `starting` → `transferring` | ~5 s (worker runs and writes report) |
| `transferring` → `finished` | up to 6 min (adder daemon loop interval) |
| **Total** | **2–8 minutes** |

## Subprocess plugin design

The Harvester subprocess plugins are intentionally simple and self-contained.
They are suitable for running short-lived test transformations inside the
harvester container, not for production workloads.

`subprocess_submitter.py`:
- Receives a list of `WorkSpec` objects from Harvester
- For each worker, writes a `pandaJobData.out` file from the job descriptor
- Launches `panda-worker.sh` with `subprocess.Popen` (non-blocking)
- Returns `ST_submitted` immediately

`subprocess_monitor.py`:
- Receives a list of `WorkSpec` objects from Harvester
- For each worker, checks whether `jobReport.json` exists in the worker directory
- If present, reads `exitCode` and returns `ST_finished` or `ST_failed`

`panda-worker.sh`:
- Parses `pandaJobData.out` (CGI-encoded key-value format) using `grep`
- Sets `TRANSFORM` and `JOB_PARAMS` from the descriptor
- Runs `exec $TRANSFORM $JOB_PARAMS`
- On exit, writes `{"exitCode": N, "exitMsg": "..."}` to `jobReport.json`

> **Note:** The `--transformation` value in job submission must refer to a binary
> available **inside the harvester container**, not on the host. Use `/bin/echo`,
> `/bin/true`, or a custom binary baked into a derived harvester image.
