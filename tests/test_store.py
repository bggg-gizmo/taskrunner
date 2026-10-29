import pytest
from task_runner.store import Store
from task_runner.actions import default_step
from task_runner.scheduling import utc_text,utc_now
from datetime import timedelta

@pytest.fixture()
def store(tmp_path):return Store(tmp_path/"tasks.db")


def create(store,kind="manual",cfg=None):
    return store.save_job({"name":"Sample task","description":"Test persistence",
        "enabled":True,"schedule_kind":kind,"schedule":cfg or {},
        "actions":[default_step("wait")]})


def test_create_edit_duplicate_and_delete(store):
    job_id=create(store)
    job=store.get_job(job_id)
    assert job["name"]=="Sample task"
    assert job["actions"][0]["type"]=="wait"
    job["name"]="Changed name"
    assert store.save_job(job)==job_id
    assert store.get_job(job_id)["name"]=="Changed name"
    copy=store.clone(job_id)
    assert copy!=job_id
    assert store.get_job(copy)["enabled"]==0
    store.delete_job(copy)
    assert store.get_job(copy) is None


def test_claim_is_exclusive_and_logs(store):
    job_id=create(store)
    execution_id=store.claim(job_id,force=True)
    assert execution_id
    assert store.claim(job_id,force=True) is None
    store.event(execution_id,"INFO","Step started",1)
    assert store.events_for(execution_id)[0]["message"]=="Step started"
    assert store.running_execution(job_id)==execution_id
    store.finish(job_id,execution_id,"success","completed")
    assert store.get_job(job_id)["status"]=="success"
    assert store.running_execution(job_id) is None
    assert store.execution_history(job_id)[0]["status"]=="success"


def test_due_jobs_claim_and_schedule_next(store):
    job_id=create(store,"interval",{"seconds":300})
    with store.connection() as db:
        db.execute("UPDATE jobs SET next_run=? WHERE id=?",(utc_text(utc_now()-timedelta(seconds=1)),job_id))
    got=store.claim_due()
    assert len(got)==1
    assert got[0][0]==job_id
    assert store.claim_due()==[]
    assert store.get_job(job_id)["next_run"]>utc_text(utc_now())


def test_disable_clears_due(store):
    job_id=create(store,"interval",{"seconds":60})
    store.set_enabled(job_id,False)
    assert store.get_job(job_id)["next_run"] is None


def test_abandoned_runner_is_recovered(store):
    job_id=create(store)
    run=store.claim(job_id,force=True)
    with store.connection() as db:
        db.execute("UPDATE executions SET started_at=?,runner_pid=? WHERE id=?",
                   (utc_text(utc_now()-timedelta(days=1)),2147483646,run))
    store.recover_abandoned()
    assert store.get_job(job_id)["status"]=="failed"
    assert store.execution_history(job_id)[0]["status"]=="failed"
