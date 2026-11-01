"""Launcher: GUI, scheduled heartbeat, and isolated claimed workflow worker."""
import argparse
import sys

def main():
    parser=argparse.ArgumentParser(prog="TaskRunner",description="Windows workflow automation")
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--tick",action="store_true",help="Launch due scheduled tasks and exit")
    group.add_argument("--self-test",action="store_true",help="Run non-destructive packaged-app integration checks")
    group.add_argument("--run-claimed",nargs=2,type=int,metavar=("JOB_ID","EXECUTION_ID"))
    group.add_argument("--install-scheduler",action="store_true")
    group.add_argument("--remove-scheduler",action="store_true")
    parser.add_argument("--data-dir",default=None,help="Persistent data folder for headless scheduled runs")
    parser.add_argument("--report",default=None,help="JSON report path for --self-test")
    options=parser.parse_args()
    if options.data_dir:
        import os
        os.environ["TASKRUNNER_HOME"]=options.data_dir
    if options.self_test:
        from .diagnostics import run_diagnostics
        from .paths import data_root
        return 0 if run_diagnostics(options.report or data_root()/"self-test.json") else 1
    from .runner import tick,run_claimed,install_scheduler,remove_scheduler
    if options.tick:
        tick();return 0
    if options.run_claimed:
        job,execution=options.run_claimed
        return 0 if run_claimed(job,execution)=="success" else 1
    if options.install_scheduler or options.remove_scheduler:
        ok,msg=(install_scheduler() if options.install_scheduler else remove_scheduler())
        print(msg)
        return 0 if ok else 1
    if sys.platform == "win32":
        from .winmouse import enable_dpi_awareness
        enable_dpi_awareness()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from .paths import asset_path, setup_browser_path
    from .gui import MainWindow
    from .style import APP_STYLE
    setup_browser_path()
    app=QApplication(sys.argv)
    app.setApplicationName("Task Runner")
    app.setOrganizationName("Background Gremlin Group")
    app.setOrganizationDomain("background-gremlin-group")
    app.setApplicationVersion("1.4.0")
    app.setStyleSheet(APP_STYLE)
    app.setWindowIcon(QIcon(str(asset_path("task-runner.ico"))))
    window=MainWindow()
    window.show()
    return app.exec()

if __name__=="__main__":sys.exit(main())
