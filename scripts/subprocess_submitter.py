"""
subprocess_submitter.py — Harvester submitter plugin that executes workers as
local subprocesses.  Intended for the panda-compose dev stack where a real
batch system is not available.

Configuration in panda_queues.cfg::

    "submitter": {
        "name": "SubprocessSubmitter",
        "module": "subprocess_submitter",
        "workerScript": "/harvester/panda-worker.sh",
        "workDir": "/harvester/workers"
    }
"""

import os
import subprocess

from pandaharvester.harvestercore import core_utils
from pandaharvester.harvestercore.plugin_base import PluginBase
from pandaharvester.harvestercore.work_spec import WorkSpec

baseLogger = core_utils.setup_logger("subprocess_submitter")


class SubprocessSubmitter(PluginBase):
    def __init__(self, **kwarg):
        # workerScript and workDir are injected from panda_queues.cfg.
        self.workerScript = "/harvester/panda-worker.sh"
        self.workDir = "/harvester/workers"
        PluginBase.__init__(self, **kwarg)

    def submit_workers(self, workspec_list):
        tmpLog = self.make_logger(baseLogger, method_name="submit_workers")
        tmpLog.debug(f"start nWorkers={len(workspec_list)}")
        retList = []
        for workSpec in workspec_list:
            accessPoint = workSpec.get_access_point()
            os.makedirs(accessPoint, exist_ok=True)
            pidFile = os.path.join(accessPoint, "worker.pid")
            logFile = os.path.join(accessPoint, "worker.log")
            try:
                with open(logFile, "w") as lf:
                    proc = subprocess.Popen(
                        ["/bin/bash", self.workerScript, accessPoint],
                        stdout=lf,
                        stderr=subprocess.STDOUT,
                        close_fds=True,
                    )
                with open(pidFile, "w") as pf:
                    pf.write(str(proc.pid))
                workSpec.batchID = str(proc.pid)
                workSpec.set_log_file("batch_log", f"file://{logFile}")
                tmpLog.debug(f"launched PID={proc.pid} accessPoint={accessPoint}")
                retList.append((True, ""))
            except Exception as exc:
                tmpLog.error(f"failed to launch worker: {exc}")
                retList.append((False, str(exc)))
        tmpLog.debug("done")
        return retList
