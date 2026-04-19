"""
subprocess_monitor.py — Harvester monitor plugin for workers launched by
subprocess_submitter.  Checks whether the worker PID is still alive and whether
jobReport.json has been written to the accessPoint.

Configuration in panda_queues.cfg::

    "monitor": {
        "name": "SubprocessMonitor",
        "module": "subprocess_monitor"
    }
"""

import json
import os

from pandaharvester.harvestercore import core_utils
from pandaharvester.harvestercore.plugin_base import PluginBase
from pandaharvester.harvestercore.work_spec import WorkSpec

baseLogger = core_utils.setup_logger("subprocess_monitor")


def _pid_alive(pid):
    """Return True if the process with *pid* is still running."""
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError, ValueError):
        return False


class SubprocessMonitor(PluginBase):
    def __init__(self, **kwarg):
        PluginBase.__init__(self, **kwarg)

    def check_workers(self, workspec_list):
        tmpLog = self.make_logger(baseLogger, method_name="check_workers")
        tmpLog.debug(f"start nWorkers={len(workspec_list)}")
        retList = []
        for workSpec in workspec_list:
            tmpLog2 = self.make_logger(baseLogger, f"workerID={workSpec.workerID}", method_name="check_workers")
            accessPoint = workSpec.get_access_point()
            reportPath = os.path.join(accessPoint, "jobReport.json")
            if os.path.exists(reportPath):
                try:
                    with open(reportPath) as f:
                        report = json.load(f)
                    exitCode = report.get("exitCode", 1)
                    workSpec.nativeExitCode = exitCode
                    workSpec.nativeStatus = "done"
                    newStatus = WorkSpec.ST_finished if exitCode == 0 else WorkSpec.ST_failed
                except Exception as exc:
                    tmpLog2.warning(f"failed to read {reportPath}: {exc}")
                    newStatus = WorkSpec.ST_failed
            elif workSpec.batchID and _pid_alive(workSpec.batchID):
                newStatus = WorkSpec.ST_running
            else:
                newStatus = WorkSpec.ST_failed
            tmpLog2.debug(f"batchID={workSpec.batchID} newStatus={newStatus}")
            retList.append((newStatus, ""))
        tmpLog.debug("done")
        return True, retList
