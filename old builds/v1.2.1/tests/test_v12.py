"""v1.2: integration checks for text extraction, disclosures, delays and waits."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

from task_runner.actions import ACTIONS,default_step
from task_runner.collection import capture_browser_scrolling_text,expand_browser_controls
from task_runner.executor import WorkflowEngine
from task_runner.flow import validate_workflow
from task_runner.store import Store


def step(kind,**params):
    item=default_step(kind)
    item['params'].update(params)
    return item


def test_v12_action_catalog_and_defaults_are_wired():
    for action in ("browser_expand_all","browser_scroll_text","desktop_expand_all", "desktop_scroll_text",
                   "browser_select","browser_wait_state","wait_window","wait_file"):
        assert action in ACTIONS
        assert action==default_step(action)['type']
    assert step("wait_file")['delay_before']==0.0
    assert step("wait_file")['delay_after']==0.0


def test_wait_before_action_comes_before_side_effect(monkeypatch,tmp_path):
    events=[]
    database=Store(tmp_path/'v12.sqlite3')
    target=tmp_path/'output.txt'
    task=step('write_file',path=str(target),text='written')
    task['delay_before']=0.3
    task['delay_after']=0.4
    job=database.save_job({'name':'before/after','actions':[task]})
    claim=database.claim(job,force=True)
    engine=WorkflowEngine(database)
    def spy_sleep(seconds):
        events.append(('sleep',seconds,target.exists()))
    monkeypatch.setattr(engine,'sleep',spy_sleep)
    assert engine.execute(job,claim)=='success'
    assert events[0]==('sleep',0.3,False)
    assert events[1]==('sleep',0.4,True)


def test_wait_file_immediate_and_missing(tmp_path):
    engine=WorkflowEngine(Store(tmp_path/'database.sqlite3'))
    path=tmp_path/'exists.txt';path.write_text('hi')
    engine.run_action(step('wait_file',path=str(path),state='exists',timeout=0))
    engine.run_action(step('wait_file',path=str(path/'nope'),state='missing',timeout=0))
    with pytest.raises(TimeoutError):
        engine.run_action(step('wait_file',path=str(tmp_path/'nonexistent'),state='exists',timeout=0))


def test_invalid_limits_fail_before_file_side_effect(tmp_path):
    target=tmp_path/'file.txt'
    tasks=[step('write_file',path=str(target),text='no'),step('browser_scroll_text',max_scrolls=10001)]
    db=Store(tmp_path/'tasks.sqlite3')
    with pytest.raises(ValueError):db.save_job({'name':'rejected','actions':tasks})
    assert not target.exists()
    for action,field in [('browser_expand_all','max_controls'),('desktop_expand_all','max_controls'),
                         ('desktop_scroll_text','max_scrolls')]:
        with pytest.raises(ValueError):validate_workflow([step(action,**{field:0})])


def test_before_delay_invalidates_preflight():
    item=step('wait',seconds=1)
    for value in (-1,3601,'invalid'):
        item['delay_before']=value
        with pytest.raises(ValueError):validate_workflow([item])


def test_playwright_real_browser_disclosures_and_scrolling(tmp_path):
    from playwright.sync_api import sync_playwright
    import shutil
    binary=shutil.which('chromium') or shutil.which('google-chrome')
    if not binary:
        pytest.skip('Authoring environment has no Chromium; frozen EXE self-test checks packaged browser')
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,executable_path=binary,args=['--no-sandbox'])
        try:
            page=browser.new_page()
            page.set_content('''<!doctype html><html><body>
              <details id="details"><summary>Open me</summary><p>Details text</p></details>
              <button id="menu" aria-expanded="false" onclick="this.setAttribute('aria-expanded','true');document.getElementById('hidden').hidden=false">Expand</button>
              <p id="hidden" hidden>Expanded text</p>
              <select id="choices"><option value="a">Alpha</option><option value="b">Beta</option></select>
              <div id="scroller" style="height:120px;overflow-y:auto"><div style="height:2000px">Top</div><p>Bottom of scrolling page</p></div>
              </body></html>''')
            results=expand_browser_controls(page,'body',20)
            assert results['details_opened']==1
            assert results['aria_opened']==1
            assert results['select_count']==1
            assert [item['label'] for item in results['selects'][0]['options']]==['Alpha','Beta']
            assert page.locator('#hidden').is_visible()
            # Exercise actual runner integration with a real Playwright page.
            engine=WorkflowEngine(Store(tmp_path/'real-chromium.sqlite3'))
            engine.page=page
            engine.run_action(step('browser_expand_all',selector='body',name='expanded',max_controls=20))
            assert json.loads(engine.vars['expanded'])['select_count']==1
            engine.run_action(step('browser_select',selector='#choices',method='label',choice='Beta'))
            assert page.locator('#choices').input_value()=='b'
            engine.run_action(step('browser_scroll_text',selector='#scroller',name='text',
                                   max_scrolls=20,step_px=300,pause_seconds=0,copy_to_clipboard=False))
            assert 'Bottom of scrolling page' in engine.vars['text']
            assert int(engine.vars['scroll_count'])>0
            browser.close()
        finally:
            if browser.is_connected():browser.close()


def test_no_hidden_pip_fallback_for_unrelated_failure(monkeypatch,tmp_path):
    from scripts import shared_dependencies as dep
    calls=[]
    def fake(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1,stdout='ERROR: package wheel not found')
    monkeypatch.setattr(dep.subprocess,'run',fake)
    with pytest.raises(Exception):dep.install_shared_requirements(tmp_path/'req.txt')
    assert len(calls)==1


def test_shared_pip_cache_permission_recovers(monkeypatch,tmp_path):
    from scripts import shared_dependencies as dep
    calls=[]
    def fake(args,**kwargs):
        calls.append(args)
        if len(calls)==1:
            return SimpleNamespace(returncode=1,stdout="ERROR [Errno 13] Permission denied: pip/cache/wheels/file.whl")
        return SimpleNamespace(returncode=0,stdout='Successfully installed')
    monkeypatch.setattr(dep.subprocess,'run',fake)
    dep.install_shared_requirements(tmp_path/'req.txt')
    assert len(calls)==2
    assert '--user' in calls[1]
    assert '--no-cache-dir' in calls[1]
    assert calls[1][0]==sys.executable
