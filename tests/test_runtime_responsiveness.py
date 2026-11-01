"""Database and application responsiveness regression checks."""
from concurrent.futures import ThreadPoolExecutor

from task_runner.actions import default_step
from task_runner.store import Store


def test_repeated_read_connections_preserve_wal_and_existing_jobs(tmp_path):
    store=Store(tmp_path/'tasks.sqlite3')
    job_id=store.save_job({'name':'Unchanged task', 'actions':[default_step('wait')]})
    for i in range(50):
        assert store.get_job(job_id)['name']=='Unchanged task'
        with store.connection() as conn:
            assert conn.execute('PRAGMA journal_mode').fetchone()[0].lower()=='wal'
    assert store.all_jobs()[0]['id']==job_id


def test_simultaneous_scheduler_reads_and_task_edit_without_lost_data(tmp_path):
    store=Store(tmp_path/'tasks.sqlite3')
    job_id=store.save_job({'name':'Concurrent task','actions':[default_step('wait')]})
    def reader():
        for _ in range(35):
            assert store.get_job(job_id)['id']==job_id
            assert store.claim_due()==[]
            assert store.claim_file_events()==[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        future=pool.submit(reader)
        for number in range(8):
            saved=store.get_job(job_id)
            saved['description']=f'Edited {number}'
            store.save_job(saved)
        future.result(timeout=20)
    assert store.get_job(job_id)['description']=='Edited 7'
