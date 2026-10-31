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


def run_diagnostics(report_path: str | Path) -> bool:
    report={"application":"Task Runner","version":"1.3.0","developer":"Background Gremlin Group","test_started_utc":datetime.now(timezone.utc).isoformat(),
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
                        "mss","PIL","pyautogui","pywinauto","pyperclip","cv2"):
            importlib.import_module(package)

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
    check("Time-zone-aware cron engine",scheduling)
    check("SQLite save, claim, execute, verify and persistence",workflow)
    check("Playwright bundled Chromium headless startup",browser)
    check("Main Qt GUI / wizard module import",gui_import)
    report["passed"]=all(item["status"]=="pass" for item in report["checks"])
    report["test_finished_utc"]=datetime.now(timezone.utc).isoformat()
    path=Path(report_path).expanduser().resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    return report["passed"]
