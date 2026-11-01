"""v1.5.1 PID reuse and user-initiated stop race regressions."""
from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

from task_runner.executor import Cancelled, WorkflowEngine
from task_runner.resources import MemoryWatch, ResourceSample, process_identity


def sample(ram=100):
    return ResourceSample(234,ram,1,2048,8192,45,None)


def test_warning_guard_rejects_recycled_pid_before_reading_memory():
    touched=[]
    watch=MemoryWatch(234,process_ram_limit_mb=50,response='warn',
                      observed_identity=(234,1.0),
                      identity_provider=lambda pid:(pid,2.0),
                      sampler=lambda *args,**kwargs:touched.append(1) or sample(),
                      on_event=lambda *args:None)
    with pytest.raises(ProcessLookupError,match='reused'):
        watch.start()
    assert touched==[]


def test_monitored_pid_identity_is_validated_for_all_policies():
    observed=[]
    watch=MemoryWatch(os.getpid(), process_ram_limit_mb=0,
                      observed_identity=process_identity(os.getpid()),
                      sampler=lambda *args,**kwargs:sample(),
                      on_event=lambda level,message:observed.append((level,message)))
    watch.start()
    summary=watch.stop()
    assert summary['samples']==1
    assert observed==[]


def test_memory_stop_while_sampling_does_not_trigger_late_termination():
    entered=threading.Event()
    release=threading.Event()
    actions=[]
    def slow_sampler(*args,**kwargs):
        entered.set()
        assert release.wait(5)
        return sample(ram=500)
    watch=MemoryWatch(234,process_ram_limit_mb=5,response='terminate_owned',
                      owned_identity=(234,1.0),sampler=slow_sampler,
                      terminator=lambda _:actions.append('terminated') or [234],
                      on_event=lambda *a:actions.append('event'))
    worker=threading.Thread(target=watch.poll_once,daemon=True)
    worker.start()
    assert entered.wait(3)
    # A cancellation can occur after the sampler starts but before it returns.
    watch._stop.set()
    release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert actions==[]
    assert watch.cancel_reason is None


def test_late_guard_cancel_during_stop_cannot_be_lost(monkeypatch):
    runner=WorkflowEngine()
    class LateAlert:
        cancel_reason=None
        def stop(self):
            self.cancel_reason='Memory threshold exceeded during shutdown'
            return {'peak_process_mb':150,'samples':4}
    watcher=LateAlert()
    runner.memory_watch=watcher
    with pytest.raises(Cancelled,match='threshold exceeded'):
        runner.run_action({'type':'memory_watch_stop','params':{}})
    assert runner.memory_watch is None
    assert runner.vars['memory_peak_process_mb']=='150'
    assert runner.vars['memory_sample_count']=='4'


def test_identity_validation_rejects_wrong_pid_at_configuration():
    with pytest.raises(ValueError, match='monitored PID'):
        MemoryWatch(234,observed_identity=(999,1.0))


def test_monitor_thread_releases_guard_when_pid_is_reused():
    import time
    history=[]
    identities=iter([(234,1.0),(234,2.0)])
    watch=MemoryWatch(234,interval=.2,process_ram_limit_mb=0,
                      observed_identity=(234,1.0),
                      identity_provider=lambda _pid:next(identities),
                      sampler=lambda *a,**kw:sample(),
                      on_event=lambda level,message:history.append((level,message)))
    watch.start()
    assert watch._thread is not None
    assert watch._stop.wait(2)
    watch.stop()
    assert watch.cancel_reason is None
    assert watch.samples == 1
    assert any('reused' in message for _level,message in history)


def test_windows_installer_rolls_back_before_discarding_old_build():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    source=(root/'scripts/install_windows.ps1').read_text(encoding='utf-8')
    assert source.index('$activated = $true') < source.index('$committed = $true',source.index('try {'))
    assert source.index("-Name NoRepair") < source.index('$committed = $true',source.index('try {'))
    assert "Remove-Item -LiteralPath $install -Recurse -Force" in source
    assert "Move-Item -LiteralPath $old -Destination $install -ErrorAction Stop" in source
    assert "if ($committed -and (Test-Path $old))" in source
    assert "DisplayVersion -Value '1.5.1'" in source


def test_release_version_and_readme_reference_actual_current_source():
    import json
    from pathlib import Path
    from task_runner import __version__
    root=Path(__file__).resolve().parents[1]
    assert __version__ == '1.5.1'
    assert json.loads((root/'repository-metadata.json').read_text())['version'] == __version__
    assert "1.5.1" in (root/'BUILD_WINDOWS.cmd').read_text()
    assert "1.5.1" in (root/'assets/version_info.txt').read_text()
    readme=(root/'README.md').read_text()
    assert 'Release-v1.5.1' in readme
    assert 'Source%20tests-139%20passing' in readme
    assert 'V1.5.1_RELEASE_NOTES.md' in readme
    assert (root/'V1.5.1_RELEASE_NOTES.md').is_file()
