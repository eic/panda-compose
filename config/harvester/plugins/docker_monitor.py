"""
DockerMonitor — Harvester monitor plugin for Docker container workers.

Polls the Docker daemon for container state and maps it to WorkSpec status values.

Queue config example:

    "monitor": {
        "name": "DockerMonitor",
        "module": "docker_monitor",
        "dockerSocket": "unix:///var/run/docker.sock"
    }
"""

import docker as docker_module
from pandaharvester.harvestercore import core_utils
from pandaharvester.harvestercore.plugin_base import PluginBase
from pandaharvester.harvestercore.work_spec import WorkSpec

baseLogger = core_utils.setup_logger("docker_monitor")


class DockerMonitor(PluginBase):
    def __init__(self, **kwarg):
        self.dockerSocket = "unix:///var/run/docker.sock"
        PluginBase.__init__(self, **kwarg)

    def check_workers(self, workspec_list):
        tmpLog = self.make_logger(baseLogger, method_name="check_workers")
        tmpLog.debug(f"start nWorkers={len(workspec_list)}")

        try:
            client = docker_module.DockerClient(base_url=self.dockerSocket)
        except Exception as exc:
            err = f"Failed to connect to Docker daemon at {self.dockerSocket}: {exc}"
            tmpLog.error(err)
            return False, [(WorkSpec.ST_failed, err)] * len(workspec_list)

        retList = []
        for workSpec in workspec_list:
            wLog = self.make_logger(baseLogger, f"workerID={workSpec.workerID}", method_name="check_workers")
            if not workSpec.batchID:
                wLog.warning("no batchID set, marking failed")
                retList.append((WorkSpec.ST_failed, "no batchID"))
                continue
            try:
                container = client.containers.get(workSpec.batchID)
                container.reload()
                c_status = container.status          # "created", "running", "paused", "exited", "dead"
                exit_code = container.attrs["State"].get("ExitCode", -1)
                wLog.debug(f"container status={c_status} exit_code={exit_code}")

                if c_status in ("created", "running"):
                    new_status = WorkSpec.ST_running
                elif c_status == "exited":
                    if exit_code == 0:
                        new_status = WorkSpec.ST_finished
                        workSpec.nativeExitCode = 0
                        workSpec.nativeStatus = "exited(0)"
                    else:
                        new_status = WorkSpec.ST_failed
                        workSpec.nativeExitCode = exit_code
                        workSpec.nativeStatus = f"exited({exit_code})"
                else:
                    new_status = WorkSpec.ST_failed
                    workSpec.nativeStatus = c_status

                retList.append((new_status, ""))
            except docker_module.errors.NotFound:
                wLog.warning(f"container {workSpec.batchID[:12]} not found — treating as failed (container disappeared unexpectedly)")
                retList.append((WorkSpec.ST_failed, "container not found"))
            except Exception as exc:
                err = f"Error checking container {workSpec.batchID[:12]}: {exc}"
                wLog.error(err)
                retList.append((WorkSpec.ST_failed, err))

        try:
            client.close()
        except Exception:
            pass

        tmpLog.debug("done")
        return True, retList
