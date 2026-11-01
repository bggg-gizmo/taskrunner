"""Task Runner: native Windows control panel and multi-step workflow editor."""
from __future__ import annotations
import copy
import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from PySide6.QtCore import Qt,QDate,QDateTime,QTime,QTimer
from PySide6.QtGui import QIcon,QPixmap
from PySide6.QtWidgets import (
 QApplication,QMainWindow,QDialog,QWidget,QLabel,QPushButton,QCheckBox,
 QVBoxLayout,QHBoxLayout,QFormLayout,QGridLayout,QSplitter,QFrame,
 QLineEdit,QTextEdit,QPlainTextEdit,QListWidget,QListWidgetItem,
 QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,
 QComboBox,QSpinBox,QDoubleSpinBox,QTimeEdit,QDateTimeEdit,QStackedWidget,
 QMessageBox,QInputDialog,QFileDialog,QGroupBox,QSizePolicy,QScrollArea
)
from .actions import ACTIONS,VERIFY_KINDS,default_step,describe_step
from .recorder import DesktopRecorder
from .flow import validate_workflow
from .capture import capture_desktop,CaptureDialog
from .paths import asset_path,data_root
from .scheduling import compute_next,local_text
from .sounds import Preferences
from .store import Store
from .runner import run_claimed,request_stop,install_scheduler,remove_scheduler,scheduler_status,tick


def btn(title,callback=None,primary=False,danger=False):
    b=QPushButton(title)
    if primary:b.setObjectName("Primary")
    if danger:b.setObjectName("Danger")
    if callback:b.clicked.connect(callback)
    return b


def message(parent,title,text,critical=False):
    if critical: QMessageBox.critical(parent,title,str(text))
    else: QMessageBox.information(parent,title,str(text))


def confirm(parent,title,text):
    return QMessageBox.question(parent,title,text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes


def field_value(widget):
    if isinstance(widget,QTextEdit):return widget.toPlainText()
    if isinstance(widget,QLineEdit):return widget.text()
    if isinstance(widget,QComboBox):return widget.currentData() if widget.currentData() is not None else widget.currentText()
    if isinstance(widget,QCheckBox):return widget.isChecked()
    if isinstance(widget,(QSpinBox,QDoubleSpinBox)):return widget.value()
    raise TypeError(type(widget))


class StepEditor(QDialog):
    def __init__(self,step=None,parent=None):
        super().__init__(parent)
        self.setWindowTitle("Action configuration")
        self.resize(640,680)
        self.step=copy.deepcopy(step or default_step("click"))
        root=QVBoxLayout(self)
        form=QFormLayout()
        self.kind=QComboBox()
        for code,action in ACTIONS.items():
            self.kind.addItem(f"{action.category} / {action.name}",code)
        idx=self.kind.findData(self.step["type"])
        self.kind.setCurrentIndex(max(0,idx))
        form.addRow("Action type",self.kind)
        root.addLayout(form)
        self.description=QLabel()
        self.description.setWordWrap(True)
        root.addWidget(self.description)
        scroller=QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        details_surface=QWidget()
        details_layout=QVBoxLayout(details_surface)
        scroller.setWidget(details_surface)
        root.addWidget(scroller,1)
        self.params_box=QGroupBox("Action parameters")
        self.params_form=QFormLayout(self.params_box)
        details_layout.addWidget(self.params_box)
        self.controls={}
        verification=QGroupBox("Optional verification after action")
        vf=QFormLayout(verification)
        self.verify_kind=QComboBox()
        for code,title in VERIFY_KINDS:self.verify_kind.addItem(title,code)
        v=self.step.get("verify",{})
        self.verify_kind.setCurrentIndex(max(0,self.verify_kind.findData(v.get("kind","none"))))
        self.verify_target=QLineEdit(v.get("target",""))
        self.verify_target.setPlaceholderText("Path, window-title substring, CSS selector, or reference PNG")
        browse=btn("Browse…",self.choose_verify_file)
        vl=QHBoxLayout();vl.addWidget(self.verify_target,1);vl.addWidget(browse)
        self.verify_timeout=QDoubleSpinBox();self.verify_timeout.setRange(0,3600)
        self.verify_timeout.setDecimals(1);self.verify_timeout.setValue(float(v.get("timeout",10)))
        vf.addRow("Verification",self.verify_kind)
        help_text=QLabel("Click retries only happen if Windows reports an error or a verification fails. "
                         "Set a window/file/image verification to detect when a click had no effect.")
        help_text.setWordWrap(True);vf.addRow(help_text)
        vf.addRow("Target",vl)
        vf.addRow("Timeout (seconds)",self.verify_timeout)
        details_layout.addWidget(verification)
        resilience=QGroupBox("Retries and timing")
        rf=QFormLayout(resilience)
        self.retries=QSpinBox();self.retries.setRange(0,100)
        self.retries.setValue(int(self.step.get("retry_count",0)))
        self.retry_delay=QDoubleSpinBox();self.retry_delay.setRange(0,3600);self.retry_delay.setDecimals(2)
        self.retry_delay.setValue(float(self.step.get("retry_delay",1)))
        self.delay_before=QDoubleSpinBox();self.delay_before.setRange(0,3600);self.delay_before.setDecimals(2)
        self.delay_before.setValue(float(self.step.get("delay_before",0)))
        self.delay_after=QDoubleSpinBox();self.delay_after.setRange(0,3600);self.delay_after.setDecimals(2)
        self.delay_after.setValue(float(self.step.get("delay_after",0)))
        rf.addRow("Retries after failure",self.retries)
        rf.addRow("Delay between retries (s)",self.retry_delay)
        rf.addRow("Wait BEFORE action (s)",self.delay_before)
        rf.addRow("Wait after action (s)",self.delay_after)
        details_layout.addWidget(resilience)
        details_layout.addStretch()
        footer=QHBoxLayout()
        footer.addStretch()
        footer.addWidget(btn("Cancel",self.reject))
        footer.addWidget(btn("Save action",self.apply,primary=True))
        root.addLayout(footer)
        self.kind.currentIndexChanged.connect(self.build_fields)
        self.verify_kind.currentIndexChanged.connect(self.verification_enabled)
        self.build_fields()
        self.verification_enabled()

    def build_fields(self):
        # Rebuild typed controls when action selection changes.
        while self.params_form.count():
            item=self.params_form.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():
                lay=item.layout()
                while lay.count():
                    child=lay.takeAt(0)
                    if child.widget():child.widget().deleteLater()
        self.controls={}
        code=self.kind.currentData()
        action=ACTIONS[code]
        self.description.setText(action.description)
        saved=self.step.get("params",{}) if code==self.step.get("type") else {}
        for field in action.fields:
            val=saved.get(field.key,field.default)
            if field.kind=="bool":
                control=QCheckBox()
                control.setChecked(bool(val))
            elif field.kind=="choice":
                control=QComboBox()
                control.addItems(field.options)
                control.setCurrentIndex(max(0,control.findText(str(val))))
            elif field.kind=="int":
                control=QSpinBox();control.setRange(-100000000,100000000)
                control.setValue(int(val))
            elif field.kind=="float":
                control=QDoubleSpinBox();control.setRange(0,1000000);control.setDecimals(3)
                control.setValue(float(val))
            elif field.kind=="multiline":
                control=QTextEdit();control.setPlainText(str(val));control.setMaximumHeight(100)
            else:
                control=QLineEdit(str(val))
            if field.kind=="path":
                browse_row=QHBoxLayout()
                browse_row.addWidget(control,1)
                browse_row.addWidget(btn("Browse…",lambda checked=False,key=field.key,widget=control:
                                         self.browse_parameter(key,widget)))
                self.params_form.addRow(field.label,browse_row)
            else:
                self.params_form.addRow(field.label,control)
            self.controls[field.key]=control

    def browse_parameter(self,key,control):
        action=self.kind.currentData()
        current=control.text().strip()
        start=current or str(Path.home())
        if (action in ("mkdir","list_dir") or key=="cwd"
              or (action=="capture_live_start" and key=="destination")
              or (action=="capture_live_start" and key=="source"
                  and field_value(self.controls.get("mode"))=="image_folder")):
            path=QFileDialog.getExistingDirectory(self,"Select folder",start)
        elif action=="open_path":
            choice,ok=QInputDialog.getItem(self,"Choose path type", "Open a file or folder?",
                                         ["File","Folder"],0,False)
            if not ok:return
            if choice=="Folder":path=QFileDialog.getExistingDirectory(self,"Open folder",start)
            else:path,_=QFileDialog.getOpenFileName(self,"Open file",start)
        elif key=="destination" or action in ("write_file","save_clipboard","screenshot",
                                                   "browser_screenshot","browser_download","clipboard_image","capture_program_output") or key=="output":
            path,_=QFileDialog.getSaveFileName(self,"Select output file",start)
        else:
            path,_=QFileDialog.getOpenFileName(self,"Select input file",start)
        if path:control.setText(path)

    def verification_enabled(self):
        active=self.verify_kind.currentData()!="none"
        self.verify_target.setEnabled(active)
        self.verify_timeout.setEnabled(active)

    def choose_verify_file(self):
        file,_=QFileDialog.getOpenFileName(self,"Choose reference PNG",str(data_root()/"captures"),"Images (*.png *.jpg *.jpeg)")
        if file:self.verify_target.setText(file)

    def apply(self):
        code=self.kind.currentData()
        params={key:field_value(widget) for key,widget in self.controls.items()}
        for field in ACTIONS[code].fields:
            if field.required and not str(params[field.key]).strip():
                message(self,"Incomplete action",f"{field.label} is required.",True)
                return
        kind=self.verify_kind.currentData()
        if kind not in ("none","screen_changed") and not self.verify_target.text().strip():
            message(self,"Incomplete verification","Verification target is required.",True)
            return
        if code=="shutdown":
            if not confirm(self,"Confirm shutdown action",
                "This action will request an actual Windows shutdown when the workflow executes, including on a schedule. Include it?"):
                return
        self.step={"type":code,"params":params,
                   "verify":{"kind":kind,"target":self.verify_target.text().strip(),"timeout":self.verify_timeout.value()},
                   "retry_count":self.retries.value(),"retry_delay":self.retry_delay.value(),
                   "delay_before":self.delay_before.value(),"delay_after":self.delay_after.value()}
        self.accept()


class ScheduleEditor(QGroupBox):
    KINDS=[("Manual / Run on demand","manual"),("Once","once"),("Every N seconds","interval"),
           ("Daily","daily"),("Weekly","weekly"),("Cron expression","cron"),
           ("When a file or folder changes","file_event")]

    def __init__(self,kind="manual",config=None,parent=None):
        super().__init__("Schedule",parent)
        config=config or {}
        layout=QVBoxLayout(self)
        self.choice=QComboBox()
        for label,code in self.KINDS:self.choice.addItem(label,code)
        self.stack=QStackedWidget()
        layout.addWidget(self.choice);layout.addWidget(self.stack)
        self.panels={}
        # Page 0: manual.
        manual=QWidget();v=QVBoxLayout(manual);v.addWidget(QLabel("Runs only when started manually."));self.stack.addWidget(manual)
        # Page 1: one-time local wall clock.
        once=QWidget();f=QFormLayout(once)
        self.once=QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600));self.once.setCalendarPopup(True)
        self.once.setDisplayFormat("yyyy-MM-dd HH:mm:ss");f.addRow("Run at (local time)",self.once)
        self.stack.addWidget(once)
        # Page 2: seconds.
        interval=QWidget();f=QFormLayout(interval)
        self.seconds=QSpinBox();self.seconds.setRange(1,31536000);self.seconds.setValue(3600)
        f.addRow("Every (seconds)",self.seconds);self.stack.addWidget(interval)
        # Page 3: daily.
        daily=QWidget();f=QFormLayout(daily)
        self.daily=QTimeEdit(QTime(8,0));self.daily.setDisplayFormat("HH:mm")
        f.addRow("Local time",self.daily);self.stack.addWidget(daily)
        # Page 4: weekly.
        weekly=QWidget();f=QFormLayout(weekly)
        self.weekday=QComboBox();self.weekday.addItems(["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"])
        self.weekly=QTimeEdit(QTime(8,0));self.weekly.setDisplayFormat("HH:mm")
        f.addRow("Day",self.weekday);f.addRow("Local time",self.weekly);self.stack.addWidget(weekly)
        # Page 5: cron.
        cron=QWidget();f=QFormLayout(cron)
        self.cron=QLineEdit("0 8 * * *")
        f.addRow("Minute hour day month weekday",self.cron)
        f.addRow("Example",QLabel("*/15 * * * * = every 15 minutes; local time"))
        self.stack.addWidget(cron)
        watcher=QWidget();wf=QFormLayout(watcher)
        self.watch_path=QLineEdit()
        self.watch_path.setPlaceholderText('C:\\Users\\...\\output.txt')
        wf.addRow('Absolute file/folder path',self.watch_path)
        self.watch_event=QComboBox()
        self.watch_event.addItems(['created','modified','removed','any'])
        wf.addRow('Trigger when',self.watch_event)
        wf.addRow(QLabel('GUI watches every 1s; Windows heartbeat watches about once per minute.'))
        self.stack.addWidget(watcher)
        self.choice.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.choice.setCurrentIndex(max(0,self.choice.findData(kind)))
        if kind=="once" and config.get("at"):
            dt=datetime.fromisoformat(config["at"])
            self.once.setDateTime(QDateTime(QDate(dt.year,dt.month,dt.day),QTime(dt.hour,dt.minute,dt.second)))
        if kind=="interval":self.seconds.setValue(int(config.get("seconds",3600)))
        if kind=="daily":self.daily.setTime(QTime.fromString(config.get("time","08:00"),"HH:mm"))
        if kind=="weekly":
            self.weekday.setCurrentIndex(int(config.get("weekday",0)))
            self.weekly.setTime(QTime.fromString(config.get("time","08:00"),"HH:mm"))
        if kind=="cron":self.cron.setText(str(config.get("expression","0 8 * * *")))
        if kind=='file_event':
            self.watch_path.setText(str(config.get('path','')))
            self.watch_event.setCurrentIndex(max(0,self.watch_event.findText(config.get('event','modified'))))

    def result(self):
        kind=self.choice.currentData()
        if kind=="manual":config={}
        elif kind=="once": config={"at":self.once.dateTime().toString("yyyy-MM-ddTHH:mm:ss")}
        elif kind=="interval":config={"seconds":self.seconds.value()}
        elif kind=="daily":config={"time":self.daily.time().toString("HH:mm")}
        elif kind=="weekly":config={"weekday":self.weekday.currentIndex(),"time":self.weekly.time().toString("HH:mm")}
        elif kind=='cron':config={"expression":self.cron.text().strip()}
        else:config={'path':self.watch_path.text().strip(),'event':self.watch_event.currentText()}
        compute_next(kind,config)
        return kind,config


class TaskWizard(QDialog):
    def __init__(self,store:Store,job=None,parent=None):
        super().__init__(parent)
        self.store=store
        self.previous=copy.deepcopy(job or {})
        self.actions=copy.deepcopy(self.previous.get("actions",[]))
        self.run_after_save=False
        self.recorder=None
        self.recording_timer=None
        self.recording_started=0.0
        self.setWindowTitle("Task Runner — Task Setup Wizard")
        self.resize(1040,850)
        root=QVBoxLayout(self)
        scroller=QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        content=QWidget()
        content_layout=QVBoxLayout(content)
        scroller.setWidget(content)
        root.addWidget(scroller,1)
        header=QLabel("TASK SETUP WIZARD");header.setObjectName("Hero")
        content_layout.addWidget(header)
        content_layout.addWidget(QLabel("Create a complete action sequence. Capture desktop targets, expand dropdowns, collect scrolling text, and set timed waits."))
        details=QGroupBox("1 · Task details")
        f=QFormLayout(details)
        self.name=QLineEdit(self.previous.get("name",""))
        self.name.setPlaceholderText("Meaningful job name")
        self.description=QLineEdit(self.previous.get("description",""))
        self.enabled=QCheckBox("Enabled");self.enabled.setChecked(bool(self.previous.get("enabled",True)))
        f.addRow("Name",self.name);f.addRow("Description",self.description);f.addRow("State",self.enabled)
        content_layout.addWidget(details)
        work=QGroupBox("2 · Action sequence and screen selection")
        v=QVBoxLayout(work)
        controls=QHBoxLayout()
        controls.addWidget(btn("Capture full screen + select",lambda:self.begin_capture("click"),primary=True))
        controls.addWidget(btn("Select area + type",lambda:self.begin_capture("type")))
        controls.addWidget(btn("Capture trigger area",lambda:self.begin_capture("condition")))
        controls.addWidget(btn("Add action",lambda:self.add_action()))
        controls.addWidget(btn("● Record actions / Replay",self.begin_recording,primary=True))
        controls.addStretch()
        v.addLayout(controls)
        capture_control=QHBoxLayout()
        capture_control.addWidget(QLabel("Capture delay (seconds):"))
        self.capture_delay=QSpinBox();self.capture_delay.setRange(0,30);self.capture_delay.setValue(0)
        self.capture_delay.setToolTip("Set 5–10 seconds to open a right-click menu or a transient dropdown after hiding Task Runner.")
        capture_control.addWidget(self.capture_delay)
        capture_control.addWidget(btn("Capture RIGHT-CLICK MENU in 5s",lambda:self.begin_capture("click",5),primary=True))
        capture_control.addStretch()
        v.addLayout(capture_control)
        v.addWidget(QLabel("Recording: Task Runner hides, you perform the task, and Ctrl+Shift+F12 stops capture. "
                           "It saves mouse/keyboard actions and measured pauses for later replay."))
        v.addWidget(QLabel("For transient menus: click the timed-capture button, right-click in your program, and keep the menu open until the screenshot freezes."))
        quick=QGroupBox("Quick actions · no screenshot required")
        quick_grid=QGridLayout(quick)
        shortcuts=[("Expand webpage menus", "browser_expand_all"),
                   ("Inspect program dropdowns", "desktop_expand_all"),
                   ("Copy scrolling webpage text", "browser_scroll_text"),
                   ("Copy scrolling program text", "desktop_scroll_text"),
                   ("Pause / delay", "wait"),
                   ("Run reusable task module", "run_module"),
                   ("Load protected credential", "load_secret"),
                   ("Wait for program window", "wait_window"),
                   ("Wait for file", "wait_file"),
                   ("Wait for browser element", "browser_wait_state"),
                   ("Choose dropdown option", "browser_select"),
                   ("Wait for screen/image change", "wait_screen"),
                   ("Wait for visible text (offline OCR)", "wait_ocr"),
                   ("Click matching on-screen image", "click_image"),
                   ("Wait for output/text", "wait_content"),
                   ("Start saving live output/images", "capture_live_start"),
                   ("Stop live capture", "capture_live_stop"),
                   ("Save clipboard image", "clipboard_image"),
                   ("Stream program output", "capture_program_output")]
        for index,(label,kind) in enumerate(shortcuts):
            quick_grid.addWidget(btn(label,lambda checked=False,k=kind:self.add_action(k)),index//3,index%3)
        v.addWidget(quick)
        v.addWidget(btn("Apply retry + timing settings across existing actions…",self.bulk_timing))
        row=QHBoxLayout()
        self.steps=QListWidget()
        self.steps.setMinimumHeight(190)
        self.steps.itemDoubleClicked.connect(lambda _:self.edit_action())
        row.addWidget(self.steps,1)
        movement=QVBoxLayout()
        movement.addWidget(btn("Edit",self.edit_action))
        movement.addWidget(btn("Remove",self.remove_action,danger=True))
        movement.addWidget(btn("Move ↑",lambda:self.move_action(-1)))
        movement.addWidget(btn("Move ↓",lambda:self.move_action(1)))
        movement.addStretch()
        row.addLayout(movement)
        v.addLayout(row)
        self.capture_preview=QLabel("Desktop screenshot preview appears here after capture")
        self.capture_preview.setMinimumHeight(110)
        self.capture_preview.setMaximumHeight(175)
        self.capture_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.capture_preview.setStyleSheet("border: 1px dashed #415b85; color: #9eb4d6;")
        v.addWidget(self.capture_preview)
        content_layout.addWidget(work,1)
        self.schedule=ScheduleEditor(self.previous.get("schedule_kind","manual"),self.previous.get("schedule",{}))
        content_layout.addWidget(self.schedule)
        foot=QHBoxLayout()
        self.summary=QLabel("")
        foot.addWidget(self.summary,1)
        foot.addWidget(btn("Validate workflow",self.validate))
        foot.addWidget(btn("Cancel",self.reject))
        foot.addWidget(btn("Save + Run now",lambda:self.save(run_now=True)))
        foot.addWidget(btn("Verify & save task",self.save,primary=True))
        root.addLayout(foot)
        self.refresh_actions()

    def refresh_actions(self,chosen=None):
        previous=self.steps.currentRow() if chosen is None else chosen
        self.steps.clear()
        depth=0
        for idx,step in enumerate(self.actions,start=1):
            code=step.get("type")
            if code in ("else","endif","end_repeat"):
                depth=max(0,depth-1)
            prefix="✓ " if step.get("verify",{}).get("kind","none")!="none" else "   "
            self.steps.addItem(f"{idx:02d}. {prefix}{'    '*depth}{describe_step(step)}")
            if code in ("if_var","repeat","else"):
                depth+=1
        if self.actions:self.steps.setCurrentRow(min(max(0,previous),len(self.actions)-1))
        configured=sum(bool(s.get("retry_count",0)) for s in self.actions)
        self.summary.setText(f"{len(self.actions)} actions  ·  {configured} with retries  ·  Configure verification to retry unsuccessful clicks (not just exceptions)")

    def add_action(self,action_type=None):
        editor=StepEditor(default_step(action_type) if action_type else None,parent=self)
        if editor.exec()==QDialog.DialogCode.Accepted:
            idx=self.steps.currentRow()
            insert=idx+1 if idx>=0 else len(self.actions)
            self.actions.insert(insert,editor.step)
            self.refresh_actions(insert)

    def bulk_timing(self):
        if not self.actions:
            message(self,"No actions", "Add actions before applying workflow-wide timing.")
            return
        dialog=QDialog(self);dialog.setWindowTitle("Workflow-wide retries and timing")
        form=QFormLayout(dialog)
        retries=QSpinBox();retries.setRange(0,100);retries.setValue(2)
        retry_delay=QDoubleSpinBox();retry_delay.setRange(0,3600);retry_delay.setDecimals(2);retry_delay.setValue(1.0)
        before=QDoubleSpinBox();before.setRange(0,3600);before.setDecimals(2);before.setValue(0.0)
        after=QDoubleSpinBox();after.setRange(0,3600);after.setDecimals(2);after.setValue(1.0)
        overwrite=QCheckBox("Replace existing custom step delays and retries")
        overwrite.setChecked(False)
        form.addRow("Retries after failure",retries)
        form.addRow("Between retries (seconds)",retry_delay)
        form.addRow("Wait BEFORE action (seconds)",before)
        form.addRow("Wait AFTER action (seconds)",after)
        form.addRow(overwrite)
        notice=QLabel("Only execution settings change, never action parameters or verification. "
                      "With replacement off, only absent/zero retry or delay fields are filled.")
        notice.setWordWrap(True);form.addRow(notice)
        buttons=QHBoxLayout()
        buttons.addWidget(btn("Cancel",dialog.reject))
        buttons.addWidget(btn("Apply to all steps",dialog.accept,primary=True))
        form.addRow(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        count=0
        for step in self.actions:
            values={"retry_count":retries.value(),"retry_delay":retry_delay.value(),
                    "delay_before":before.value(),"delay_after":after.value()}
            for key,value in values.items():
                if overwrite.isChecked() or not step.get(key):
                    step[key]=value
            count+=1
        self.refresh_actions()
        message(self,"Workflow timing applied",f"Updated timing/retry settings on {count} actions. Save the task to persist these changes.")

    def edit_action(self):
        idx=self.steps.currentRow()
        if idx<0:return
        editor=StepEditor(self.actions[idx],self)
        if editor.exec()==QDialog.DialogCode.Accepted:
            self.actions[idx]=editor.step
            self.refresh_actions(idx)

    def remove_action(self):
        i=self.steps.currentRow()
        if i>=0:
            self.actions.pop(i)
            self.refresh_actions(min(i,len(self.actions)-1))

    def move_action(self,delta):
        i=self.steps.currentRow();j=i+delta
        if 0<=i<len(self.actions) and 0<=j<len(self.actions):
            self.actions[i],self.actions[j]=self.actions[j],self.actions[i]
            self.refresh_actions(j)

    def begin_capture(self,mode,override_delay=None):
        # No focus stealing between user opening a context menu and the capture.
        # The screenshot freezes before the wizard is re-shown, preserving popups.
        seconds=self.capture_delay.value() if override_delay is None else override_delay
        if seconds:
            message(self,"Armed screen capture",
                    f"After selecting OK, Task Runner will hide. Open the menu/dropdown "
                    f"you want to capture. The screenshot will be taken after {seconds} seconds. "
                    "Do not click back into Task Runner before then.")
        parent=self.parentWidget()
        if parent:parent.hide()
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(max(700,int(seconds*1000)),lambda:self.finish_capture(mode,parent))

    def finish_capture(self,mode,parent):
        try:
            file,left,top=capture_desktop()
        except Exception as exc:
            if parent:parent.show()
            self.show()
            message(self,"Screen capture failed",exc,True)
            return
        if parent:parent.show()
        self.show()
        self.raise_();self.activateWindow()
        preview=QPixmap(str(file)).scaled(780,170,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        self.capture_preview.setPixmap(preview)
        picker=CaptureDialog(file,left,top,self)
        if picker.exec()!=QDialog.DialogCode.Accepted:return
        selected=picker.selection
        if mode=="condition":
            options=["Wait until selected region changes","Wait for reference image to appear","Click matching reference image"]
            choice,ok=QInputDialog.getItem(self,"Visual trigger","What should happen?",options,0,False)
            if not ok:return
            x,y,w,h=picker.reference_region()
            area=f"{x+left},{y+top},{w},{h}"
            if choice==options[0]:
                step=default_step("wait_screen")
                step["params"]["region"]=area
            elif choice==options[1]:
                step=default_step("wait_screen")
                step["params"].update({"mode":"image_appears","region":area,"image":str(picker.save_region())})
            else:
                step=default_step("click_image")
                step["params"].update({"image":str(picker.save_region()),"region":""})
            self.actions.append(step)
            self.refresh_actions(len(self.actions)-1)
            return
        if mode=="click":
            options=["Click once","Double-click","Right-click",
                     "Save region as verification image",
                     "Verify selected action changes this screen region"]
            choice,ok=QInputDialog.getItem(self,"Selected region","What action should this selection perform?",options,0,False)
            if not ok:return
            if choice.startswith("Verify selected action"):
                index=self.steps.currentRow()
                if index < 0:
                    message(self,"No selected action","Select the action whose effect you want to verify.",True)
                    return
                x,y,w,h=picker.reference_region()
                self.actions[index]["verify"]={"kind":"screen_changed",
                     "target":f"{x+left},{y+top},{w},{h}","timeout":10.0}
                self.actions[index]["retry_count"]=max(2,int(self.actions[index].get("retry_count",0)))
                self.refresh_actions(index)
                return
            if choice.startswith("Save region"):
                path=picker.save_region()
                if self.steps.currentRow()<0:
                    message(self,"No selected action","Select a workflow action to attach this screenshot verification.",True)
                    return
                step=self.actions[self.steps.currentRow()]
                step["verify"]={"kind":"image_visible","target":str(path),"timeout":10.0}
                self.refresh_actions()
                return
            step=default_step("click")
            step["params"].update({"x":selected["x"],"y":selected["y"],
                                   "clicks":2 if choice=="Double-click" else 1,
                                   "button":"right" if choice=="Right-click" else "left"})
            self.actions.append(step)
        else:
            body,ok=QInputDialog.getMultiLineText(self,"Text for selected input area","Enter the exact text to type after clicking the selected area:")
            if not ok:return
            click=default_step("click")
            click["params"].update({"x":selected["x"],"y":selected["y"]})
            typing=default_step("type")
            typing["params"]["text"]=body
            self.actions.extend([click,typing])
        self.refresh_actions(len(self.actions)-1)

    def validate(self):
        try:
            if not self.name.text().strip():
                raise ValueError("A task name is required")
            validate_workflow(self.actions)
            kind,config=self.schedule.result()
            if kind=="once" and compute_next(kind,config) is None:
                raise ValueError("The one-time schedule must be in the future")
        except Exception as exc:
            message(self,"Workflow validation failed",exc,True)
            return False
        message(self,"Workflow validated",
                f"All {len(self.actions)} actions have valid parameters and structured blocks. "
                "This is a configuration check; no external application has been modified or executed.")
        return True

    def save(self,run_now=False):
        if not self.name.text().strip():
            message(self,"Name required","Enter a task name.",True);return
        if not self.actions:
            message(self,"Actions required","Add at least one workflow step.",True);return
        try:
            validate_workflow(self.actions)
            kind,config=self.schedule.result()
            if kind=="once" and compute_next(kind,config) is None:
                raise ValueError("One-time schedule must be in the future")
            doc={"id":self.previous.get("id"),"name":self.name.text().strip(),
                 "description":self.description.text(),"enabled":self.enabled.isChecked(),
                 "actions":self.actions,"schedule_kind":kind,"schedule":config}
            self.saved_id=self.store.save_job(doc)
            self.run_after_save=bool(run_now)
        except Exception as exc:
            message(self,"Could not save task",exc,True);return
        self.accept()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store=Store();self.preferences=Preferences()
        self.active_workers={}
        self._restore_after_run=set()
        self.selected_job=None
        self.setWindowTitle("Task Runner — Automation Control Panel")
        self.setWindowIcon(QIcon(str(asset_path("task-runner.ico"))))
        self.resize(1240,840)
        root=QWidget();self.setCentralWidget(root)
        horizontal=QHBoxLayout(root);horizontal.setContentsMargins(10,10,10,10)
        navigation=QFrame();navigation.setObjectName("Panel");navigation.setFixedWidth(185)
        nav=QVBoxLayout(navigation)
        icon=QLabel()
        art=QPixmap(str(asset_path("task-runner.png")))
        icon.setPixmap(art.scaled(140,140,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(icon)
        nav.addWidget(btn("Dashboard",lambda:self.set_page(0),primary=True))
        nav.addWidget(btn("+ New Task",self.new_task))
        nav.addWidget(btn("Execution Logs",lambda:self.set_page(1)))
        nav.addWidget(btn("Output Gallery",lambda:self.set_page(3)))
        nav.addWidget(btn("Settings",lambda:self.set_page(2)))
        nav.addStretch()
        nav.addWidget(QLabel("TASK RUNNER  /  1.4.0"))
        by=QLabel("BACKGROUND GREMLIN GROUP")
        by.setWordWrap(True);by.setObjectName("Muted");nav.addWidget(by)
        motto=QLabel("Creating Unique Tools\nfor Unique Individuals")
        motto.setWordWrap(True);motto.setObjectName("Muted");nav.addWidget(motto)
        nav.addWidget(QLabel("SCHEDULE • AUTOMATE"))
        horizontal.addWidget(navigation)
        main=QVBoxLayout();horizontal.addLayout(main,1)
        hero=QHBoxLayout()
        heading=QLabel("TASK RUNNER");heading.setObjectName("Hero");hero.addWidget(heading)
        hero.addStretch()
        self.agent_label=QLabel()
        hero.addWidget(self.agent_label)
        main.addLayout(hero)
        subtitle=QLabel("DESKTOP + BROWSER AUTOMATION  /  WORKFLOW CONTROL")
        subtitle.setObjectName("Muted");main.addWidget(subtitle)
        self.stack=QStackedWidget()
        main.addWidget(self.stack,1)
        self.build_dashboard()
        self.build_logs()
        self.build_settings()
        self.build_gallery()
        self.set_page(0)
        self.statusBar().showMessage("Ready — use New Task to configure a workflow")
        self.timer=QTimer(self);self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.scheduler_timer=QTimer(self);self.scheduler_timer.setInterval(1000)
        self.scheduler_timer.timeout.connect(self.check_due)
        self.scheduler_timer.start()
        initial_runs = self.store.execution_history(limit=200)
        self.last_seen_run = max((r["id"] for r in initial_runs),default=0)
        self.previous_run_states = {r["id"]:r["status"] for r in initial_runs}
        self.refresh()
        QTimer.singleShot(200,lambda:self.preferences.play("startup"))

    def build_dashboard(self):
        page=QWidget();layout=QVBoxLayout(page)
        toolbar=QHBoxLayout()
        toolbar.addWidget(btn("New Task",self.new_task,primary=True))
        toolbar.addWidget(btn("Run now",self.run_selected))
        toolbar.addWidget(btn("▶ Debug replay",self.run_debug_selected,primary=True))
        toolbar.addWidget(btn("Stop",self.stop_selected,danger=True))
        toolbar.addWidget(btn("Edit",self.edit_selected))
        toolbar.addWidget(btn("Duplicate",self.duplicate_selected))
        toolbar.addWidget(btn("Enable / Disable",self.toggle_selected))
        toolbar.addWidget(btn("Delete",self.delete_selected,danger=True))
        toolbar.addWidget(btn("Import JSON",self.import_task))
        toolbar.addWidget(btn('Import package',self.import_portable))
        toolbar.addWidget(btn('Export package',self.export_portable))
        toolbar.addWidget(btn("Export JSON",self.export_selected))
        toolbar.addWidget(btn("Refresh",self.refresh))
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.task_count=QLabel("All tasks")
        self.task_count.setObjectName("SectionTitle")
        layout.addWidget(self.task_count)
        self.table=QTableWidget(0,7)
        self.table.setHorizontalHeaderLabels(["ID","Task","State","Schedule","Next run","Last run","Description"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6,QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda *_:self.edit_selected())
        layout.addWidget(self.table,1)
        caption=QLabel("Double-click a task to edit it. Scheduled desktop actions require an unlocked Windows user session.")
        caption.setObjectName("Muted")
        layout.addWidget(caption)
        self.stack.addWidget(page)

    def build_logs(self):
        page=QWidget();vertical=QVBoxLayout(page)
        bar=QHBoxLayout()
        name=QLabel("Execution history");name.setObjectName("SectionTitle")
        bar.addWidget(name);bar.addStretch()
        bar.addWidget(btn("Export selected log",self.export_run_log))
        bar.addWidget(btn('Resume failed run…',self.resume_from_checkpoint))
        bar.addWidget(btn("Refresh logs",self.refresh_logs))
        vertical.addLayout(bar)
        split=QSplitter(Qt.Orientation.Vertical)
        self.runs=QTableWidget(0,5)
        self.runs.setHorizontalHeaderLabels(["Run ID","Task","Started","Finished","State"])
        self.runs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.runs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.runs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.runs.verticalHeader().setVisible(False)
        self.runs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.runs.itemSelectionChanged.connect(self.show_run)
        split.addWidget(self.runs)
        self.run_details=QPlainTextEdit()
        self.run_details.setReadOnly(True)
        split.addWidget(self.run_details)
        split.setSizes([360,320])
        vertical.addWidget(split,1)
        debug=QGroupBox("Playback Debugger · Live Timeline / Teach a Click")
        panel=QVBoxLayout(debug)
        buttons=QHBoxLayout()
        buttons.addWidget(btn("⏸ Pause",lambda:self.debug_command('pause')))
        buttons.addWidget(btn('⏹ Emergency stop',lambda:self.debug_command('cancel'),danger=True))
        buttons.addWidget(btn("▶ Continue",lambda:self.debug_command('run'),primary=True))
        buttons.addWidget(btn("Step once",lambda:self.debug_command('step')))
        buttons.addWidget(btn("Retry failed step",lambda:self.debug_command('retry')))
        buttons.addWidget(btn("Teach current click…",self.teach_debug_click))
        buttons.addStretch()
        panel.addLayout(buttons)
        self.debug_status_label=QLabel("Select a debug run to inspect its live actions and screenshots")
        self.debug_status_label.setObjectName("Muted")
        panel.addWidget(self.debug_status_label)
        timeline=QHBoxLayout()
        self.debug_steps=QListWidget()
        self.debug_steps.setMinimumHeight(110)
        self.debug_steps.setMaximumHeight(210)
        self.debug_steps.itemSelectionChanged.connect(self.show_debug_capture)
        timeline.addWidget(self.debug_steps,2)
        self.debug_image=QLabel("Per-step capture preview · local only")
        self.debug_image.setObjectName("Muted")
        self.debug_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.debug_image.setMinimumSize(220,110)
        self.debug_image.setMaximumHeight(210)
        timeline.addWidget(self.debug_image,2)
        panel.addLayout(timeline)
        vertical.addWidget(debug)
        self.debug_timer=QTimer(self)
        self.debug_timer.setInterval(500)
        self.debug_timer.timeout.connect(self.refresh_debugger)
        self.debug_timer.start()
        self.stack.addWidget(page)

    def build_gallery(self):
        page=QWidget();vertical=QVBoxLayout(page)
        title=QLabel('OUTPUT CAPTURE GALLERY');title.setObjectName('SectionTitle');vertical.addWidget(title)
        bar=QHBoxLayout()
        self.gallery_root=QLineEdit(str(data_root()/'captures'))
        self.gallery_root.setReadOnly(True)
        bar.addWidget(self.gallery_root,1)
        bar.addWidget(btn('Choose folder…',self.gallery_choose))
        bar.addWidget(btn('Refresh',self.gallery_refresh))
        bar.addWidget(btn('Export capture bundle…',self.gallery_export))
        vertical.addLayout(bar)
        main=QSplitter(Qt.Orientation.Horizontal)
        self.gallery_list=QListWidget()
        self.gallery_list.itemSelectionChanged.connect(self.gallery_show)
        main.addWidget(self.gallery_list)
        detail=QWidget();detail_layout=QVBoxLayout(detail)
        self.gallery_preview=QLabel('Select a captured image or output text to preview')
        self.gallery_preview.setObjectName('Muted')
        self.gallery_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gallery_preview.setMinimumHeight(220)
        detail_layout.addWidget(self.gallery_preview,2)
        self.gallery_text=QPlainTextEdit();self.gallery_text.setReadOnly(True)
        detail_layout.addWidget(self.gallery_text,1)
        detail_layout.addWidget(btn('Copy selected file path',self.gallery_copy))
        main.addWidget(detail);main.setSizes([430,650])
        vertical.addWidget(main,1)
        self.gallery_summary=QLabel('Local captures only. Contents may include private desktop data.')
        self.gallery_summary.setObjectName('Muted');vertical.addWidget(self.gallery_summary)
        self._gallery_entries=[]
        self.stack.addWidget(page)
        self.gallery_refresh()

    def gallery_choose(self):
        folder=QFileDialog.getExistingDirectory(self,'Select captured-output folder',self.gallery_root.text())
        if folder:self.gallery_root.setText(folder);self.gallery_refresh()

    def gallery_refresh(self):
        from .gallery import gallery_entries,duplicates
        folder=Path(self.gallery_root.text())
        if not folder.exists():folder.mkdir(parents=True,exist_ok=True)
        try:
            self._gallery_entries=gallery_entries(folder)
            duplicated=duplicates(self._gallery_entries)
        except Exception as error:
            self._gallery_entries=[]
            message(self,'Capture gallery unavailable',error,True)
        self.gallery_list.clear()
        for entry in self._gallery_entries:
            icon='▣' if entry['kind']=='image' else '≡'
            self.gallery_list.addItem(f'{icon}  {entry["relative"]}  ·  {entry["bytes"]:,} bytes')
        self.gallery_summary.setText(
            f'{len(self._gallery_entries)} local captures  ·  {len(duplicated) if self._gallery_entries else 0} duplicate groups  '
            '·  Select Export to create a private archive with SHA-256 manifest')

    def gallery_show(self):
        index=self.gallery_list.currentRow()
        if not 0<=index<len(self._gallery_entries):return
        entry=self._gallery_entries[index]
        path=Path(entry['path'])
        self.gallery_preview.setPixmap(QPixmap())
        self.gallery_text.clear()
        if entry['kind']=='image':
            image=QPixmap(str(path))
            if image.isNull():self.gallery_preview.setText('Image preview unavailable')
            else:self.gallery_preview.setPixmap(image.scaled(650,350,Qt.AspectRatioMode.KeepAspectRatio,
                                                             Qt.TransformationMode.SmoothTransformation))
        else:
            self.gallery_preview.setText(entry['relative'])
            with path.open('r',encoding='utf-8',errors='replace') as stream:
                self.gallery_text.setPlainText(stream.read(250000))

    def gallery_copy(self):
        i=self.gallery_list.currentRow()
        if not 0<=i<len(self._gallery_entries):return
        QApplication.clipboard().setText(self._gallery_entries[i]['path'])
        self.statusBar().showMessage('Captured file path copied')

    def gallery_export(self):
        from .gallery import export_gallery
        if not self._gallery_entries:
            message(self,'Nothing to export','Choose a folder with captured output first.');return
        if not confirm(self,'Export private captures',
                       'This archive will include screenshots and text that may contain private information. Export it?'):
            return
        suggested=str(Path.home()/'TaskRunner-Captures.zip')
        path,_=QFileDialog.getSaveFileName(self,'Export capture archive',suggested,'Zip archives (*.zip)')
        if not path:return
        try:
            result=export_gallery(self.gallery_root.text(),path,self._gallery_entries)
            message(self,'Capture export complete',f'Saved {len(self._gallery_entries)} files to {result}')
        except Exception as error:message(self,'Export failed',error,True)

    def build_settings(self):
        page=QWidget();layout=QVBoxLayout(page)
        name=QLabel("Application Settings");name.setObjectName("SectionTitle")
        layout.addWidget(name)
        audio=QGroupBox("Retro interface audio")
        a=QVBoxLayout(audio)
        self.sounds_toggle=QCheckBox("Play original Windows 95-inspired interface sound effects")
        self.sounds_toggle.setChecked(bool(self.preferences.get("sounds")))
        self.sounds_toggle.toggled.connect(self.set_sound)
        a.addWidget(self.sounds_toggle)
        a.addWidget(btn("Test sound",lambda:self.preferences.play("select")))
        layout.addWidget(audio)
        vault=QGroupBox('Local credential vault · Windows DPAPI')
        vault_layout=QHBoxLayout(vault)
        vault_layout.addWidget(btn('Store / update secret…',self.vault_save))
        vault_layout.addWidget(btn('Delete secret…',self.vault_delete,danger=True))
        vault_layout.addWidget(QLabel('Secrets are encrypted for this Windows account; not included in JSON exports.'))
        layout.addWidget(vault)
        options=QGroupBox("Execution safety and diagnostics")
        o=QVBoxLayout(options)
        self.failure_captures=QCheckBox("Save desktop screenshot after a failed workflow (contains desktop contents)")
        self.failure_captures.setChecked(bool(self.preferences.get("save_failure_screenshots")))
        self.failure_captures.toggled.connect(lambda checked:self.preferences.set("save_failure_screenshots",checked))
        o.addWidget(self.failure_captures)
        self.minimize_on_run=QCheckBox("Minimize Task Runner while manually running desktop mouse/keyboard workflows; restore at completion")
        self.minimize_on_run.setChecked(bool(self.preferences.get("minimize_during_manual_runs")))
        self.minimize_on_run.toggled.connect(lambda checked:self.preferences.set("minimize_during_manual_runs",checked))
        o.addWidget(self.minimize_on_run)
        o.addWidget(QLabel("Move the mouse to the primary screen's top-left corner to trigger PyAutoGUI fail-safe."))
        o.addWidget(QLabel("Jobs that click/type must run in an interactive, unlocked Windows desktop session."))
        layout.addWidget(options)
        scheduler=QGroupBox("Windows Task Scheduler integration")
        s=QVBoxLayout(scheduler)
        self.scheduler_label=QLabel()
        s.addWidget(self.scheduler_label)
        s.addWidget(QLabel("A lightweight task runs every minute while logged in to launch due workflows without the GUI."))
        row=QHBoxLayout()
        row.addWidget(btn("Install / update scheduler",self.install_agent,primary=True))
        row.addWidget(btn("Remove scheduler",self.remove_agent,danger=True))
        row.addStretch()
        s.addLayout(row)
        layout.addWidget(scheduler)
        paths=QGroupBox("Storage")
        p=QFormLayout(paths)
        p.addRow("Database and logs",QLabel(str(data_root())))
        p.addRow("Screenshots",QLabel(str(data_root()/"captures")))
        p.addRow("Backup",btn("Backup task database…",self.backup_tasks))
        layout.addWidget(paths)
        credits=QGroupBox("About Task Runner")
        credits_layout=QVBoxLayout(credits)
        credits_layout.addWidget(QLabel("Task Runner v1.4.0  ·  Vaporwave Edition"))
        credits_layout.addWidget(QLabel("Developed by the Background Gremlin Group"))
        credits_layout.addWidget(QLabel("Creating Unique Tools for Unique Individuals"))
        layout.addWidget(credits)
        layout.addStretch()
        self.stack.addWidget(page)

    def set_page(self,index):
        self.stack.setCurrentIndex(index)
        if index==1:self.refresh_logs()
        if index==2:self.refresh_scheduler_label()

    def refresh_scheduler_label(self):
        self.scheduler_label.setText("Scheduler: " + ("installed" if scheduler_status() else "not installed"))
        self.agent_label.setText("● Scheduler enabled" if scheduler_status() else "○ Scheduler not installed")

    def set_sound(self,checked):
        self.preferences.set("sounds",checked)
        if checked:self.preferences.play("select")

    def selected_id(self):
        row=self.table.currentRow()
        if row<0:return None
        item=self.table.item(row,0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def require_selection(self):
        selected=self.selected_id()
        if selected is None:message(self,"Choose a task","Select a task in the dashboard first.")
        return selected

    def new_task(self):
        wizard=TaskWizard(self.store,parent=self)
        if wizard.exec()==QDialog.DialogCode.Accepted:
            self.preferences.play("save")
            self.refresh()
            self.select_task(wizard.saved_id)
            if wizard.run_after_save:self.run_selected()

    def edit_selected(self):
        job_id=self.require_selection()
        if job_id is None:return
        job=self.store.get_job(job_id)
        if job["status"]=="running":
            message(self,"Task is running","Stop the current execution before editing this task.")
            return
        wizard=TaskWizard(self.store,job,parent=self)
        if wizard.exec()==QDialog.DialogCode.Accepted:
            self.preferences.play("save")
            self.refresh();self.select_task(wizard.saved_id)
            if wizard.run_after_save:self.run_selected()

    def select_task(self,job_id):
        for row in range(self.table.rowCount()):
            item=self.table.item(row,0)
            if item and item.data(Qt.ItemDataRole.UserRole)==job_id:
                self.table.selectRow(row);break

    def backup_tasks(self):
        filename,_=QFileDialog.getSaveFileName(self,"Backup Task Runner jobs and logs",
                            str(Path.home()/"task-runner-backup.sqlite3"),"SQLite database (*.sqlite3)")
        if not filename:return
        try:
            path=self.store.backup_database(Path(filename))
        except Exception as exc:
            message(self,"Backup failed",exc,True)
            return
        self.preferences.play("save")
        message(self,"Backup completed",f"Consistent jobs/history backup saved to:\n{path}\n\n"
                "Keep it private: saved workflows and execution logs can contain sensitive information."
                " Personal settings and screenshot files are not included.")

    def export_selected(self):
        job_id=self.require_selection()
        if job_id is None:return
        task=self.store.get_job(job_id)
        if not task:return
        # Export only portable user-editable configuration, never internal run state.
        document={"format":"TaskRunnerJob","version":1,
                  "job":{key:task[key] for key in
                         ("name","description","enabled","schedule_kind","schedule","actions")}}
        document["job"]["enabled"] = bool(task["enabled"])
        filename,_=QFileDialog.getSaveFileName(self,"Export task JSON",
                        str(Path.home() / f"task-runner-{job_id}.json"),"JSON (*.json)")
        if not filename:return
        try:
            Path(filename).write_text(json.dumps(document,indent=2,ensure_ascii=False),encoding="utf-8")
        except Exception as exc:message(self,"Export failed",exc,True);return
        self.preferences.play("save")
        self.statusBar().showMessage(f"Exported task {job_id} to {filename}")

    def import_task(self):
        filename,_=QFileDialog.getOpenFileName(self,"Import Task Runner job",str(Path.home()),"JSON (*.json)")
        if not filename:return
        try:
            document=json.loads(Path(filename).read_text(encoding="utf-8-sig"))
            if not isinstance(document,dict) or document.get("format")!="TaskRunnerJob" or document.get("version")!=1:
                raise ValueError("Not a supported Task Runner job export (format version 1)")
            job=document["job"]
            if not isinstance(job,dict):raise ValueError("Invalid job object")
            # Imported tasks never schedule themselves before the owner reviews them.
            job={key:job[key] for key in ("name","description","schedule_kind","schedule","actions")}
            job["enabled"]=False
            job["name"]+=" (imported)"
            job_id=self.store.save_job(job)
        except Exception as exc:message(self,"Import failed",exc,True);return
        self.preferences.play("save")
        self.refresh();self.select_task(job_id)
        message(self,"Task imported","Task imported in disabled state. Review its actions and schedule before enabling it.")

    def export_portable(self):
        job_id=self.require_selection()
        if job_id is None:return
        from .packages import export_package
        job=self.store.get_job(job_id)
        target,_=QFileDialog.getSaveFileName(self,'Export complete portable workflow',
                                              str(Path.home()/(job['name']+'.trpkg')),
                                              'Task Runner packages (*.trpkg)')
        if not target:return
        scripts=confirm(self,'Bundle referenced scripts?',
                        'Include locally referenced Python/PowerShell/CMD/BAT launch scripts? '
                        'These may contain private code or credentials; choose No to exclude them.')
        try:
            path=export_package(self.store,job_id,target,include_scripts=scripts)
            message(self,'Portable workflow exported',f'Exported source, referenced images and modules to {path}')
        except Exception as error:message(self,'Export failed',error,True)

    def import_portable(self):
        from .packages import import_package
        source,_=QFileDialog.getOpenFileName(self,'Import portable workflow',str(Path.home()),
                                              'Task Runner packages (*.trpkg)')
        if not source:return
        if not confirm(self,'Import untrusted workflow',
                       'This file may include commands, scripts, file writes or shutdown actions. '
                       'All imported jobs will be DISABLED until you review them. Import now?'):
            return
        try:
            job_id=import_package(self.store,source)
            self.refresh();self.select_task(job_id)
            message(self,'Portable workflow imported',
                    'Imported workflow and referenced assets. It is disabled. Review every step, path and target before enabling.')
        except Exception as error:message(self,'Import failed',error,True)

    def export_run_log(self):
        row=self.runs.currentRow()
        if row<0 or not self.runs.item(row,0):
            message(self,"Select a run","Choose an execution in the log table first.");return
        execution_id=int(self.runs.item(row,0).data(Qt.ItemDataRole.UserRole))
        filename,_=QFileDialog.getSaveFileName(self,"Export execution log",
                              str(Path.home()/f"task-runner-execution-{execution_id}.txt"),"Text (*.txt)")
        if not filename:return
        try:
            events=self.store.events_for(execution_id)
            contents="\n".join(f"[{local_text(e['recorded_at'])}] [{e['level']}] "
                       + (f"Step {e['step_index']}: " if e['step_index'] else "")+e['message'] for e in events)
            Path(filename).write_text(contents+"\n",encoding="utf-8")
        except Exception as exc:message(self,"Export log failed",exc,True);return
        self.statusBar().showMessage(f"Exported execution log {execution_id}")

    def duplicate_selected(self):
        job_id=self.require_selection()
        if job_id is None:return
        try:new_id=self.store.clone(job_id)
        except Exception as exc:message(self,"Duplicate failed",exc,True);return
        self.preferences.play("save")
        self.refresh();self.select_task(new_id)

    def toggle_selected(self):
        job_id=self.require_selection()
        if job_id is None:return
        job=self.store.get_job(job_id)
        try:self.store.set_enabled(job_id,not bool(job["enabled"]))
        except Exception as exc:message(self,"Could not update task",exc,True);return
        self.preferences.play("select");self.refresh();self.select_task(job_id)

    def delete_selected(self):
        job_id=self.require_selection()
        if job_id is None:return
        job=self.store.get_job(job_id)
        if not confirm(self,"Permanently delete task",f"Delete '{job['name']}' and its execution history? This cannot be undone."):
            return
        try:self.store.delete_job(job_id)
        except Exception as exc:message(self,"Delete failed",exc,True);return
        self.preferences.play("select");self.refresh()

    def run_debug_selected(self):
        self.run_selected(debug=True)

    def run_selected(self, debug=False):
        job_id=self.require_selection()
        if job_id is None:return
        job=self.store.get_job(job_id)
        if any(step["type"]=="shutdown" for step in job["actions"]):
            if not confirm(self,"Workflow contains shutdown",
                "This workflow requests a real Windows shutdown. Execute it now?"):
                return
        claimed=self.store.claim(job_id,force=True)
        if claimed is None:
            message(self,"Already running","The selected task already has a running execution.")
            return
        if debug:
            try:
                self.store.debug_enable(claimed,paused=True,break_on_failure=True,snapshots=True)
            except Exception as error:
                self.store.finish(job_id,claimed,'failed',f'Debugger startup failed: {error}')
                message(self,'Cannot start debugger',error,True)
                return
            self.set_page(1)
            self.refresh_logs()
            for row in range(self.runs.rowCount()):
                cell=self.runs.item(row,0)
                if cell and cell.data(Qt.ItemDataRole.UserRole)==claimed:
                    self.runs.selectRow(row)
                    break
        self.preferences.play("run")
        th=threading.Thread(target=run_claimed,args=(job_id,claimed),daemon=False,
                            name=f"taskrunner-job-{job_id}")
        self.active_workers[claimed]=th
        native_types={"click","move","drag","scroll","type","key","hotkey","paste","copy",
                      "close_window","desktop_expand_all","desktop_scroll_text"}
        minimize=bool(self.preferences.get("minimize_during_manual_runs")) and any(
                 step.get("type") in native_types for step in job["actions"])
        if minimize:
            self._restore_after_run.add(claimed)
            self.showMinimized()
            QApplication.processEvents()
            # Give Windows time to complete minimize/focus transition before the first click.
            QTimer.singleShot(900,th.start)
        else:
            th.start()
        self.refresh();self.select_task(job_id)

    def stop_selected(self):
        job_id=self.require_selection()
        if job_id is None:return
        running=self.store.running_execution(job_id)
        if running is None:
            message(self,"Nothing to stop","This task does not have a running execution.")
            return
        request_stop(running)
        self.statusBar().showMessage(f"Stop requested for task {job_id}, run {running}")
        self.preferences.play("select")

    def refresh(self):
        remembered=self.selected_id()
        jobs=self.store.all_jobs()
        self.table.setRowCount(len(jobs))
        for row,job in enumerate(jobs):
            fields=[str(job["id"]),job["name"],job["status"].upper() if job["enabled"] else "DISABLED",
                    job["schedule_kind"],local_text(job["next_run"]),local_text(job["last_run"]),job["description"]]
            for column,value in enumerate(fields):
                item=QTableWidgetItem(value)
                if column==0:item.setData(Qt.ItemDataRole.UserRole,job["id"])
                self.table.setItem(row,column,item)
        if remembered is not None:self.select_task(remembered)
        running=sum(j["status"]=="running" for j in jobs)
        self.task_count.setText(f"TASKS  ·  {len(jobs)} total  /  {running} running")
        # Detect completions from GUI workers or scheduled worker subprocesses.
        history=self.store.execution_history(limit=200)
        completed=[r for r in history if r["status"]!="running" and (
            r["id"]>self.last_seen_run or self.previous_run_states.get(r["id"])=="running")]
        if completed:
            self.preferences.play("done" if all(x["status"]=="success" for x in completed) else "error")
        if history:
            self.last_seen_run=max(self.last_seen_run,max(r["id"] for r in history))
        self.previous_run_states={r["id"]:r["status"] for r in history}
        finished={record["id"] for record in history if record["status"]!="running"}
        if self._restore_after_run & finished:
            self._restore_after_run.difference_update(finished)
            self.showNormal()
            self.raise_()
            self.activateWindow()
        self.active_workers={key:value for key,value in self.active_workers.items()
                             if value.is_alive() or key in self._restore_after_run}

    def check_due(self):
        # If GUI is open, it also acts as a scheduler. SQLite claims prevent duplication with the heartbeat.
        try:
            self.store.recover_abandoned()
            for job_id,execution_id in self.store.claim_due()+self.store.claim_file_events():
                th=threading.Thread(target=run_claimed,args=(job_id,execution_id),daemon=False)
                self.active_workers[execution_id]=th
                th.start()
        except Exception as exc:
            self.statusBar().showMessage(f"Scheduler check failed: {exc}")

    def refresh_logs(self):
        current=self.runs.currentRow()
        stored=self.runs.item(current,0).data(Qt.ItemDataRole.UserRole) if current>=0 and self.runs.item(current,0) else None
        entries=self.store.execution_history(limit=200)
        self.runs.setRowCount(len(entries))
        restore=None
        for row,entry in enumerate(entries):
            values=[str(entry["id"]),entry["job_name"],local_text(entry["started_at"]),
                    local_text(entry["finished_at"]),entry["status"]]
            for column,val in enumerate(values):
                item=QTableWidgetItem(val)
                if column==0:item.setData(Qt.ItemDataRole.UserRole,entry["id"])
                self.runs.setItem(row,column,item)
            if entry["id"]==stored:restore=row
        if restore is not None:self.runs.selectRow(restore)
        elif entries:self.runs.selectRow(0)
        else:self.run_details.setPlainText("No executions recorded yet.")

    def resume_from_checkpoint(self):
        previous=self.selected_debug_run()
        if previous is None:
            message(self,'Select a failed run','Choose a failed/cancelled execution with a checkpoint.');return
        progress=self.store.checkpoint_for(previous)
        if not progress:
            message(self,'No checkpoint','The selected run has no completed action checkpoint.');return
        if not confirm(self,'Resume from checkpoint',
                       f'Continue after step {progress["completed"]}? This requires a linear workflow with no lost browser/variable state. '
                       'The previously failed action may have partially changed the desktop; verify your target program is ready. '
                       'A new execution will be created, and completed steps will not be rerun.'):
            return
        try:
            job_id,execution=self.store.claim_resume(previous)
            self.active_workers[execution]=threading.Thread(target=run_claimed,args=(job_id,execution),daemon=False,
                                                              name=f'taskrunner-resume-{job_id}')
            self.active_workers[execution].start()
            self.statusBar().showMessage(f'Checkpoint continuation started as run {execution}')
            self.refresh_logs()
        except Exception as error:
            message(self,'Cannot resume checkpoint',error,True)

    def selected_debug_run(self):
        row=self.runs.currentRow()
        cell=self.runs.item(row,0) if row>=0 else None
        return cell.data(Qt.ItemDataRole.UserRole) if cell else None

    def debug_command(self, command):
        execution_id=self.selected_debug_run()
        if execution_id is None:
            message(self,'Select an execution','Choose a debug execution from the history table.');return
        try:
            self.store.debug_command(execution_id,command)
            if command=='cancel':request_stop(execution_id)
            self.refresh_debugger()
        except Exception as error:
            message(self,'Debugger control unavailable',error,True)

    def refresh_debugger(self):
        if self.stack.currentIndex()!=1:return
        execution_id=self.selected_debug_run()
        if execution_id is None:return
        session=self.store.debug_status(execution_id)
        if not session or not session['enabled']:
            self.debug_status_label.setText('Standard execution · Choose ▶ Debug replay to enable interactive step controls')
            return
        run=self.store.execution_by_id(execution_id)
        job=self.store.get_job(run['job_id']) if run else None
        steps=job['actions'] if job else []
        if self.debug_steps.count()!=len(steps) or self.debug_steps.property('job_id')!=(run['job_id'] if run else None):
            self.debug_steps.clear()
            for n,step in enumerate(steps,1):
                self.debug_steps.addItem(f'{n:03d}  {ACTIONS[step["type"]].name}')
            self.debug_steps.setProperty('job_id',run['job_id'] if run else None)
        current=int(session['step_index'])
        if current and 0<=current-1<self.debug_steps.count() and self.debug_steps.currentRow()!=current-1:
            self.debug_steps.setCurrentRow(current-1)
        self.debug_status_label.setText(
            f'Run {execution_id}  ·  {session["state"].upper()}  ·  Step {current}/{len(steps)}  ·  Control: {session["mode"].upper()}'
            + (f'  ·  {session["last_error"]}' if session['last_error'] else ''))
        self.show_debug_capture()

    def show_debug_capture(self):
        execution_id=self.selected_debug_run()
        if execution_id is None:return
        entries=self.store.debug_artifacts_for(execution_id)
        current=self.debug_steps.currentRow()+1
        matching=[x for x in entries if x['step_index']==current]
        if not matching:
            self.debug_image.setText('No screenshot captured for this step')
            self.debug_image.setPixmap(QPixmap())
            return
        path=Path(matching[-1]['path'])
        if not path.is_file():
            self.debug_image.setPixmap(QPixmap())
            self.debug_image.setText('Screenshot no longer exists')
            return
        preview=QPixmap(str(path))
        self.debug_image.setPixmap(preview.scaled(400,200,Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        self.debug_image.setToolTip(str(path))

    def teach_debug_click(self):
        execution_id=self.selected_debug_run()
        if execution_id is None:
            message(self,'Select an execution','Choose a paused debug run first.');return
        status=self.store.debug_status(execution_id)
        if not status or status['state'] not in ('paused','failed_paused'):
            message(self,'Pause to teach','Pause the debugger at a click action before capturing its replacement.');return
        run=self.store.execution_by_id(execution_id)
        job=self.store.get_job(run['job_id']) if run else None
        step_num=status['step_index']
        if not job or not 1<=step_num<=len(job['actions']) or job['actions'][step_num-1]['type']!='click':
            message(self,'Click required','The paused step is not a click action.');return
        if not confirm(self,'Teach a new click target',
                       'Task Runner will hide for an exact desktop screenshot. Select the correct button; '
                       'the new target will be saved to this task for future runs. Continue or Retry afterward.'):
            return
        self.hide()
        QTimer.singleShot(600,lambda:self._finish_teach_click(execution_id,step_num))

    def _finish_teach_click(self,execution_id,step_num):
        try:
            filename,left,top=capture_desktop()
        except Exception as error:
            self.show();message(self,'Capture failed',error,True);return
        self.show();self.raise_()
        picker=CaptureDialog(filename,left,top,self)
        if picker.exec()!=QDialog.DialogCode.Accepted:return
        sel=picker.selection
        try:
            from .recorder import window_at_point
            evidence=window_at_point(sel['x'],sel['y']) if os.name=='nt' else {}
            path=picker.save_region()
            patch={'x':sel['x'],'y':sel['y'],**evidence,
                   'reference_image':str(path) if path else '',
                   'confidence':0.9,'strict_target':True,'target_timeout':30.0}
            self.store.teach_click(execution_id,step_num,patch)
            self.statusBar().showMessage(f'Saved corrected target for step {step_num}. Choose Retry or Continue.')
            self.refresh_debugger()
        except Exception as error:
            message(self,'Could not save click correction',error,True)

    def show_run(self):
        row=self.runs.currentRow()
        if row<0:return
        item=self.runs.item(row,0)
        if not item:return
        execution_id=item.data(Qt.ItemDataRole.UserRole)
        lines=[]
        for event in self.store.events_for(execution_id):
            lines.append(f"[{local_text(event['recorded_at'])}] [{event['level']}] " +
                         (f"Step {event['step_index']}: " if event['step_index'] else "") + event["message"])
        self.run_details.setPlainText("\n".join(lines) if lines else "No step events recorded yet.")
        self.refresh_debugger()

    def vault_save(self):
        from .vault import Vault
        name,ok=QInputDialog.getText(self,'Protected credential','Vault name (identifier):')
        if not ok or not name:return
        value,accepted=QInputDialog.getText(self,'Protected credential','Credential value:',QLineEdit.EchoMode.Password)
        if not accepted or not value:return
        try:
            Vault().put(name,value)
            message(self,'Credential protected',f'Saved {name} using Windows user-bound DPAPI. The value is not displayed.')
        except Exception as error:message(self,'Vault error',error,True)

    def vault_delete(self):
        from .vault import Vault
        try:names=Vault().list_names()
        except Exception as error:message(self,'Vault unavailable',error,True);return
        if not names:
            message(self,'Vault empty','No protected credentials are stored.');return
        name,ok=QInputDialog.getItem(self,'Delete credential','Select credential:',names,0,False)
        if not ok or not name:return
        if not confirm(self,'Delete protected credential',f'Permanently delete stored credential {name}?'):
            return
        try:Vault().remove(name)
        except Exception as error:message(self,'Vault error',error,True)

    def install_agent(self):
        ok,details=install_scheduler()
        self.refresh_scheduler_label()
        message(self,"Scheduler installation" if ok else "Scheduler installation failed",details or ("Installed" if ok else "No details"),not ok)

    def remove_agent(self):
        if not confirm(self,"Disable background scheduling","Remove Task Runner's Windows Task Scheduler heartbeat? Saved jobs remain intact."):
            return
        ok,details=remove_scheduler()
        self.refresh_scheduler_label()
        message(self,"Scheduler removal" if ok else "Removal failed",details or ("Removed" if ok else "No details"),not ok)

    def closeEvent(self,event):
        if self.active_workers:
            if not confirm(self,"Active workflows",
                "There are workflows running in this GUI. Request cancellation and close? Background scheduled runners are unaffected."):
                event.ignore();return
            for execution_id in self.active_workers:request_stop(execution_id)
        self.preferences.play("exit",blocking=True)
        event.accept()
