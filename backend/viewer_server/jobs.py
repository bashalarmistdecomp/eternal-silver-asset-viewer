"""Long-running work, run on a thread, polled by the UI for progress.

Extracting a disc takes long enough that a request would time out
waiting on it. It becomes a Job: the request that starts it returns at
once with the job's id, and the UI polls `/api/jobs/<id>` until it is
done. A job may go on to a later `stage` (an extraction to indexing the
disc, viewer_server.index) after it has let go of what it held alone.
"""

from __future__ import annotations

import secrets
import threading
import time
import traceback
from typing import Any, Callable


class Job:
    def __init__(self, kind: str):
        self.id = secrets.token_hex(6)
        self.kind = kind
        self.state = "running"          # running | done | error
        self.message = ""
        self.current = 0
        self.total = 0
        self.result: Any = None
        self.error = ""
        self.started = time.monotonic()
        #: what it is doing now, where it goes on past its first part ("index")
        self.stage = ""
        #: running alone (Jobs.start), until it lets go
        self.alone = False

    def progress(self, message: str, current: int = 0, total: int = 0):
        self.message, self.current, self.total = message, current, total

    def let_go(self, stage: str):
        """Go on to `stage`, no longer alone: another job of the kind may
        start meanwhile."""
        self.stage, self.alone = stage, False

    def describe(self) -> dict:
        return {"id": self.id, "kind": self.kind, "state": self.state,
                "stage": self.stage,
                "message": self.message, "current": self.current,
                "total": self.total, "result": self.result,
                "error": self.error,
                "seconds": round(time.monotonic() - self.started, 1)}


class Busy(Exception):
    """A job of the kind is running already, and runs alone."""


class Jobs:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, work: Callable[[Job], Any],
              alone: bool = False) -> Job:
        """Run `work(job)` on a thread. `alone`: raise Busy instead while
        another job of `kind` is running alone (until it lets go)."""
        job = Job(kind)
        with self._lock:
            if alone and any(j.kind == kind and j.state == "running" and j.alone
                             for j in self._jobs.values()):
                raise Busy(kind)
            job.alone = alone
            self._jobs[job.id] = job

        def run():
            try:
                job.result = work(job)
                job.state = "done"
            except Exception as exc:        # reported to the UI, verbatim
                traceback.print_exc()
                job.error = str(exc) or exc.__class__.__name__
                job.state = "error"

        threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)
