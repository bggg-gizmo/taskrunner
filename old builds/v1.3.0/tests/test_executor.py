import pytest
from task_runner.actions import default_step, ACTIONS
from task_runner.store import Store
from task_runner.executor import WorkflowEngine


def step(action_type,**kwargs):
    out=default_step(action_type)
    out["params"].update(kwargs)
    return out


def test_file_actions_variables_beautiful_soup(tmp_path):
    s=Store(tmp_path/"data.db")
    output=tmp_path/"result.txt"
    html='<html><body><div class="result" data-code="ok">Success!</div></body></html>'
    actions=[step("set_var",name="html",value=html),
             step("soup_select",source="html",selector=".result",attribute="data-code",name="answer"),
             step("write_file",path=str(output),text="status=${answer}"),
             step("read_file",path=str(output),name="from_disk")]
    actions[2]["verify"]={"kind":"file_exists","target":str(output),"timeout":1.0}
    job=s.save_job({"name":"Offline parse and file workflow","actions":actions,"schedule_kind":"manual","schedule":{}})
    execution_id=s.claim(job,force=True)
    engine=WorkflowEngine(s)
    assert engine.execute(job,execution_id)=="success"
    assert output.read_text()=="status=ok"
    assert engine.vars["from_disk"]=="status=ok"
    assert len(s.events_for(execution_id))>=len(actions)*2


def test_failed_verification_marks_run_failed(tmp_path):
    store=Store(tmp_path/"data.db")
    s=step("wait",seconds=0)
    s["verify"]={"kind":"file_exists","target":str(tmp_path/"nonexistent.file"),"timeout":0}
    job=store.save_job({"name":"Check failed condition","actions":[s]})
    execution=store.claim(job,force=True)
    assert WorkflowEngine(store).execute(job,execution)=="failed"
    assert store.get_job(job)["status"]=="failed"


def test_cancelled_workflow(tmp_path):
    store=Store(tmp_path/"data.db")
    job=store.save_job({"name":"Stop test","actions":[step("wait",seconds=0.1)]})
    execution=store.claim(job,force=True)
    assert WorkflowEngine(store,should_stop=lambda:True).execute(job,execution)=="cancelled"


def test_action_catalog_has_nonempty_names():
    assert len(ACTIONS)>=25
    assert all(action.name and action.category for action in ACTIONS.values())
