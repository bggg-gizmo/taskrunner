"""Construct and drive real Qt New Task / Edit dialogs under test."""
import sys
import pytest


def test_new_task_and_edit_work_in_real_qt(monkeypatch):
    pytest.importorskip('PySide6')
    if sys.platform != 'win32':
        monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from task_runner.diagnostics import interactive_dialogs
    interactive_dialogs()


def test_scheduler_poll_runs_off_the_gui_thread(monkeypatch):
    pytest.importorskip('PySide6')
    import time
    import threading
    import tempfile
    if sys.platform != 'win32':
        monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from task_runner.gui import MainWindow
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='taskrunner-scheduler-check-') as home:
        monkeypatch.setenv('TASKRUNNER_HOME',home)
        window=MainWindow()
        try:
            entered=threading.Event()
            completed=threading.Event()
            def slow_recovery():
                entered.set()
                time.sleep(.4)
                completed.set()
            monkeypatch.setattr(window.store,'recover_abandoned',slow_recovery)
            started=time.monotonic()
            window.check_due()
            assert (time.monotonic()-started)<.25
            assert entered.wait(3)
            assert completed.wait(5)
            window.check_due()
        finally:
            window.timer.stop()
            window.scheduler_timer.stop()
            window.debug_timer.stop()
            window.close()
