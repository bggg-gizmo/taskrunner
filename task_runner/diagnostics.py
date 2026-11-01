"""Non-destructive post-build diagnostics for the packaged Windows application."""
from __future__ import annotations
import importlib
import json
import os
import platform
import sys
import tempfile
import traceback
from datetime import datetime,timezone
from pathlib import Path
from .paths import asset_path,setup_browser_path


def interactive_dialogs():
    """Exercise actual Qt objects and the New Task / Edit event handlers.

    The older self-test only imported the classes, missing runtime errors
    in dialog constructors, signal connections, and persistence.
    """
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton
    from .actions import default_step
    from .gui import MainWindow,TaskWizard,StepEditor
    app=QApplication.instance()
    if app is None:
        app=QApplication([])
    with tempfile.TemporaryDirectory(prefix='taskrunner-ui-check-') as temp:
        original_home=os.environ.get('TASKRUNNER_HOME')
        os.environ['TASKRUNNER_HOME']=temp
        window=None
        try:
            window=MainWindow()
            assert window.table is not None and window.stack.count()==5
            editor=StepEditor(default_step('wait'),parent=window)
            assert editor.kind.currentData()=='wait'
            editor.apply()
            assert editor.result()==QDialog.DialogCode.Accepted
            editor.deleteLater()

            def scripted_wizard(dialog):
                dialog.name.setText('GUI smoke test edited' if dialog.previous.get('id') else 'GUI smoke test')
                if not dialog.actions:
                    dialog.actions=[default_step('wait')]
                dialog.refresh_actions()
                dialog.save(run_now=False)
                assert dialog.saved_id>0
                return QDialog.DialogCode.Accepted

            # A failed validation must never open a blocking message box
            # inside the unattended packaged executable self-test.
            with patch('task_runner.gui.message',side_effect=AssertionError('Unexpected GUI error dialog')):
                with patch.object(TaskWizard,'exec',scripted_wizard):
                    dashboard=window.stack.widget(0)
                    new_button=next(button for button in dashboard.findChildren(QPushButton)
                                    if button.text()=='New Task')
                    new_button.click()
                    jobs=window.store.all_jobs()
                    assert len(jobs)==1 and jobs[0]['name']=='GUI smoke test'
                    window.select_task(jobs[0]['id'])
                    edit_button=next(button for button in dashboard.findChildren(QPushButton)
                                     if button.text()=='Edit')
                    edit_button.click()
                    updated=window.store.get_job(jobs[0]['id'])
                    assert updated['name']=='GUI smoke test edited'
                    assert len(updated['actions'])==1
        finally:
            if window is not None:
                window.timer.stop()
                window.scheduler_timer.stop()
                window.debug_timer.stop()
                window.close()
                window.deleteLater()
            if original_home is None:
                os.environ.pop('TASKRUNNER_HOME',None)
            else:
                os.environ['TASKRUNNER_HOME']=original_home


def run_diagnostics(report_path: str | Path) -> bool:
    report={"application":"Task Runner","version":"1.5.1","developer":"Background Gremlin Group","test_started_utc":datetime.now(timezone.utc).isoformat(),
            "python":sys.version,"platform":platform.platform(),
            "frozen":bool(getattr(sys,"frozen",False)),"checks":[]}

    def check(name,callback):
        try:
            callback()
            report["checks"].append({"name":name,"status":"pass"})
        except BaseException as exc:
            report["checks"].append({"name":name,"status":"fail",
                                      "error":f"{type(exc).__name__}: {exc}",
                                      "traceback":traceback.format_exc()})

    def dependencies():
        for package in ("PySide6","playwright","bs4","lxml","croniter","tzlocal",
                        "mss","PIL","pyautogui","pywinauto","pyperclip","cv2","rapidocr","onnxruntime","psutil"):
            importlib.import_module(package)

    def local_ocr():
        from PIL import Image
        from .ocr import _engine, read_region
        assert callable(_engine())
        # First inference initializes lazy ONNX models and catches missing
        # package data in the frozen EXE, regardless of recognized text.
        detected=read_region(image=Image.new('RGB',(128,64),'white'))
        assert isinstance(detected,str)

    def resource_monitor():
        from .resources import sample_resources
        report=sample_resources(os.getpid())
        assert report.pid==os.getpid() and report.process_ram_mb>0
        assert report.total_ram_mb>=report.available_ram_mb>0

    def assets():
        from PIL import Image
        for name in ("task-runner.ico","task-runner.png","select.wav","run.wav","save.wav","done.wav","error.wav","startup.wav","exit.wav"):
            path=asset_path(name)
            if not path.is_file() or path.stat().st_size<100:
                raise FileNotFoundError(f"Missing or empty application asset: {path}")
        with Image.open(asset_path("task-runner.ico")) as icon:
            icon.verify()

    def scheduling():
        from .scheduling import compute_next, utc_now
        assert compute_next("cron",{"expression":"*/5 * * * *"},utc_now())>utc_now()

    def workflow():
        from .store import Store
        from .actions import default_step
        from .executor import WorkflowEngine
        with tempfile.TemporaryDirectory(prefix="task-runner-check-") as temp:
            output=Path(temp)/"report-test.txt"
            doc=default_step("write_file")
            doc["params"].update({"path":str(output),"text":"Windows build test OK"})
            doc["verify"]={"kind":"file_exists","target":str(output),"timeout":1}
            db=Store(Path(temp)/"db.sqlite3")
            job=db.save_job({"name":"Windows build self-test","actions":[doc]})
            execution=db.claim(job,force=True)
            assert WorkflowEngine(db).execute(job,execution)=="success"
            assert output.read_text(encoding="utf-8")=="Windows build test OK"

    def browser():
        setup_browser_path()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            instance=pw.chromium.launch(headless=True)
            try:
                page=instance.new_page()
                page.goto("data:text/html,<title>Task Runner</title><main id='status'>READY</main>")
                assert page.locator("#status").inner_text()=="READY"
                from .collection import expand_browser_controls,capture_browser_scrolling_text
                page.set_content("<details><summary>Show</summary>hidden</details>"
                                 "<select><option>Alpha</option><option>Beta</option></select>"
                                 "<main id='status'>READY</main>")
                expanded=expand_browser_controls(page)
                assert expanded["details_opened"]==1
                assert expanded["select_count"]==1
                extracted,scrolls=capture_browser_scrolling_text(page,max_scrolls=3,pause_seconds=0)
                assert "READY" in extracted
            finally:
                instance.close()

    def gui_import():
        from .gui import MainWindow,TaskWizard,StepEditor
        from .style import APP_STYLE
        assert callable(MainWindow) and callable(TaskWizard) and callable(StepEditor)
        assert "QWidget" in APP_STYLE

    check("All runtime Python modules can import",dependencies)
    check("Icon and all seven audio assets",assets)
    check("Offline OCR models bundled and initialized",local_ocr)
    check("Resource Monitor RAM/process telemetry",resource_monitor)
    check("Time-zone-aware cron engine",scheduling)
    check("SQLite save, claim, execute, verify and persistence",workflow)
    check("Playwright bundled Chromium headless startup",browser)
    check("Main Qt GUI / wizard module import",gui_import)
    check("Real New Task, Edit and action-editor Qt dialog interactions",interactive_dialogs)
    report["passed"]=all(item["status"]=="pass" for item in report["checks"])
    report["test_finished_utc"]=datetime.now(timezone.utc).isoformat()
    path=Path(report_path).expanduser().resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    return report["passed"]
