"""Pure workflow validation and deeply nested control flow regression tests."""
import pytest
from task_runner.actions import default_step
from task_runner.flow import compile_flow,condition,validate_workflow
from task_runner.store import Store
from task_runner.executor import WorkflowEngine


def step(kind,**params):
    doc=default_step(kind)
    doc["params"].update(params)
    return doc


def execute(tmp_path,actions):
    store=Store(tmp_path/"runner.sqlite3")
    job_id=store.save_job({"name":"Branch integration","actions":actions})
    run_id=store.claim(job_id,force=True)
    engine=WorkflowEngine(store)
    result=engine.execute(job_id,run_id)
    return result,engine,store,run_id


def test_if_true_skips_else(tmp_path):
    actions=[step("set_var",name="mode",value="active"),
             step("if_var",name="mode",operator="equals",value="active"),
             step("set_var",name="result",value="correct"),
             step("else"),step("set_var",name="result",value="wrong"),step("endif")]
    result,engine,*_=execute(tmp_path,actions)
    assert result=="success"
    assert engine.vars["result"]=="correct"


def test_if_false_uses_else(tmp_path):
    actions=[step("set_var",name="mode",value="inactive"),
             step("if_var",name="mode",operator="equals",value="active"),
             step("set_var",name="result",value="wrong"),
             step("else"),step("set_var",name="result",value="correct"),step("endif")]
    result,engine,*_=execute(tmp_path,actions)
    assert result=="success" and engine.vars["result"]=="correct"


def test_nested_conditions(tmp_path):
    actions=[step("set_var",name="active",value="yes"),
             step("if_var",name="active",operator="equals",value="yes"),
             step("if_var",name="active",operator="not empty"),
             step("set_var",name="out",value="nested"),
             step("endif"),step("endif")]
    assert execute(tmp_path,actions)[1].vars["out"]=="nested"


def test_repeat_runs_exact_times(tmp_path):
    actions=[step("repeat",times=4),step("set_var",name="latest",value="${loop_iteration}"),
             step("write_file",path=str(tmp_path/"numbers.txt"),text="${loop_iteration}\n",append=True),
             step("end_repeat")]
    result,engine,*_=execute(tmp_path,actions)
    assert result=="success" and engine.vars["latest"]=="4"
    assert (tmp_path/"numbers.txt").read_text()=="1\n2\n3\n4\n"


def test_repeat_zero_runs_nothing(tmp_path):
    result,engine,*_=execute(tmp_path,[step("repeat",times=0),step("set_var",name="oops",value="oops"),step("end_repeat")])
    assert result=="success" and "oops" not in engine.vars


def test_break_and_continue(tmp_path):
    actions=[step("repeat",times=8),step("if_var",name="loop_iteration",operator="equals",value="3"),
             step("break_loop"),step("endif"),
             step("write_file",path=str(tmp_path/"lines.txt"),text="${loop_iteration}\n",append=True),
             step("continue_loop"),step("end_repeat")]
    result,engine,*_=execute(tmp_path,actions)
    assert result=="success"
    assert (tmp_path/"lines.txt").read_text()=="1\n2\n"


def test_file_operations(tmp_path):
    src=tmp_path/"source.txt"
    dst=tmp_path/"destination"/"moved.txt"
    final=tmp_path/"destination"/"copied.txt"
    actions=[step("write_file",path=str(src),text="full content"),
             step("mkdir",path=str(dst.parent)),
             step("move_file",source=str(src),destination=str(dst)),
             step("copy_file",source=str(dst),destination=str(final)),
             step("list_dir",path=str(dst.parent),name="listing"),
             step("delete_file",path=str(dst))]
    result,engine,*_=execute(tmp_path,actions)
    assert result=="success"
    assert final.read_text()=="full content"
    assert not src.exists() and not dst.exists()
    assert engine.vars["listing"]=="copied.txt\nmoved.txt"


def test_file_copy_collision_preserves_existing(tmp_path):
    a=tmp_path/"a.txt";b=tmp_path/"b.txt";a.write_text("new");b.write_text("old")
    result,_,store,run=execute(tmp_path,[step("copy_file",source=str(a),destination=str(b))])
    assert result=="failed" and b.read_text()=="old"
    assert "FileExistsError" in store.execution_history()[0]["message"]


def test_preflight_rejects_unknown_step_without_side_effect(tmp_path):
    source=tmp_path/"should-not-exist.txt"
    actions=[step("write_file",path=str(source),text="no"),step("else")]
    with pytest.raises(ValueError,match="Else"):
        execute(tmp_path,actions)
    assert not source.exists()


@pytest.mark.parametrize("types",[
    ["if_var"],["else"],["endif"],["repeat"],["end_repeat"],["break_loop"],["continue_loop"],
    ["if_var","else","else","endif"],["if_var","end_repeat"],
    ["repeat","endif"],
])
def test_invalid_blocks(types):
    with pytest.raises(ValueError):compile_flow([step(code) for code in types])


def test_validation_required_field_and_out_of_range():
    with pytest.raises(ValueError,match="URL is required"):
        validate_workflow([step("http_get",url="")])
    with pytest.raises(ValueError,match="repeat count"):
        validate_workflow([step("repeat",times=-1),step("end_repeat")])
    broken=step("wait",seconds=1)
    broken["verify"]={"kind":"file_exists","target":"","timeout":3}
    with pytest.raises(ValueError,match="verification target"):
        validate_workflow([broken])


def test_conditions():
    assert condition("hello world","contains","world")
    assert condition("hello world","regex matches",r"h.*d")
    assert not condition("hello world","empty","")
    with pytest.raises(ValueError):condition("a","unknown","a")
