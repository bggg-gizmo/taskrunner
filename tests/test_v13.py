"""v1.3 recorder, visual triggers, live capture, and uninstall regression tests."""
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from task_runner.actions import ACTIONS, default_step
from task_runner.recorder import Timeline
from task_runner.observability import LiveCapture, wait_until, image_match
from task_runner.flow import validate_workflow

class Clock:
    def __init__(self):self.now=10.0
    def __call__(self):return self.now
    def advance(self, seconds):self.now+=seconds


def test_recorded_click_follows_window_and_waits_for_slow_program():
    clock=Clock()
    title={'v':'Explorer'}
    def window(x,y):return {'window_title':title['v'],'window_rx':.5,'window_ry':.5}
    timeline=Timeline(clock, window_info=window)
    timeline._last=clock()
    clock.advance(2)
    timeline.mouse_click(350,250)
    clock.advance(12.7)
    title['v']='A very slow app'
    timeline.mouse_click(750,450)
    actions=timeline.result()
    assert [s['type'] for s in actions]==['wait_window','click','wait_window','click']
    assert actions[2]['params']['title']=='A very slow app'
    assert actions[2]['delay_before']==12.7
    assert actions[3]['params']['window_rx']==.5
    assert all(s['verify']['kind']=='none' for s in actions)
    validate_workflow(actions)


def test_recorder_keystrokes_text_shortcuts_stop_hotkey():
    clock=Clock();t=Timeline(clock,window_info=lambda *_:{})
    t._last=clock()
    clock.advance(1);t.key_down('h','h');t.key_up('h')
    clock.advance(.2);t.key_down('i','i');t.key_up('i')
    clock.advance(1);t.key_down('ctrl');t.key_down('c','c');t.key_up('c');t.key_up('ctrl')
    t.key_down('ctrl');t.key_down('shift');t.key_down('f12')
    assert t.stopped
    assert [(s['type'],s['params']) for s in t.result()] == [
        ('type',{'text':'hi','interval':.02}),('hotkey',{'keys':'ctrl+c'})]


def test_recorded_double_click_and_actual_delays():
    clock=Clock();t=Timeline(clock,window_info=lambda *_:{})
    clock.advance(3);t.mouse_click(50,60)
    clock.advance(.12);t.mouse_click(50,60)
    assert len(t.result())==1
    assert t.result()[0]['params']['clicks']==2
    assert t.result()[0]['delay_before']==0.0  # start not armed until recorder begins


def test_recording_is_not_saved_until_explicit_task_save():
    t=Timeline(window_info=lambda *_:{})
    t.mouse_click(10,10)
    a=t.result();a[0]['params']['x']=999
    assert t.result()[0]['params']['x']==10


def test_wait_until_uses_cancellation_and_times_out():
    count=[]
    with pytest.raises(TimeoutError):
        wait_until(lambda:False,.02,poll=.01)
    with pytest.raises(RuntimeError,match='stop requested'):
        wait_until(lambda:False,10,abort=lambda: (_ for _ in ()).throw(RuntimeError('stop requested')))


def test_live_file_capture_snapshots_and_manifest(tmp_path):
    source=tmp_path/'output.log';source.write_text('started',encoding='utf-8')
    monitor=LiveCapture('file',str(tmp_path/'capture'),str(source))
    first=monitor.capture()
    assert first.read_text()=='started'
    assert monitor.capture() is None
    source.write_text('started\nrender completed',encoding='utf-8')
    second=monitor.capture()
    assert second.read_text().endswith('render completed')
    manifest=monitor.stop()
    doc=json.loads(manifest.read_text())
    assert doc['captured']==2
    assert doc['files']==[str(first),str(second)]
    assert Path(doc['files'][0]).exists()


def test_screen_capture_changed_png(tmp_path):
    from PIL import Image
    colors=iter([Image.new('RGB',(4,4),'red'),Image.new('RGB',(4,4),'red'),
                 Image.new('RGB',(4,4),'blue')])
    with patch('task_runner.observability.screen_image',side_effect=lambda _: next(colors)):
        monitor=LiveCapture('screen',str(tmp_path/'screens'))
        assert monitor.capture().suffix=='.png'
        assert monitor.capture() is None
        assert monitor.capture().suffix=='.png'
        assert json.loads(monitor.stop().read_text())['captured']==2


def test_monitor_validation_and_source_guardrails(tmp_path):
    with pytest.raises(ValueError):LiveCapture('window',str(tmp_path))
    with pytest.raises(ValueError):LiveCapture('screen',str(tmp_path),interval=0)
    with pytest.raises(ValueError):LiveCapture('screen',str(tmp_path),max_captures=0)
    with pytest.raises(ValueError):LiveCapture('console',str(tmp_path))


def test_new_actions_visible_and_json_schema_matches():
    from scripts.generate_workflow_schema import generate
    root=Path(__file__).resolve().parents[1]
    assert json.loads((root/'schemas/taskrunner-job.schema.json').read_text(encoding='utf-8'))==generate()
    assert {'wait_screen','wait_content','capture_live_start','capture_live_stop',
            'clipboard_image','capture_program_output'} <= ACTIONS.keys()
    for kind in ('wait_screen','capture_live_stop'):
        validate_workflow([default_step(kind)])
    invalid=default_step('wait_screen')
    invalid['params']['mode']='image_appears'
    with pytest.raises(ValueError,match='reference image'):validate_workflow([invalid])


def test_windows_installer_exposes_uninstall_registration():
    root=Path(__file__).resolve().parents[1]
    install=(root/'scripts/install_windows.ps1').read_text()
    uninstall=(root/'scripts/uninstall_windows.ps1').read_text()
    build=(root/'BUILD_WINDOWS.cmd').read_text()
    assert 'UninstallString' in install and 'HKCU:' in install
    assert 'TaskRunnerScheduler' in uninstall
    assert "Read-Host 'Delete all saved workflows" in uninstall
    assert 'pynput' in build
    assert (root/'UNINSTALL_WINDOWS.cmd').is_file()


def test_executor_waits_for_live_file_text_and_exposes_variable(tmp_path):
    import threading, time
    from task_runner.executor import WorkflowEngine
    from task_runner.store import Store
    store=Store(tmp_path/'db.sqlite3')
    path=tmp_path/'result.txt'
    output=tmp_path/'final.txt'
    wait=default_step('wait_content')
    wait['params'].update({'source':'file','target':str(path),'condition':'contains',
                            'text':'READY','name':'observed','poll':.1,'timeout':2})
    write=default_step('write_file')
    write['params'].update({'path':str(output),'text':'${observed}'})
    job_id=store.save_job({'name':'Wait for output','actions':[wait,write]})
    claim=store.claim(job_id,force=True)
    def produce():
        time.sleep(.15)
        path.write_text('STARTED\nREADY\n',encoding='utf-8')
    worker=threading.Thread(target=produce);worker.start()
    assert WorkflowEngine(store).execute(job_id,claim)=='success'
    worker.join(timeout=1)
    assert output.read_text()=='STARTED\nREADY\n'


def test_live_capture_spans_multiple_engine_actions(tmp_path):
    from task_runner.executor import WorkflowEngine
    from task_runner.store import Store
    store=Store(tmp_path/'db.sqlite3')
    source=tmp_path/'process-output.log'
    source.write_text('first',encoding='utf-8')
    destination=tmp_path/'snapshots'
    start=default_step('capture_live_start')
    start['params'].update({'mode':'file','source':str(source),'destination':str(destination),
                            'interval':.1,'max_captures':20})
    sleep=default_step('wait');sleep['params']['seconds']=.15
    update=default_step('write_file');update['params'].update({'path':str(source),'text':'second'})
    sleep_again=default_step('wait');sleep_again['params']['seconds']=.15
    stop=default_step('capture_live_stop')
    job_id=store.save_job({'name':'Monitor output','actions':[start,sleep,update,sleep_again,stop]})
    claim=store.claim(job_id,force=True)
    runner=WorkflowEngine(store)
    assert runner.execute(job_id,claim)=='success'
    manifest=json.loads(Path(runner.vars['capture_manifest']).read_text())
    assert manifest['captured']>=2
    assert any(Path(f).read_text()=='second' for f in manifest['files'])


def test_program_stdout_stream_capture(tmp_path):
    import sys
    from task_runner.executor import WorkflowEngine
    log=tmp_path/'program-output.log'
    step=default_step('capture_program_output')
    step['params'].update({'path':sys.executable,'arguments':'-c "print(123456)"',
                           'output':str(log),'timeout':5})
    runner=WorkflowEngine()
    runner.run_action(step)
    assert b'123456' in log.read_bytes()
    assert runner.vars['last_file']==str(log)


def test_click_image_uses_current_match_not_recorded_coordinates(monkeypatch):
    import sys, types
    import task_runner.executor as executor
    import task_runner.observability as obs
    import task_runner.winmouse as winmouse

    runner=executor.WorkflowEngine()
    clicked=[]
    monkeypatch.setattr(obs,'image_location',lambda *args:(123,567))
    capture_click=lambda *args,**kwargs:clicked.append((args,kwargs))
    monkeypatch.setattr(winmouse,'click',capture_click)
    monkeypatch.setitem(sys.modules,'pyautogui',types.SimpleNamespace(click=capture_click))
    step=default_step('click_image')
    step['params'].update({'image':'current-button.png','region':''})
    # Cover both the native Windows multi-monitor implementation and the
    # PyAutoGUI fallback, even on Linux build-validation hosts.
    for platform in ('win32','linux'):
        monkeypatch.setattr(executor,'sys',types.SimpleNamespace(platform=platform))
        clicked.clear()
        runner.run_action(step)
        assert clicked==[((123,567),{'button':'left'})]


def test_browser_close_preserves_unrelated_output_capture(tmp_path):
    from task_runner.executor import WorkflowEngine
    from task_runner.observability import LiveCapture
    runner=WorkflowEngine()
    monitor=LiveCapture('screen',str(tmp_path/'images'))
    runner.live_capture=monitor
    runner.run_action(default_step('browser_close'))
    assert runner.live_capture is monitor
    runner.cleanup()
    assert runner.live_capture is None


def test_recorder_captures_drag_and_duration():
    clock=Clock();timeline=Timeline(clock,window_info=lambda *_:{})
    timeline._last=clock()
    clock.advance(1.0)
    timeline.mouse_click(10,15,pressed=True)
    clock.advance(2.5)
    timeline.mouse_click(150,90,pressed=False)
    actions=timeline.result()
    assert len(actions)==1
    assert actions[0]['type']=='drag'
    assert actions[0]['params']=={'x1':10,'y1':15,'x2':150,'y2':90,'duration':2.5}
    assert actions[0]['delay_before']==1.0
    validate_workflow(actions)


def test_live_capture_copies_completed_rendered_image_file(tmp_path):
    from PIL import Image
    src=tmp_path/'renders';src.mkdir()
    monitor=LiveCapture('image_folder',str(tmp_path/'saved-images'),str(src))
    picture=src/'final-art.png'
    Image.new('RGB',(5,5),'red').save(picture)
    assert monitor.capture() is None  # must be observed stable before copy
    saved=monitor.capture()
    assert saved and saved.is_file()
    assert saved.read_bytes()==picture.read_bytes()
    assert monitor.capture() is None
    doc=json.loads(monitor.stop().read_text())
    assert doc['captured']==1
    assert doc['files']==[str(saved)]
