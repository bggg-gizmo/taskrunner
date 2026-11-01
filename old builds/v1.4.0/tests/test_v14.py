"""v1.4 regression: target certainty, interactive replay, secrets, reusable modules,
file-based schedules, and in-place preservation of existing workflows."""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from task_runner.actions import ACTIONS,default_step
from task_runner.debugger import PlaybackDebugger,DebugAbort
from task_runner.file_events import event_between, fingerprint
from task_runner.modules import expand_modules
from task_runner.precision import TargetCandidate,choose,resolve_adaptive,AmbiguousTargetError
from task_runner.store import Store
from task_runner.vault import Vault


def make_job(store, name='Test', steps=None, schedule_kind='manual', schedule=None):
    return store.save_job({'name':name,'actions':steps or [default_step('wait')],
                           'schedule_kind':schedule_kind,'schedule':schedule or {},'enabled':True})


def eventually(predicate, timeout=3):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.02)
    raise AssertionError('Operation did not reach expected state')


def test_debugger_pauses_and_executes_one_step_without_skipping(tmp_path):
    store=Store(tmp_path/'task.sqlite3')
    jid=make_job(store)
    execution=store.claim(jid,force=True)
    store.debug_enable(execution,paused=True,snapshots=False)
    debug=PlaybackDebugger(store,execution)
    finished=[]
    worker=threading.Thread(target=lambda:(debug.before(1),finished.append('one'),debug.completed(1),debug.before(2),finished.append('two')))
    worker.start()
    eventually(lambda:store.debug_status(execution)['state']=='paused')
    assert finished==[]
    store.debug_command(execution,'step')
    eventually(lambda:finished==['one'] and store.debug_status(execution)['state']=='paused' and
               store.debug_status(execution)['step_index']==2)
    assert worker.is_alive()
    store.debug_command(execution,'run')
    worker.join(3)
    assert not worker.is_alive()
    assert finished==['one','two']


def test_debugger_failure_requires_explicit_retry(tmp_path):
    store=Store(tmp_path/'task.sqlite3')
    jid=make_job(store)
    execution=store.claim(jid,force=True)
    store.debug_enable(execution,paused=False,break_on_failure=True,snapshots=False)
    debug=PlaybackDebugger(store,execution)
    returned=[]
    worker=threading.Thread(target=lambda:returned.append(debug.failed(1,RuntimeError('missing window'))))
    worker.start()
    eventually(lambda:store.debug_status(execution)['state']=='failed_paused')
    assert returned==[]
    with pytest.raises(RuntimeError):store.debug_command(execution,'step')
    store.debug_command(execution,'retry')
    worker.join(3)
    assert returned==[True]
    assert store.debug_status(execution)['mode']=='pause'


def test_reteach_click_persists_and_rejects_wrong_step(tmp_path):
    store=Store(tmp_path/'db.sqlite3')
    click=default_step('click')
    task=make_job(store,steps=[click,default_step('wait')])
    run=store.claim(task,force=True)
    store.debug_enable(run,paused=True)
    store.debug_state(run,'paused',1,'')
    with pytest.raises(RuntimeError):store.teach_click(run,2,{'x':30,'y':40})
    store.teach_click(run,1,{'x':30,'y':40,'reference_image':str(tmp_path/'button.png'),
                             'strict_target':True,'window_title':'Editor'})
    corrected=store.get_job(task)['actions'][0]['params']
    assert (corrected['x'],corrected['y'])==(30,40)
    assert corrected['strict_target'] is True
    assert store.correction_for(run,1)==corrected


def test_adaptive_priority_and_strict_failures():
    results=lambda title,expected:{'bounds':(200,100,400,400),
         'controls':[{'x':310,'y':190,'automation_id':'run','control_name':'Run'},
                     {'x':430,'y':280,'automation_id':'other','control_name':'Other'}]}
    chosen=resolve_adaptive(100,100,'Editor',.5,.5,'Run','run',
                           window_search=results,strict_target=True)
    assert chosen.method=='automation_id' and (chosen.x,chosen.y)==(310,190)
    selected=resolve_adaptive(15,19,'',reference_image='fake',strict_target=True,
                             image_search=lambda *a:[TargetCandidate(85,96,'image',.97)])
    assert selected.method=='image' and selected.confidence==.97
    with pytest.raises(LookupError):resolve_adaptive(15,19,'',reference_image='missing',strict_target=True,
                                                     image_search=lambda *a:[])
    assert resolve_adaptive(15,19).method=='absolute'  # legacy workflows still work
    assert resolve_adaptive(15,19,'Editor',.25,.25,window_search=results).method=='window-relative'


def test_duplicate_targets_never_silently_pick_one():
    candidates=[TargetCandidate(40,40,'image',.981),TargetCandidate(300,300,'image',.979)]
    with pytest.raises(AmbiguousTargetError):choose(candidates)
    assert choose(candidates,expected=(40,40)).x==40
    assert choose([TargetCandidate(40,40,'image',.95),TargetCandidate(41,41,'image',.94)]).x==40


def test_module_expansion_and_cycles(tmp_path):
    store=Store(tmp_path/'db.sqlite3')
    child=make_job(store,name='Reusable',steps=[default_step('set_var'),default_step('wait')])
    root=default_step('run_module');root['params']['task_id']=child
    root['delay_before']=1.5
    expanded=expand_modules(store,[root,default_step('wait')])
    assert [s['type'] for s in expanded]==['set_var','wait','wait']
    assert expanded[0]['delay_before']==1.5
    another=make_job(store,name='Parent',steps=[root])
    recursive=default_step('run_module');recursive['params']['task_id']=another
    # Use the current job ID as ancestor, even though there are no prior steps.
    with pytest.raises(ValueError):expand_modules(store,[recursive],ancestors=(another,))


def test_dpapi_vault_has_no_plaintext_fallback(tmp_path,monkeypatch):
    # Mock ONLY Windows encryption for deterministic offline tests.
    import task_runner.vault as vault_module
    encrypted=Vault(tmp_path/'safe',protect=lambda b:bytes((x^0xA5) for x in b),
                    unprotect=lambda b:bytes((x^0xA5) for x in b))
    encrypted.put('api_key','secret-123')
    assert encrypted.get('api_key')=='secret-123'
    assert 'secret-123' not in (tmp_path/'safe'/'api_key.dpapi').read_bytes().decode('latin1')
    with pytest.raises(ValueError):encrypted.put('../oops','token')
    assert encrypted.list_names()==['api_key']
    encrypted.remove('api_key')
    assert not encrypted.list_names()
    if vault_module.sys.platform!='win32':
        with pytest.raises(OSError):Vault(tmp_path/'no_fallback').put('token','abc')


def test_file_event_watch_uses_durable_baseline_and_no_duplicate_runs(tmp_path):
    db=Store(tmp_path/'db.sqlite3')
    target=tmp_path/'out.txt'
    jid=make_job(db,schedule_kind='file_event',schedule={'path':str(target),'event':'any'})
    assert db.claim_file_events()==[]  # initial baseline (missing)
    target.write_text('first')
    claimed=db.claim_file_events()
    assert len(claimed)==1 and claimed[0][0]==jid
    assert db.claim_file_events()==[]
    db.finish(jid,claimed[0][1],'success','done')
    target.write_text('a longer file')
    claimed=db.claim_file_events()
    assert len(claimed)==1
    db.finish(jid,claimed[0][1],'success','done')
    target.unlink()
    assert len(db.claim_file_events())==1
    assert event_between('{"exists": false}','{"exists": true}')=='created'
    assert event_between('{"exists": true}','{"exists": false}')=='removed'


def test_file_event_validation(tmp_path):
    store=Store(tmp_path/'db.sqlite3')
    with pytest.raises(ValueError):make_job(store,schedule_kind='file_event',schedule={'path':'relative'})
    with pytest.raises(ValueError):make_job(store,schedule_kind='file_event',schedule={'path':str(tmp_path),'event':'bad'})


def test_all_existing_actions_remain_present():
    for name in ('click','move','drag','scroll','type','key','browser_open','browser_select','soup_select',
                 'wait_screen','wait_content','capture_live_start','capture_live_stop','capture_program_output',
                 'click_image','shutdown','repeat','if_var'):
        assert name in ACTIONS
    for addition in ('run_module','load_secret'):
        assert addition in ACTIONS
