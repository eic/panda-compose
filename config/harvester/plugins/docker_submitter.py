"""
DockerSubmitter — Harvester submitter plugin that runs PanDA jobs inside Docker containers.

Each worker maps to one detached container. The container image and Docker socket path are
configurable via the queue config. Job command is derived from jobSpec.jobParams fields
"transformation" (executable) and "jobPars" (argument string).

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
                    command = ["sh", "-c", "echo 'no job spec available'"]

                container_name = f"harvester-worker-{workSpec.workerID}"
                wLog.debug(f"running container image={self.containerImage} command={command}")

                container = client.containers.run(
                    self.containerImage,
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
