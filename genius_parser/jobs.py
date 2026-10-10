"""In-memory background jobs. State lives as long as the server process."""
from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .progress import Cancelled, Reporter

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    kind: str
    params: dict[str, Any]
    title: str = ""
    status: str = "queued"  # queued | running | done | failed | cancelled
    stage: str = ""
    done: int = 0
    total: int = 0
    message: str = ""
    summary: dict[str, Any] | None = None
    error: str | None = None
    logs: deque = field(default_factory=lambda: deque(maxlen=200))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "params": self.params, "title": self.title,
            "status": self.status, "stage": self.stage, "done": self.done, "total": self.total,
            "message": self.message, "summary": self.summary, "error": self.error,
            "logs": list(self.logs), "created_at": self.created_at, "finished_at": self.finished_at,
        }


class JobReporter(Reporter):
    def __init__(self, job: Job) -> None:
        self.job = job

    def _check(self) -> None:
        if self.job.cancel_event.is_set():
            raise Cancelled()

    def set_title(self, title: str) -> None:
        self.job.title = title

    def update(self, stage: str, done: int = 0, total: int = 0, message: str = "") -> None:
        self._check()
        j = self.job
        j.stage, j.done, j.total, j.message = stage, done, total, message

    def log(self, message: str) -> None:
        self.job.logs.append(message)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, params: dict[str, Any], title: str, fn: Callable[[Reporter], dict[str, Any]]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, params=params, title=title)
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, fn), daemon=True, name=f"job-{job.id}").start()
        return job

    def _run(self, job: Job, fn: Callable[[Reporter], dict[str, Any]]) -> None:
        job.status = "running"
        try:
            job.summary = fn(JobReporter(job))
            job.status = "done"
        except Cancelled:
            job.status = "cancelled"
            job.logs.append("Остановлено пользователем")
        except Exception as exc:  # noqa: BLE001 - report any failure on the job itself
            log.exception("job %s failed", job.id)
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def active_for(self, kind: str, params: dict[str, Any]) -> Job | None:
        return next(
            (j for j in self.list() if j.kind == kind and j.params == params and j.status in ("queued", "running")),
            None,
        )

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status not in ("queued", "running"):
            return False
        job.cancel_event.set()
        return True
