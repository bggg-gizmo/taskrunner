"""Windows scheduled agent and direct execution entrypoints."""
import os
import threading
import subprocess
import sys
from pathlib import Path
from .paths import data_root
from .store import Store
from .executor import WorkflowEngine


def marker(execution_id:int)->Path:
    p=data_root()/"stop-signals"
    p.mkdir(parents=True,exist_ok=True)
    return p/f"{execution_id}.stop"


def request_stop(execution_id:int):
    marker(execution_id).touch()


def emergency_shortcut(execution_id:int):
    """Global emergency stop while the current user's task is executing.

    Listening never starts outside an active workflow, and the listener is
    always shut down in run_claimed's finally block.
    """
    if sys.platform!='win32':return None
    from pynput.keyboard import GlobalHotKeys
    listener=GlobalHotKeys({'<ctrl>+<shift>+<f11>':lambda:request_stop(execution_id)})
    listener.start()
    return listener


def run_claimed(job_id:int,execution_id:int):
    stop=marker(execution_id)
    listener=None
    try:
        db=Store()
        try:listener=emergency_shortcut(execution_id)
        except Exception as error:
            db.event(execution_id,'WARNING',f'Global emergency stop hotkey unavailable: {error}')
        db.register_runner(execution_id,os.getpid())
        return WorkflowEngine(db,should_stop=stop.exists).execute(job_id,execution_id)
    finally:
        if listener is not None:
            listener.stop()
            if listener.is_alive() and threading.current_thread() is not listener:
                listener.join(timeout=2)
        stop.unlink(missing_ok=True)


def command(*args):
    home=os.environ.get("TASKRUNNER_HOME")
    suffix=["--data-dir", str(Path(home).expanduser().resolve())] if home else []
    if getattr(sys,"frozen",False):
        return [sys.executable,*map(str,args),*suffix]
    # Windows Task Scheduler launches with C:\Windows\System32 as its working
    # directory. A fully qualified launcher is required for source checkouts.
    launcher = Path(__file__).resolve().parent.parent / "launcher.py"
    return [sys.executable, str(launcher), *map(str,args),*suffix]


def spawn_claimed(job_id:int,execution_id:int):
    kwargs={}
    if sys.platform=="win32":
        kwargs["creationflags"]=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(command("--run-claimed",job_id,execution_id),
                            cwd=str(Path(sys.executable).resolve().parent) if getattr(sys,"frozen",False) else None,
                            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**kwargs)


def tick():
    store=Store()
    store.recover_abandoned()
    jobs=store.claim_due()+store.claim_file_events()
    for job_id,execution_id in jobs:
        try:
            spawn_claimed(job_id,execution_id)
        except Exception as exc:
            store.finish(job_id,execution_id,"failed",f"Could not launch workflow runner: {exc}")
    return len(jobs)


def scheduler_task_name():
    return "TaskRunnerScheduler"


def install_scheduler() -> tuple[bool,str]:
    """Register a current-user interactive heartbeat without saving a password.

    PowerShell ScheduledTasks cmdlets accept an Interactive logon principal, so
    the task runs only after this account has logged in. No UAC bypass or
    elevated system account is requested.
    """
    if sys.platform!="win32":
        return False,"Windows Task Scheduler is only available on Windows."
    from subprocess import list2cmdline
    import base64

    args=command("--tick")
    executable=args[0]
    command_arguments=list2cmdline(args[1:])
    workdir=str(Path(executable).resolve().parent if getattr(sys,"frozen",False)
                else Path(__file__).resolve().parent.parent)
    def quote(value:str) -> str:
        return "'" + str(value).replace("'", "''") + "'"
    script="\n".join([
        "$ErrorActionPreference='Stop'",
        "$identity=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name",
        "$principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited",
        f"$action=New-ScheduledTaskAction -Execute {quote(executable)} -Argument {quote(command_arguments)} -WorkingDirectory {quote(workdir)}",
        "$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)",
        "$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 3)",
        f"Register-ScheduledTask -TaskName {quote(scheduler_task_name())} -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null",
        "Write-Output 'Task Runner heartbeat registered for the current interactive Windows account.'",
    ])
    encoded=base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-EncodedCommand",encoded],
                              capture_output=True,text=True,errors="replace",timeout=45)
    except (OSError,subprocess.TimeoutExpired) as exc:
        return False,f"Unable to register Windows scheduled task: {exc}"
    message=((result.stdout or "")+(result.stderr or "")).strip()
    if result.returncode:
        return False,message or f"Task Scheduler registration failed (exit {result.returncode})"
    return True,message

def remove_scheduler() -> tuple[bool,str]:
    if sys.platform!="win32":return False,"Windows only"
    result=subprocess.run(["schtasks.exe","/Delete","/TN",scheduler_task_name(),"/F"],
                          capture_output=True,text=True,errors="replace",timeout=40)
    return result.returncode==0,((result.stdout or "")+(result.stderr or "")).strip()


def scheduler_status() -> bool:
    if sys.platform!="win32":return False
    result=subprocess.run(["schtasks.exe","/Query","/TN",scheduler_task_name()],
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return result.returncode==0
