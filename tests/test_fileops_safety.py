from pathlib import Path
import pytest
from task_runner.fileops import atomic_copy_file, atomic_write_text
from task_runner.actions import default_step
from task_runner.executor import WorkflowEngine
from task_runner.store import Store


def test_atomic_write_replaces_text_and_cleans_tempfiles(tmp_path):
    path = tmp_path / 'report.txt'
    path.write_text('original', encoding='utf-8')
    atomic_write_text(path, 'updated\ncontains unicode: 🦎')
    assert path.read_text(encoding='utf-8') == 'updated\ncontains unicode: 🦎'
    assert sorted(x.name for x in tmp_path.iterdir()) == ['report.txt']


def test_atomic_write_keeps_old_file_if_replace_fails(tmp_path, monkeypatch):
    import task_runner.fileops as fileops
    path = tmp_path / 'report.txt'
    path.write_text('original', encoding='utf-8')
    def fail(*args):
        raise PermissionError('locked target')
    monkeypatch.setattr(fileops.os, 'replace', fail)
    with pytest.raises(PermissionError):
        atomic_write_text(path, 'replacement')
    assert path.read_text() == 'original'
    assert sorted(x.name for x in tmp_path.iterdir()) == ['report.txt']


def test_atomic_copy_keeps_destination_if_copy_fails(tmp_path, monkeypatch):
    import task_runner.fileops as fileops
    src, dst = tmp_path/'source.txt', tmp_path/'dest.txt'
    src.write_text('new'); dst.write_text('important old content')
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(fileops.shutil, 'copy2', fail)
    with pytest.raises(OSError):
        atomic_copy_file(src, dst, overwrite=True)
    assert dst.read_text() == 'important old content'
    assert src.read_text() == 'new'
    assert sorted(x.name for x in tmp_path.iterdir()) == ['dest.txt', 'source.txt']


def test_atomic_copy_existing_destination_needs_explicit_overwrite(tmp_path):
    src, dst = tmp_path/'source.txt', tmp_path/'dest.txt'
    src.write_text('new'); dst.write_text('old')
    with pytest.raises(FileExistsError):
        atomic_copy_file(src, dst)
    assert dst.read_text() == 'old'
    atomic_copy_file(src, dst, overwrite=True)
    assert dst.read_text() == 'new'
    assert src.read_text() == 'new'


def test_workflow_file_write_uses_atomic_path(tmp_path):
    store = Store(tmp_path/'tasks.sqlite3')
    target = tmp_path/'result.txt'
    step = default_step('write_file')
    step['params'].update(path=str(target), text='Hello')
    job = store.save_job({'name': 'Atomic integration', 'actions':[step]})
    execution = store.claim(job, force=True)
    assert WorkflowEngine(store).execute(job, execution) == 'success'
    assert target.read_text() == 'Hello'
