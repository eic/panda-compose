"""
DockerSubmitter — Harvester submitter plugin that runs PanDA jobs inside Docker containers.

Each worker maps to one detached container. The image is resolved in priority order:
  1. job.jobParams["container_name"] — per-job image set by the submitter via
     job.container_name (mirrors PanDA's production container_name field); any
     leading "docker://" prefix is stripped for Docker SDK compatibility.
  2. containerImage queue config key — the site-level default (e.g. "alpine:latest").

The Docker socket path is configurable via the dockerSocket queue config key.
Job command is derived from jobSpec.jobParams fields "transformation" (executable)
and "jobPars" (argument string).

Queue config example:

    "submitter": {
        "name": "DockerSubmitter",
        "module": "docker_submitter",
        "containerImage": "alpine:latest",
        "dockerSocket": "unix:///var/run/docker.sock"
    }
"""

import shlex

import docker as docker_module
from pandaharvester.harvestercore import core_utils
from pandaharvester.harvestercore.plugin_base import PluginBase

baseLogger = core_utils.setup_logger("docker_submitter")


class DockerSubmitter(PluginBase):
    def __init__(self, **kwarg):
        self.containerImage = "alpine:latest"
        self.dockerSocket = "unix:///var/run/docker.sock"
        PluginBase.__init__(self, **kwarg)

    def _resolve_image(self, job, wLog):
        """Return the Docker image to use for this job.

        Per-job container_name takes priority over the queue-level default.
        Strips any leading "docker://" prefix so the Docker SDK gets a plain
        registry reference (e.g. "docker://python:3.12-alpine" → "python:3.12-alpine").
        """
        per_job = job.jobParams.get("container_name", "").strip() if job else ""
        if per_job:
            image = per_job.removeprefix("docker://")
            wLog.debug(f"using per-job container image={image} (from container_name)")
        else:
            image = self.containerImage
            wLog.debug(f"using queue default container image={image}")
        return image

    def submit_workers(self, workspec_list):
        tmpLog = self.make_logger(baseLogger, method_name="submit_workers")
        tmpLog.debug(f"start nWorkers={len(workspec_list)}")

        try:
            client = docker_module.DockerClient(base_url=self.dockerSocket)
        except Exception as exc:
            err = f"Failed to connect to Docker daemon at {self.dockerSocket}: {exc}"
            tmpLog.error(err)
            return [(False, err)] * len(workspec_list)

        retList = []
        for workSpec in workspec_list:
            wLog = self.make_logger(baseLogger, f"workerID={workSpec.workerID}", method_name="submit_workers")
            try:
                jobspec_list = workSpec.get_jobspec_list()
                if jobspec_list:
                    job = jobspec_list[0]
                    transformation = job.jobParams.get("transformation", "sh")
                    job_pars = job.jobParams.get("jobPars", "")
                    command = [transformation] + shlex.split(job_pars) if job_pars else [transformation]
                else:
                    job = None
                    command = ["sh", "-c", "echo 'no job spec available'"]

                image = self._resolve_image(job, wLog)
                container_name = f"harvester-worker-{workSpec.workerID}"
                wLog.debug(f"running container image={image} command={command}")

                container = client.containers.run(
                    image,
                    command=command,
                    name=container_name,
                    detach=True,
                    remove=False,
                )
                workSpec.batchID = container.id
                wLog.debug(f"started container id={container.id[:12]}")
                retList.append((True, ""))
            except Exception as exc:
                err = f"Failed to start container for workerID={workSpec.workerID}: {exc}"
                wLog.error(err)
                retList.append((False, err))

        try:
            client.close()
        except Exception:
            pass

        tmpLog.debug("done")
        return retList
