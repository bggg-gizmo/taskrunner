"""Opt-in resource protection: no unexpected termination or history regressions."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from task_runner.resources import (
    MemoryWatch, ResourceSample, nvidia_compute_vram, nvidia_overview,
    process_identity, sample_resources, terminate_owned, threshold_breaches,
)
from task_runner.executor import WorkflowEngine, Cancelled
from task_runner.actions import ACTIONS


def metric(ram=100, free=4000, vram=None):
    return ResourceSample(345, ram, 1, free, 8192, 51.2, vram)


def test_snapshot_of_own_process_and_system():
    system=sample_resources()
    assert system.pid==0 and system.process_count==0
    assert system.available_ram_mb > 0 and system.total_ram_mb >= system.available_ram_mb
    report=sample_resources(os.getpid())
    assert report.pid==os.getpid() and report.process_count>=1
    assert report.process_ram_mb > 0
    assert process_identity(os.getpid())[0]==os.getpid()


def test_thresholds_do_not_treat_missing_gpu_as_zero():
    hits=threshold_breaches(metric(ram=300,free=200,vram=None),250,300,200)
    assert len(hits)==2
    assert all('VRAM' not in hit for hit in hits)
    assert len(threshold_breaches(metric(ram=300,free=200,vram=250),250,300,200))==3
    assert not threshold_breaches(metric(ram=100,free=4000,vram=None),200,200,500)


def test_default_warning_does_not_cancel_or_terminate():
    events=[]
    watch=MemoryWatch(345,process_ram_limit_mb=50,interval=.3,
        sampler=lambda pid,include_gpu:metric(100),on_event=lambda *args:events.append(args),
        terminator=lambda identity: pytest.fail('Termination is forbidden for warn'))
    watch.poll_once()
    watch.poll_once()
    assert watch.cancel_reason is None
    assert len([e for e in events if e[0]=='WARNING'])==1
    assert watch.stop()['samples']==2


def test_warning_does_not_spam_when_usage_fluctuates():
    values=iter([metric(101),metric(106),metric(110),metric(30),metric(102)])
    messages=[]
    watch=MemoryWatch(345,process_ram_limit_mb=90,
        sampler=lambda *a,**kw:next(values),on_event=lambda level,msg:messages.append((level,msg)))
    for _ in range(5):watch.poll_once()
    assert len([m for level,m in messages if level=='WARNING'])==2
    assert len([m for level,m in messages if 'recovered' in m])==1


def test_cancel_workflow_opt_in_without_process_termination():
    events=[]
    watch=MemoryWatch(345,process_ram_limit_mb=30,response='cancel_workflow',
        sampler=lambda *a,**kw:metric(50),on_event=lambda *a:events.append(a),
        terminator=lambda identity: pytest.fail('Cancellation must not kill the process'))
    watch.start()
    assert watch.cancel_reason and watch.stop()['samples']==1
    runner=WorkflowEngine()
    runner.memory_watch=watch
    with pytest.raises(Cancelled):runner.abort_if_requested()


def test_termination_for_unowned_process_is_forbidden():
    with pytest.raises(ValueError,match='launched'):
        MemoryWatch(345,process_ram_limit_mb=50,response='terminate_owned')
    with pytest.raises(ValueError,match='launched'):
        MemoryWatch(345,process_ram_limit_mb=50,response='terminate_owned',owned_identity=(346,1.0))


def test_explicit_owned_termination_only_fires_once():
    killed=[]
    watch=MemoryWatch(345,process_ram_limit_mb=20,response='terminate_owned',
        owned_identity=(345,1000.0),sampler=lambda *a,**kw:metric(50),
        terminator=lambda identity: killed.append(identity) or [345])
    watch.start()
    watch.stop()
    assert killed==[(345,1000.0)]
    assert watch.cancel_reason is not None


def test_owned_process_identity_mismatch_refuses_termination():
    with pytest.raises(RuntimeError,match='PID reuse'):
        terminate_owned((os.getpid(),1.0))


def test_gpu_parser_and_missing_gpu(monkeypatch):
    import task_runner.resources as resource
    monkeypatch.setattr(resource,'_nvidia_values',lambda args: ['NVIDIA Test, 1200, 8192'] if '--query-gpu=' in args[0] else ['99, 840','101, 120'])
    assert nvidia_overview()==[{'name':'NVIDIA Test','used_mb':1200.0,'total_mb':8192.0}]
    assert nvidia_compute_vram({99,101})==960.0
    assert nvidia_compute_vram({7}) is None
    monkeypatch.setattr(resource,'_nvidia_values',lambda args: None)
    assert nvidia_overview() is None and nvidia_compute_vram({99}) is None


def test_unsupported_nvidia_logs_not_falsely_zero():
    events=[]
    watch=MemoryWatch(345,process_gpu_vram_limit_mb=200,
        sampler=lambda *a,**kw:metric(vram=None),on_event=lambda *args:events.append(args))
    watch.poll_once();watch.poll_once()
    assert len(events)==1
    assert 'unavailable' in events[0][1]
    assert watch.cancel_reason is None


def test_memory_action_types_and_default_user_opt_in():
    assert {'memory_snapshot','memory_watch_start','memory_watch_stop'} <= ACTIONS.keys()
    defaults={f.key:f.default for f in ACTIONS['memory_watch_start'].fields}
    assert defaults['response']=='warn'
    assert defaults['process_ram_limit_mb']==0
    assert defaults['process_gpu_vram_limit_mb']==0


def test_actual_executor_action_monitor_and_cleanup():
    runner=WorkflowEngine()
    runner.vars['process_id']=str(os.getpid())
    runner.run_action({'type':'memory_snapshot','params':{'pid':'','include_gpu':False}})
    assert float(runner.vars['memory_process_ram_mb'])>0
    runner.run_action({'type':'memory_watch_start','params':{
        'pid':'','process_ram_limit_mb':0,'interval':.2,'response':'warn'}})
    time.sleep(.24)
    runner.run_action({'type':'memory_watch_stop','params':{}})
    assert float(runner.vars['memory_peak_process_mb'])>0
    assert int(runner.vars['memory_sample_count'])>=1
    assert runner.memory_watch is None
    runner.cleanup()


def test_workflow_cannot_terminate_external_process():
    runner=WorkflowEngine()
    runner.vars['process_id']=str(os.getpid())
    with pytest.raises(ValueError,match='arbitrary processes'):
        runner.run_action({'type':'memory_watch_start','params':{'response':'terminate_owned','process_ram_limit_mb':1}})
    assert runner.memory_watch is None


def test_invalid_monitor_configuration_rejected():
    for kwargs in ({'interval':.01},{'process_ram_limit_mb':-1},{'response':'delete_files'}):
        with pytest.raises(ValueError):MemoryWatch(345,**kwargs)


def test_complete_workflow_monitoring_and_log_events(tmp_path):
    """Real store/executor path, without monkeypatching the public dispatcher."""
    from task_runner.store import Store
    from task_runner.actions import default_step
    db=Store(tmp_path/'memory-watch.sqlite3')
    snapshot=default_step('memory_snapshot')
    snapshot['params'].update({'pid':str(os.getpid()),'include_gpu':False})
    start=default_step('memory_watch_start')
    start['params'].update({'pid':str(os.getpid()),'process_ram_limit_mb':1,
                            'interval':.2,'response':'warn'})
    pause=default_step('wait');pause['params']['seconds']=.25
    stop=default_step('memory_watch_stop')
    job=db.save_job({'name':'Resource guard integration','actions':[snapshot,start,pause,stop]})
    execution=db.claim(job,force=True)
    assert WorkflowEngine(db).execute(job,execution)=='success'
    events=db.events_for(execution)
    assert any('Resource snapshot PID' in item['message'] for item in events)
    assert any('Memory guard PID' in item['message'] for item in events)
    assert any('Resource guard stopped' in item['message'] for item in events)


def test_bad_memory_guard_pid_cannot_terminate_wrong_process():
    runner=WorkflowEngine()
    runner.owned_processes[os.getpid()]=(os.getpid(), 1.0)
    with pytest.raises(RuntimeError,match='PID reuse'):
        runner.run_action({'type':'memory_watch_start','params':{
            'pid':str(os.getpid()), 'response':'terminate_owned',
            'process_ram_limit_mb':1, 'interval':.5}})
    runner.cleanup()
