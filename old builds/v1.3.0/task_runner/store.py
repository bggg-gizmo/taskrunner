"""SQLite job persistence, atomic scheduling claims, and execution journals."""
import json
import os
import sys
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from .paths import data_root
from .scheduling import compute_next, parse_utc, utc_now, utc_text
from .flow import validate_workflow

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  schedule_kind TEXT NOT NULL DEFAULT 'manual', schedule_json TEXT NOT NULL DEFAULT '{}',
  actions_json TEXT NOT NULL DEFAULT '[]', next_run TEXT,
  last_run TEXT, status TEXT NOT NULL DEFAULT 'idle', last_error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS executions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
  runner_pid INTEGER,
  FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, execution_id INTEGER NOT NULL,
  recorded_at TEXT NOT NULL, step_index INTEGER,
  level TEXT NOT NULL, message TEXT NOT NULL,
  FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_jobs_due ON jobs(enabled, next_run);
CREATE INDEX IF NOT EXISTS idx_events_execution ON events(execution_id, id);
"""


class Store:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or data_root() / "tasks.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)
            columns={r[1] for r in db.execute("PRAGMA table_info(executions)")}
            if "runner_pid" not in columns:
                db.execute("ALTER TABLE executions ADD COLUMN runner_pid INTEGER")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=20000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def backup_database(self, destination: Path) -> Path:
        """Create a consistent SQLite backup even while the WAL database is active."""
        from tempfile import mkstemp
        destination = Path(destination).expanduser().resolve()
        if destination == self.db_path.resolve():
            raise ValueError("Backup destination must differ from the live database")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, staged = mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(fd)
        staged = Path(staged)
        try:
            with sqlite3.connect(self.db_path, timeout=20) as source:
                with sqlite3.connect(staged) as backup:
                    source.backup(backup)
                    if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise RuntimeError("SQLite backup integrity check failed")
            os.replace(staged, destination)
            return destination
        finally:
            staged.unlink(missing_ok=True)

    @staticmethod
    def decode(row):
        if row is None:
            return None
        obj = dict(row)
        if "schedule_json" in obj:
            obj["schedule"] = json.loads(obj.pop("schedule_json"))
        if "actions_json" in obj:
            obj["actions"] = json.loads(obj.pop("actions_json"))
        return obj

    def all_jobs(self):
        with self.connection() as db:
            return [self.decode(r) for r in db.execute("SELECT * FROM jobs ORDER BY id DESC")]

    def get_job(self, job_id: int):
        with self.connection() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def save_job(self, doc: dict) -> int:
        name = str(doc["name"]).strip()
        if not name:
            raise ValueError("Task name is required")
        actions = doc.get("actions", [])
        validate_workflow(actions)
        kind = doc.get("schedule_kind", "manual")
        config = doc.get("schedule", {})
        enabled = int(bool(doc.get("enabled", True)))
        next_run = utc_text(compute_next(kind, config)) if enabled else None
        now = utc_text(utc_now())
        values = (name, str(doc.get("description", "")), enabled, kind,
                  json.dumps(config, ensure_ascii=False), json.dumps(actions, ensure_ascii=False),
                  next_run, now)
        with self.connection() as db:
            if doc.get("id"):
                old = db.execute("SELECT id,status FROM jobs WHERE id=?", (doc["id"],)).fetchone()
                if not old:
                    raise KeyError(f"Task {doc['id']} no longer exists")
                if old["status"] == "running":
                    raise RuntimeError("Stop the running task before editing it")
                db.execute("""UPDATE jobs SET name=?, description=?, enabled=?, schedule_kind=?,
                           schedule_json=?, actions_json=?, next_run=?, updated_at=?,
                           status='idle', last_error=NULL WHERE id=?""", values + (doc["id"],))
                return int(doc["id"])
            cursor = db.execute("""INSERT INTO jobs (name,description,enabled,schedule_kind,
                          schedule_json,actions_json,next_run,updated_at,created_at)
                          VALUES (?,?,?,?,?,?,?,?,?)""", values + (now,))
            return int(cursor.lastrowid)

    def delete_job(self, job_id: int):
        with self.connection() as db:
            db.execute("DELETE FROM jobs WHERE id=? AND status!='running'", (job_id,))
            if not db.execute("SELECT changes()").fetchone()[0]:
                raise RuntimeError("Cannot delete a running or nonexistent task")

    def set_enabled(self, job_id: int, enabled: bool):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            obj = self.decode(row)
            nr = utc_text(compute_next(obj["schedule_kind"], obj["schedule"])) if enabled else None
            db.execute("UPDATE jobs SET enabled=?,next_run=?,updated_at=? WHERE id=?",
                       (int(enabled),nr,utc_text(utc_now()),job_id))

    def clone(self, job_id: int):
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        job.pop("id", None)
        job["name"] += " (copy)"
        job["enabled"] = False
        return self.save_job(job)

    def claim(self, job_id: int, force=False) -> int | None:
        """CAS-style lock: at most one runner can own a task."""
        now = utc_text(utc_now())
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] == "running":
                return None
            if not force and (not row["enabled"] or not row["next_run"] or row["next_run"] > now):
                return None
            doc = self.decode(row)
            nr = utc_text(compute_next(doc["schedule_kind"],doc["schedule"],parse_utc(now))) if doc["enabled"] else None
            db.execute("UPDATE jobs SET status='running',last_run=?,next_run=?,last_error=NULL WHERE id=?",
                       (now,nr,job_id))
            cursor = db.execute("INSERT INTO executions(job_id,started_at,status) VALUES(?,?,'running')",
                                (job_id,now))
            return int(cursor.lastrowid)

    def claim_due(self) -> list[tuple[int,int]]:
        now = utc_text(utc_now())
        with self.connection() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM jobs WHERE enabled=1 AND next_run <= ? AND status!='running' ORDER BY next_run", (now,))]
        claimed = []
        for job_id in ids:
            exec_id = self.claim(job_id)
            if exec_id is not None:
                claimed.append((job_id,exec_id))
        return claimed

    def register_runner(self, execution_id: int, pid: int):
        with self.connection() as db:
            db.execute("UPDATE executions SET runner_pid=? WHERE id=? AND status='running'",(pid,execution_id))

    @staticmethod
    def _pid_alive(pid: int):
        if not pid or pid <= 0:
            return False
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.windll.kernel32
            kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            kernel.OpenProcess.restype=wintypes.HANDLE
            handle=kernel.OpenProcess(0x1000,False,pid)
            if not handle:return False
            result=wintypes.DWORD(0)
            try:
                if not kernel.GetExitCodeProcess(handle,ctypes.byref(result)):
                    return True  # Insufficient rights: avoid falsely reclaiming a live process.
                return result.value == 259
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid,0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def recover_abandoned(self, grace_seconds: int = 300):
        """Mark orphaned executions after their owning Windows process exits.

        Waiting for the grace period avoids racing a newly launched scheduled worker.
        """
        now=utc_now()
        with self.connection() as db:
            running=[dict(r) for r in db.execute("SELECT * FROM executions WHERE status='running'")]
        for run in running:
            started=parse_utc(run["started_at"])
            if not started or (now-started).total_seconds()<grace_seconds:
                continue
            if run.get("runner_pid") and self._pid_alive(int(run["runner_pid"])):
                continue
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                cur=db.execute("UPDATE executions SET status='failed',finished_at=?,message=? WHERE id=? AND status='running'",
                               (utc_text(now),"Worker process exited without recording a result",run["id"]))
                if cur.rowcount:
                    db.execute("UPDATE jobs SET status='failed',last_error=? WHERE id=? AND status='running'",
                               ("Previous worker exited unexpectedly",run["job_id"]))

    def event(self, execution_id: int, level: str, message: str, step_index: int | None = None):
        with self.connection() as db:
            db.execute("INSERT INTO events(execution_id,recorded_at,step_index,level,message) VALUES(?,?,?,?,?)",
                       (execution_id,utc_text(utc_now()),step_index,level,str(message)))

    def finish(self, job_id: int, execution_id: int, status: str, message: str):
        if status not in ("success","failed","cancelled"):
            raise ValueError("Unrecognized execution status")
        with self.connection() as db:
            # An orphaned execution may already have been recovered. Do not let
            # a late worker overwrite the status of a newer active execution.
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("""UPDATE executions SET status=?,finished_at=?,message=?
                                WHERE id=? AND job_id=? AND status='running'""",
                             (status,utc_text(utc_now()),message,execution_id,job_id))
            if changed.rowcount:
                db.execute("UPDATE jobs SET status=?,last_error=? WHERE id=? AND status='running'",
                           (status,message if status != "success" else None,job_id))

    def running_execution(self, job_id: int) -> int | None:
        with self.connection() as db:
            row=db.execute("SELECT id FROM executions WHERE job_id=? AND status='running' ORDER BY id DESC LIMIT 1",(job_id,)).fetchone()
            return int(row["id"]) if row else None

    def execution_history(self, job_id: int | None = None, limit=100):
        with self.connection() as db:
            if job_id is None:
                rows = db.execute("""SELECT e.*, j.name AS job_name FROM executions e
                  JOIN jobs j ON j.id=e.job_id ORDER BY e.id DESC LIMIT ?""",(limit,))
            else:
                rows = db.execute("""SELECT e.*, j.name AS job_name FROM executions e
                  JOIN jobs j ON j.id=e.job_id WHERE e.job_id=? ORDER BY e.id DESC LIMIT ?""",(job_id,limit))
            return [dict(r) for r in rows]

    def events_for(self, execution_id: int):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM events WHERE execution_id=? ORDER BY id",(execution_id,))]
