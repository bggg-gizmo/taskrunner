"""Capture *real* PySide6 Task Runner windows, without overwriting user data.

Run on Windows with the installed requirements. No generated mockups, network
access, or screenshots of the user's own tasks or desktop are required.
"""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path


def main():
    if sys.platform!='win32':
        raise SystemExit('UI screenshot capture requires native Windows PySide6')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from task_runner.gui import MainWindow,TaskWizard
    from task_runner.style import APP_STYLE

    root=Path(__file__).resolve().parent.parent
    directory=root/'ui-shots'
    directory.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='taskrunner-ui-capture-') as isolated:
        os.environ['TASKRUNNER_HOME']=isolated
        app=QApplication(sys.argv[:1])
        app.setStyleSheet(APP_STYLE)
        main=MainWindow()
        main.resize(1380,900)
        main.show()
        app.processEvents()
        # Capture actual window pixels; hide the desktop beneath it.
        for index,name in ((0,'01-dashboard'),(1,'02-playback-debugger'),
                           (2,'03-settings-vault'),(3,'04-output-gallery'),(4,'05-resource-monitor')):
            main.set_page(index)
            app.processEvents()
            path=directory/f'{name}.png'
            if not main.grab().save(str(path),'PNG'):
                raise RuntimeError(f'Qt screenshot failed: {path}')
            print(path)
        wizard=TaskWizard(main.store,parent=main)
        wizard.resize(1120,900)
        wizard.show()
        app.processEvents()
        path=directory/'06-task-wizard.png'
        if not wizard.grab().save(str(path),'PNG'):
            raise RuntimeError(f'Qt screenshot failed: {path}')
        print(path)
        wizard.close();main.close()
        app.quit()
    print("Captured actual v1.5 PySide6 widgets without accessing saved workflows.")

if __name__=='__main__':main()
