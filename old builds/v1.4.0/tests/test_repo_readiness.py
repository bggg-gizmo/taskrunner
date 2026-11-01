import json
from pathlib import Path
from scripts.generate_workflow_schema import generate
from scripts.prepublish_audit import audit
from task_runner.actions import ACTIONS

ROOT=Path(__file__).resolve().parent.parent


def test_schema_remains_synchronized_with_all_actions():
    current=json.loads((ROOT/'schemas'/'taskrunner-job.schema.json').read_text(encoding='utf-8'))
    assert current==generate()
    assert {rule['properties']['type']['const'] for rule in current['properties']['job']['properties']['actions']['items']['oneOf']}==set(ACTIONS)


def test_github_ruleset_is_api_request_and_has_no_status_check_cost_dependency():
    rules=json.loads((ROOT/'.github/rulesets/main-branch-protection.json').read_text())
    assert rules['target']=='branch'
    assert rules['conditions']['ref_name']['include']==['~DEFAULT_BRANCH']
    assert {'deletion','non_fast_forward'}.issubset({r['type'] for r in rules['rules']})
    assert not any(r['type']=='pull_request' for r in rules['rules']), 'Main is direct-commit only'
    assert not any(r['type']=='required_status_checks' for r in rules['rules'])


def test_prepublication_audit_detects_sensitive_material(tmp_path):
    (tmp_path/'tasks.sqlite3').write_bytes(b'sensitive')
    (tmp_path/'.github/workflows').mkdir(parents=True)
    (tmp_path/'.github/workflows/paid.yml').write_text('name: paid\n')
    problems=audit(tmp_path)
    assert any('tasks.sqlite3' in problem for problem in problems)
    assert any('paid.yml' in problem for problem in problems)


def test_repo_package_audits_clean():
    assert audit(ROOT)==[]


def test_export_schema_accepts_current_and_historical_enabled_values():
    import importlib.util
    if importlib.util.find_spec('jsonschema') is None:
        return  # optional audit-only library, not an app dependency
    from jsonschema import Draft202012Validator
    from task_runner.actions import default_step
    from task_runner.store import Store
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as folder:
        store=Store(Path(folder)/'tasks.sqlite3')
        id=store.save_job({'name':'Portable job','actions':[default_step('wait')]})
        task=store.get_job(id)
        exported={'format':'TaskRunnerJob','version':1,
                  'job':{key:task[key] for key in ('name','description','enabled','schedule_kind','schedule','actions')}}
        schema=generate()
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(exported)  # historical integer enabled
        exported['job']['enabled']=bool(exported['job']['enabled'])
        Draft202012Validator(schema).validate(exported)  # current GUI exporter
