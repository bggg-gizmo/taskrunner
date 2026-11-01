"""Cross-platform checks of Windows launcher configuration (no Windows calls)."""
from pathlib import Path
from types import SimpleNamespace
import base64
import subprocess
from task_runner import paths,runner


def test_frozen_browser_path_overrides_existing_user_browser_cache(monkeypatch,tmp_path):
    monkeypatch.setattr(paths,'sys',SimpleNamespace(frozen=True,executable=str(tmp_path/'TaskRunner.exe')))
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH','C:\\unrelated-user-cache')
    paths.setup_browser_path()
    assert paths.os.environ['PLAYWRIGHT_BROWSERS_PATH']==str(tmp_path/'browser-binaries')


def test_powershell_schedule_registers_interactive_no_password(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(runner,'sys',SimpleNamespace(platform='win32',frozen=False,
                                                    executable=str(tmp_path/'python.exe')))
    monkeypatch.setattr(runner.subprocess,'run',lambda args,**kw: (
        calls.append(args) or SimpleNamespace(returncode=0,stdout='Registered',stderr='')))
    ok,message=runner.install_scheduler()
    assert ok and message=='Registered'
    args=calls[0]
    assert args[:3]==['powershell.exe','-NoProfile','-NonInteractive']
    ps=base64.b64decode(args[-1]).decode('utf-16-le')
    assert '-LogonType Interactive' in ps
    assert '-RunLevel Limited' in ps
    assert 'TaskRunnerScheduler' in ps
    assert '--tick' in ps
    assert 'python.exe' in ps
    assert ' -Argument ' in ps
    assert ' -WorkingDirectory ' in ps
    assert 'Register-ScheduledTask' in ps
    assert '-Password' not in ps
