"""CLI/worker and offline HTTP integration, independent of browser/Windows GUI."""
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from task_runner.actions import default_step
from task_runner.store import Store
from task_runner.runner import command
from task_runner.executor import WorkflowEngine

ROOT=Path(__file__).resolve().parents[1]


def step(kind,**params):
    item=default_step(kind)
    item['params'].update(params)
    return item


def test_source_command_is_absolute_and_carries_custom_data_dir(monkeypatch,tmp_path):
    monkeypatch.setenv('TASKRUNNER_HOME',str(tmp_path/'custom data'))
    args=command('--tick')
    assert args[0]==sys.executable
    assert args[1]==str(ROOT/'launcher.py')
    assert args[2]=='--tick'
    assert args[3]=='--data-dir'
    assert args[4]==str((tmp_path/'custom data').resolve())


def test_tick_runs_from_unrelated_working_directory(tmp_path):
    dbdir=tmp_path/'custom data'
    invocation=[sys.executable,str(ROOT/'launcher.py'),'--tick','--data-dir',str(dbdir)]
    completed=subprocess.run(invocation,cwd=str(tmp_path),capture_output=True,text=True,timeout=15)
    assert completed.returncode==0,completed.stderr
    assert (dbdir/'tasks.sqlite3').exists()


def test_claimed_worker_subprocess_writes_file(tmp_path):
    home=tmp_path/'user tasks'
    store=Store(home/'tasks.sqlite3')
    result=tmp_path/'result.txt'
    job=store.save_job({'name':'CLI integration','actions':[step('write_file',path=str(result),text='All steps executed')]})
    run=store.claim(job,force=True)
    completed=subprocess.run([sys.executable,str(ROOT/'launcher.py'),'--run-claimed',str(job),str(run),
                              '--data-dir',str(home)],cwd=str(tmp_path),capture_output=True,text=True,timeout=15)
    assert completed.returncode==0,completed.stderr
    assert result.read_text()=='All steps executed'
    assert store.get_job(job)['status']=='success'
    assert store.execution_history()[0]['status']=='success'


def test_http_get_then_soup_parsing(tmp_path):
    class LocalHTML(BaseHTTPRequestHandler):
        def do_GET(self):
            document=b'<html><body><main id="answer" data-value="fully-integrated">OK</main></body></html>'
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(document)))
            self.end_headers()
            self.wfile.write(document)
        def log_message(self,*args):pass

    server=ThreadingHTTPServer(('127.0.0.1',0),LocalHTML)
    th=threading.Thread(target=server.serve_forever,daemon=True)
    th.start()
    try:
        store=Store(tmp_path/'runs.db')
        job=store.save_job({'name':'HTTP+BeautifulSoup','actions':[
            step('http_get',url=f'http://127.0.0.1:{server.server_port}/',name='page'),
            step('soup_select',source='page',selector='#answer',attribute='data-value',name='answer'),
            step('write_file',path=str(tmp_path/'output.txt'),text='${answer}')
        ]})
        run=store.claim(job,force=True)
        engine=WorkflowEngine(store)
        assert engine.execute(job,run)=='success'
        assert (tmp_path/'output.txt').read_text()=='fully-integrated'
        assert engine.vars['http_status']=='200'
    finally:
        server.shutdown();server.server_close()


def test_scheduled_tick_launches_due_worker_with_custom_home(tmp_path):
    import time
    from task_runner.scheduling import utc_now,utc_text
    from datetime import timedelta
    home=tmp_path/'scheduled data'
    store=Store(home/'tasks.sqlite3')
    output=tmp_path/'scheduled.txt'
    job=store.save_job({'name':'Cross-process scheduled workflow','actions':[
        step('write_file',path=str(output),text='scheduler delivered')],
        'schedule_kind':'interval','schedule':{'seconds':60}})
    with store.connection() as db:
        db.execute('UPDATE jobs SET next_run=? WHERE id=?',
                   (utc_text(utc_now()-timedelta(seconds=1)),job))
    process=subprocess.run([sys.executable,str(ROOT/'launcher.py'),'--tick','--data-dir',str(home)],
                           cwd=str(tmp_path),capture_output=True,text=True,timeout=15)
    assert process.returncode==0,process.stderr
    deadline=time.monotonic()+10
    while not output.exists() and time.monotonic()<deadline:
        time.sleep(.1)
    assert output.is_file()
    assert output.read_text()=='scheduler delivered'
    while store.execution_history()[0]['status']=='running' and time.monotonic()<deadline:
        time.sleep(.1)
    assert store.execution_history()[0]['status']=='success'
