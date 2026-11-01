"""SQLite job persistence, atomic scheduling claims, and execution journals."""
import json
import os
import sys
import sqlite3
from contextlib import closing, contextmanager
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
  resume_index INTEGER NOT NULL DEFAULT 0,
  resumed_from INTEGER,
  plan_hash TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS execution_checkpoints (
  execution_id INTEGER PRIMARY KEY,
  completed INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS file_watch_state (
  job_id INTEGER PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS debug_controls (
  execution_id INTEGER PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 0,
  mode TEXT NOT NULL DEFAULT 'run',
  state TEXT NOT NULL DEFAULT 'idle',
  step_index INTEGER NOT NULL DEFAULT 0,
  break_on_failure INTEGER NOT NULL DEFAULT 0,
  snapshots INTEGER NOT NULL DEFAULT 0,
  last_error TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS debug_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_id INTEGER NOT NULL,
  step_index INTEGER NOT NULL,
  phase TEXT NOT NULL,
  path TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_debug_artifacts_run ON debug_artifacts(execution_id, id);
CREATE TABLE IF NOT EXISTS debug_corrections (
  execution_id INTEGER NOT NULL,
  step_index INTEGER NOT NULL,
  params_json TEXT NOT NULL,
  PRIMARY KEY(execution_id, step_index),
  FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
);
"""


class Store:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or data_root() / "tasks.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # WAL is a database-wide persistent setting. Configure it once per
        # Store instance rather than acquiring a journal-mode lock for every
        # UI read, scheduler poll, and workflow event.
        with closing(sqlite3.connect(self.db_path, timeout=20)) as initial:
            initial.execute("PRAGMA busy_timeout=20000")
            initial.execute("PRAGMA journal_mode=WAL")
        with self.connection() as db:
            db.executescript(SCHEMA)
            columns={r[1] for r in db.execute("PRAGMA table_info(executions)")}
            if "runner_pid" not in columns:
                db.execute("ALTER TABLE executions ADD COLUMN runner_pid INTEGER")
            for name,definition in (('resume_index','INTEGER NOT NULL DEFAULT 0'),
                                    ('resumed_from','INTEGER'),('plan_hash',"TEXT NOT NULL DEFAULT ''")):
                if name not in columns:
                    db.execute(f'ALTER TABLE executions ADD COLUMN {name} {definition}')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
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
            # SQLite connection context managers commit/rollback but DO NOT
            # close their handles. Windows refuses to rename a live SQLite file;
            # explicitly closing both connections releases the staged backup.
            with closing(sqlite3.connect(self.db_path, timeout=20)) as source:
                with closing(sqlite3.connect(staged)) as backup:
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

    def claim_file_events(self):
        """Atomically claim changed watched files without duplicate worker runs.

        Uses a durable first-observation baseline. A change while another run
        remains active is left pending, rather than silently discarded.
        """
        from .file_events import fingerprint, event_between
        claimed=[]
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            jobs=[self.decode(row) for row in db.execute(
                "SELECT * FROM jobs WHERE enabled=1 AND schedule_kind='file_event' ORDER BY id")]
            for job in jobs:
                config=job['schedule']
                current=fingerprint(config['path'])
                baseline=db.execute('SELECT fingerprint FROM file_watch_state WHERE job_id=?',
                                    (job['id'],)).fetchone()
                if baseline is None:
                    db.execute('INSERT INTO file_watch_state(job_id,fingerprint) VALUES(?,?)',
                               (job['id'],current))
                    continue
                detected=event_between(baseline['fingerprint'],current)
                if not detected:
                    continue
                event=config.get('event','modified')
                if event not in ('any',detected):
                    db.execute('UPDATE file_watch_state SET fingerprint=? WHERE job_id=?',
                               (current,job['id']))
                    continue
                if job['status']=='running':
                    continue
                now=utc_text(utc_now())
                db.execute("UPDATE jobs SET status='running',last_run=?,last_error=NULL WHERE id=?",
                           (now,job['id']))
                execution=db.execute("INSERT INTO executions(job_id,started_at,status) VALUES(?,?,'running')",
                                     (job['id'],now))
                db.execute('UPDATE file_watch_state SET fingerprint=? WHERE job_id=?',
                           (current,job['id']))
                claimed.append((job['id'],execution.lastrowid))
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

    def execution_plan(self, execution_id: int, actions):
        from .recovery import plan_hash
        digest=plan_hash(actions)
        with self.connection() as db:
            row=db.execute('SELECT plan_hash FROM executions WHERE id=?',(execution_id,)).fetchone()
            if row is None:raise LookupError('Execution is missing')
            if row['plan_hash'] and row['plan_hash']!=digest:
                raise RuntimeError('The current workflow differs from the resume checkpoint plan')
            db.execute('UPDATE executions SET plan_hash=? WHERE id=?',(digest,execution_id))
        return digest

    def execution_checkpoint(self, execution_id: int, completed: int):
        with self.connection() as db:
            db.execute("""INSERT INTO execution_checkpoints(execution_id,completed,updated_at)
                         VALUES(?,?,?) ON CONFLICT(execution_id) DO UPDATE SET
                         completed=excluded.completed,updated_at=excluded.updated_at""",
                       (execution_id,int(completed),utc_text(utc_now())))

    def checkpoint_for(self, execution_id: int):
        with self.connection() as db:
            row=db.execute('SELECT * FROM execution_checkpoints WHERE execution_id=?',(execution_id,)).fetchone()
            return dict(row) if row else None

    def claim_resume(self, previous_execution_id: int):
        from .recovery import validate_resume
        previous=self.execution_by_id(previous_execution_id)
        if previous is None or previous['status'] not in ('failed','cancelled'):
            raise ValueError('A failed/cancelled execution is required for checkpoint continuation')
        checkpoint=self.checkpoint_for(previous_execution_id)
        if checkpoint is None or not previous['plan_hash']:
            raise ValueError('The selected execution has no verified checkpoint')
        job=self.get_job(previous['job_id'])
        if job is None:raise LookupError('Task was deleted')
        validate_resume(job['actions'],checkpoint['completed'])
        if previous['plan_hash']!=__import__('task_runner.recovery',fromlist=['plan_hash']).plan_hash(job['actions']):
            raise ValueError('Task changed since the failed run; refusing to resume')
        new_id=self.claim(job['id'],force=True)
        if new_id is None:raise RuntimeError('Task is already running')
        with self.connection() as db:
            db.execute('UPDATE executions SET resume_index=?,resumed_from=?,plan_hash=? WHERE id=?',
                       (checkpoint['completed'],previous_execution_id,previous['plan_hash'],new_id))
        return job['id'],new_id

    def execution_by_id(self, execution_id: int):
        with self.connection() as db:
            row=db.execute('SELECT * FROM executions WHERE id=?',(execution_id,)).fetchone()
            return dict(row) if row else None

    def debug_enable(self, execution_id: int, paused: bool = True,
                     break_on_failure: bool = True, snapshots: bool = True):
        with self.connection() as db:
            row=db.execute("SELECT status FROM executions WHERE id=?",(execution_id,)).fetchone()
            if row is None or row['status']!='running':
                raise RuntimeError('Cannot debug an execution that is not running')
            db.execute("""INSERT INTO debug_controls(execution_id,enabled,mode,state,step_index,
                         break_on_failure,snapshots,updated_at) VALUES(?,1,?,'pending',0,?,?,?)
                         ON CONFLICT(execution_id) DO UPDATE SET enabled=1,mode=excluded.mode,
                         break_on_failure=excluded.break_on_failure,snapshots=excluded.snapshots,
                         updated_at=excluded.updated_at""",
                       (execution_id,'pause' if paused else 'run',int(break_on_failure),int(snapshots),utc_text(utc_now())))

    def debug_status(self, execution_id: int):
        with self.connection() as db:
            row=db.execute('SELECT * FROM debug_controls WHERE execution_id=?',(execution_id,)).fetchone()
            return dict(row) if row else None

    def debug_command(self, execution_id: int, command: str):
        if command not in ('run','pause','step','retry','cancel'):
            raise ValueError('Unrecognized debugger command')
        with self.connection() as db:
            row=db.execute('SELECT enabled,state,mode FROM debug_controls WHERE execution_id=?',(execution_id,)).fetchone()
            if row is None or not row['enabled']:
                raise RuntimeError('Debugger is not enabled for this execution')
            if command=='retry' and row['state']!='failed_paused':
                raise RuntimeError('Retry is only available after a failed step')
            if command=='step' and row['state'] not in ('pending','paused','completed_step','idle'):
                raise RuntimeError('Single step requires a paused workflow')
            db.execute('UPDATE debug_controls SET mode=?,updated_at=? WHERE execution_id=?',
                       (command,utc_text(utc_now()),execution_id))

    def debug_consume_step(self, execution_id: int) -> bool:
        with self.connection() as db:
            result=db.execute("UPDATE debug_controls SET mode='pause' WHERE execution_id=? AND mode='step'",(execution_id,))
            return bool(result.rowcount)

    def debug_consume_retry(self, execution_id: int) -> bool:
        with self.connection() as db:
            result=db.execute("UPDATE debug_controls SET mode='pause' WHERE execution_id=? AND mode='retry'",(execution_id,))
            return bool(result.rowcount)

    def debug_state(self, execution_id: int, state: str, step_index: int, error: str):
        with self.connection() as db:
            db.execute('UPDATE debug_controls SET state=?,step_index=?,last_error=?,updated_at=? WHERE execution_id=?',
                       (state,int(step_index),str(error),utc_text(utc_now()),execution_id))

    def debug_artifact(self, execution_id: int, step_index: int, phase: str, path: str):
        with self.connection() as db:
            db.execute('INSERT INTO debug_artifacts(execution_id,step_index,phase,path,recorded_at) VALUES(?,?,?,?,?)',
                       (execution_id,step_index,phase,str(path),utc_text(utc_now())))

    def debug_artifacts_for(self, execution_id: int):
        with self.connection() as db:
            return [dict(x) for x in db.execute('SELECT * FROM debug_artifacts WHERE execution_id=? ORDER BY id',
                                                 (execution_id,))]

    def correction_for(self, execution_id: int, step_index: int):
        with self.connection() as db:
            row=db.execute('SELECT params_json FROM debug_corrections WHERE execution_id=? AND step_index=?',
                           (execution_id,step_index)).fetchone()
            return json.loads(row['params_json']) if row else None

    def teach_click(self, execution_id: int, step_index: int, params: dict):
        """Persist a target correction for both this run and future replays.

        Reject editing an already completed step or any non-click action.
        """
        from .flow import validate_workflow
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            session=db.execute('SELECT state,step_index FROM debug_controls WHERE execution_id=? AND enabled=1',
                               (execution_id,)).fetchone()
            run=db.execute('SELECT job_id,status FROM executions WHERE id=?',(execution_id,)).fetchone()
            if not session or not run or run['status']!='running' or session['state'] not in ('paused','failed_paused'):
                raise RuntimeError('Pause a running debugger before teaching a target')
            if session['step_index']!=step_index or step_index<1:
                raise RuntimeError('Selected correction must match the paused workflow step')
            job=db.execute('SELECT actions_json FROM jobs WHERE id=?',(run['job_id'],)).fetchone()
            if not job:raise LookupError('Task not found')
            actions=json.loads(job['actions_json'])
            if step_index>len(actions) or actions[step_index-1]['type']!='click':
                raise ValueError('Only click steps can be re-taught')
            allowed={'x','y','window_title','window_rx','window_ry','control_name','automation_id',
                     'reference_image','confidence','allow_relative_fallback','strict_target','target_timeout'}
            patch={k:v for k,v in params.items() if k in allowed}
            if 'x' not in patch or 'y' not in patch:
                raise ValueError('A corrected click requires X and Y')
            updated=dict(actions[step_index-1]['params'])
            updated.update(patch)
            actions[step_index-1]['params']=updated
            validate_workflow(actions)
            db.execute('UPDATE jobs SET actions_json=?,updated_at=? WHERE id=?',
                       (json.dumps(actions,ensure_ascii=False),utc_text(utc_now()),run['job_id']))
            db.execute('INSERT INTO debug_corrections(execution_id,step_index,params_json) VALUES(?,?,?) '
                       'ON CONFLICT(execution_id,step_index) DO UPDATE SET params_json=excluded.params_json',
                       (execution_id,step_index,json.dumps(updated,ensure_ascii=False)))

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
