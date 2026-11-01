"""Dashboard auto refresh must remain nonblocking when SQLite work is slow."""
import threading
import time
from task_runner.dashboard_snapshot import DashboardSnapshotReader


class SlowStore:
    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Event()
        self.jobs = [{'id': 1, 'name': 'Original'}]

    def all_jobs(self):
        self.entered.set()
        assert self.release.wait(5)
        return self.jobs

    def execution_history(self, limit=200):
        return [{'id': 1, 'status': 'success'}]


def test_snapshot_collector_does_not_block_gui_and_carries_generation():
    store = SlowStore()
    collector = DashboardSnapshotReader(store)
    start = time.monotonic()
    assert collector.start(4)
    assert time.monotonic()-start < .3
    assert store.entered.wait(2)
    assert not collector.start(4)  # Never spawn a competing database reader
    assert collector.take_latest() is None
    store.release.set()
    deadline=time.monotonic()+5
    while (snapshot:=collector.take_latest()) is None and time.monotonic()<deadline:
        time.sleep(.01)
    assert snapshot is not None
    assert snapshot.generation == 4
    assert snapshot.jobs == store.jobs
    assert snapshot.history[0]['status']=='success'
    assert snapshot.error is None


def test_stale_snapshot_can_be_ignored_after_explicit_edit():
    store=SlowStore()
    reader=DashboardSnapshotReader(store)
    assert reader.start(7)
    assert store.entered.wait(2)
    current_generation=8  # Explicit edit/save happened during background read
    store.release.set()
    deadline=time.monotonic()+5
    while (snapshot:=reader.take_latest()) is None and time.monotonic()<deadline:
        time.sleep(.01)
    assert snapshot is not None and snapshot.generation!=current_generation


def test_reader_reports_db_error_without_raising_on_gui_thread():
    class BrokenStore:
        def all_jobs(self):
            raise OSError('simulated SQLite failure')
    reader=DashboardSnapshotReader(BrokenStore())
    assert reader.start(2)
    deadline=time.monotonic()+5
    while (snapshot:=reader.take_latest()) is None and time.monotonic()<deadline:
        time.sleep(.01)
    assert snapshot is not None and 'simulated SQLite failure' in snapshot.error
