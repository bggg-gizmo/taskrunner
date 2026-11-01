"""Regression tests for the actual Windows execution-7 failure and v1.2 wizard integrations."""
from __future__ import annotations
import wave
from pathlib import Path
from PIL import Image
import pytest

from task_runner.actions import ACTIONS, VERIFY_KINDS, default_step
from task_runner.executor import WorkflowEngine
from task_runner.flow import validate_workflow
from task_runner.store import Store
from task_runner import wininput
from task_runner.visual_verification import parse_region, significant_change


def test_default_click_retries_and_settling_time():
    step=default_step('click')
    assert step['retry_count'] >= 2
    assert step['retry_delay'] >= 1
    assert step['delay_after'] >= 1
    assert step['delay_before']==0
    assert default_step('browser_expand_all')['type'] == 'browser_expand_all'
    assert default_step('desktop_scroll_text')['type'] == 'desktop_scroll_text'


def test_windows_native_unicode_input_has_valid_event_counts_without_pyautogui():
    calls=[]
    sleep_calls=[]
    def fake(n,items,struct_size):
        calls.append((n,struct_size,[(item.data.ki.wVk,item.data.ki.wScan,item.data.ki.dwFlags) for item in items]))
        return n
    wininput.send_text('a💾\r\n\t', interval=0.01, sleep=sleep_calls.append, sender=fake)
    # a=2 events; supplementary codepoint=two UTF16 units, four events;
    # CRLF is ONE Enter; Tab is two key events.
    assert [x[0] for x in calls]==[2,4,2,2]
    assert len(sleep_calls)==4
    assert calls[0][2][0][1]==ord('a')
    assert calls[0][2][0][2] == wininput.KEYEVENTF_UNICODE
    assert calls[1][2][0][1] in range(0xd800,0xdc00)
    assert calls[1][2][2][1] in range(0xdc00,0xe000)
    assert calls[2][2][0][0]==wininput.VK_RETURN
    assert calls[3][2][0][0]==wininput.VK_TAB


def test_native_input_sender_error_is_not_masked():
    with pytest.raises(OSError,match='SendInput delivered'):
        wininput.send_text('hello', interval=0,sleep=lambda n:None,sender=lambda *args:0)


def test_visual_change_parse_and_preflight():
    assert parse_region('10,-20,200,60')=={'left':10,'top':-20,'width':200,'height':60}
    assert parse_region('') is None
    for region in ('x,2,4,5','1,2,0,5','2,3,5','1,2,3,4,5'):
        with pytest.raises(ValueError):parse_region(region)
    step=default_step('click')
    step['verify']={'kind':'screen_changed','target':'10,-20,200,60','timeout':1}
    validate_workflow([step])
    step['verify']['target']='incorrect'
    with pytest.raises(ValueError):validate_workflow([step])
    assert sum(code=='screen_changed' for code,_ in VERIFY_KINDS)==1


def test_pixel_comparison():
    before=Image.new('RGB',(120,120),(50,50,50))
    after=before.copy()
    assert not significant_change(before,after)
    for x in range(20,60):
        for y in range(30,70):
            after.putpixel((x,y),(255,0,255))
    assert significant_change(before,after)


def test_screen_unchanged_causes_retry_then_validated_success(tmp_path,monkeypatch):
    from task_runner import visual_verification
    import task_runner.executor as executor
    before=Image.new('RGB',(80,80),(0,0,0))
    after=Image.new('RGB',(80,80),(255,255,255))
    samples=iter((before,before,before,after))
    monkeypatch.setattr(visual_verification,'take_sample',lambda region='': next(samples))
    monkeypatch.setattr(executor.WorkflowEngine,'sleep',lambda self,s:None)
    store=Store(tmp_path/'data.sqlite')
    item=default_step('set_var')
    item['params']={'name':'test','value':'complete'}
    item['retry_count']=2
    item['retry_delay']=0
    item['verify']={'kind':'screen_changed','target':'','timeout':0}
    job=store.save_job({'name':'retry screen change','actions':[item]})
    run=store.claim(job,force=True)
    engine=WorkflowEngine(store)
    assert engine.execute(job,run)=='success'
    events=store.events_for(run)
    assert any('attempt 1:' in e['message'] and 'Verification failed' in e['message'] for e in events)
    assert any('attempt 2/3' in e['message'] for e in events)


def test_audio_assets_are_original_wav_files():
    root=Path(__file__).resolve().parents[1]/'assets'
    for name in ('startup.wav','exit.wav','select.wav','run.wav','save.wav','done.wav','error.wav'):
        with wave.open(str(root/name),'rb') as sound:
            assert sound.getnchannels() in (1,2)
            assert sound.getframerate()>=8000
            assert sound.getnframes()>0


def test_wizard_shortcuts_and_capture_modes_are_real_wired_methods():
    # Pure source inspection: GUI imports cannot be executed on the Linux host
    # without Qt. Windows BUILD_WINDOWS.cmd imports GUI and runs all tests.
    src=(Path(__file__).resolve().parents[1]/'task_runner'/'gui.py').read_text(encoding='utf-8')
    for essential in ('self.bulk_timing','self.begin_capture("click",5)',
                      'self.add_action(k)','"browser_expand_all"','"desktop_expand_all"',
                      '"browser_scroll_text"','"desktop_scroll_text"',
                      'self.preferences.play("startup")','self.preferences.play("exit",blocking=True)',
                      'self.showMinimized()','self.showNormal()'):
        assert essential in src
