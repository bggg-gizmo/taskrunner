"""Nonblocking dashboard snapshot collection; Qt widgets are never touched by workers.

The scheduler and the automation executors can hold SQLite locks while they
update run records. Automatic dashboard updates must not wait for a database
busy timeout or reconstruct widgets on the Qt event-loop thread.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DashboardSnapshot:
    generation: int
    jobs: list[dict[str, Any]]
    history: list[dict[str, Any]]
    error: str | None = None


class DashboardSnapshotReader:
    """A single daemon reader with a bounded pending-result queue.

    A generation fences off snapshots that started before a user-created,
    edited, or deleted task was committed and refreshed synchronously.
    """
    def __init__(self, store):
        self.store = store
        self._working = threading.Lock()
        self._completed: queue.Queue[DashboardSnapshot] = queue.Queue(maxsize=1)

    def start(self, generation: int) -> bool:
        if not self._working.acquire(blocking=False):
            return False
        try:
            thread = threading.Thread(target=self._read, args=(generation,),
                                      name="taskrunner-dashboard-snapshot", daemon=True)
            thread.start()
        except BaseException:
            self._working.release()
            raise
        return True

    def _read(self, generation: int) -> None:
        try:
            jobs = self.store.all_jobs()
            history = self.store.execution_history(limit=200)
            snapshot = DashboardSnapshot(generation, jobs, history)
        except Exception as error:
            snapshot = DashboardSnapshot(generation, [], [],
                                         f"{type(error).__name__}: {error}")
        # Never accumulate stale snapshots when the event loop is busy or a
        # modal wizard is open. A newer sample supersedes an older one.
        try:
            try:
                self._completed.put_nowait(snapshot)
            except queue.Full:
                try:
                    self._completed.get_nowait()
                except queue.Empty:
                    pass
                self._completed.put_nowait(snapshot)
        finally:
            # Release only after the result is queued, so a newer read cannot
            # finish and then be overwritten by an older, delayed producer.
            self._working.release()

    def take_latest(self) -> DashboardSnapshot | None:
        latest = None
        while True:
            try:
                latest = self._completed.get_nowait()
            except queue.Empty:
                return latest
