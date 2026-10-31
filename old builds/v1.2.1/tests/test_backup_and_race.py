import sqlite3
from pathlib import Path
import pytest
from task_runner.store import Store
from task_runner.actions import default_step


def test_backup_preserves_jobs_and_event_history(tmp_path):
    store = Store(tmp_path/'live.sqlite3')
    job = store.save_job({'name':'Recover me','actions':[default_step('wait')]})
    run = store.claim(job, force=True)
    store.event(run, 'INFO', 'Saved log event', 1)
    dest = store.backup_database(tmp_path/'backups'/'saved.sqlite3')
    with sqlite3.connect(dest) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    restored = Store(dest)
    assert restored.get_job(job)['name'] == 'Recover me'
    assert restored.events_for(run)[0]['message'] == 'Saved log event'
    store.finish(job, run, 'success', 'finished')
    # Backup is a snapshot and does not change when the original database does.
    assert restored.execution_history(job)[0]['status'] == 'running'


def test_backup_cannot_overwrite_live_database(tmp_path):
    store=Store(tmp_path/'live.sqlite3')
    with pytest.raises(ValueError):
        store.backup_database(store.db_path)


def test_late_worker_completion_does_not_overwrite_recovery_or_new_run(tmp_path):
    store = Store(tmp_path/'live.sqlite3')
    job = store.save_job({'name':'Race','actions':[default_step('wait')]})
    old_run = store.claim(job, force=True)
    with store.connection() as db:
        db.execute("UPDATE executions SET status='failed' WHERE id=?",(old_run,))
        db.execute("UPDATE jobs SET status='failed' WHERE id=?",(job,))
    active = store.claim(job, force=True)
    store.finish(job, old_run, 'success', 'late')
    assert store.get_job(job)['status'] == 'running'
    assert store.running_execution(job) == active
    store.finish(job, active, 'success', 'completed')
    assert store.get_job(job)['status'] == 'success'
