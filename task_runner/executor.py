"""Ordered desktop/browser automation runner with optional verification and journal."""
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from .store import Store
from .paths import data_root, setup_browser_path
from .actions import ACTIONS
from .flow import compile_flow, condition, validate_workflow
from .fileops import atomic_copy_file, atomic_write_text
from .debugger import PlaybackDebugger, DebugAbort

INTERPOLATE=re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class Cancelled(Exception):
    pass


class WorkflowEngine:
    def __init__(self, store: Store | None = None, on_event=None, should_stop=None):
        self.store = store or Store()
        self.on_event = on_event or (lambda *args:None)
        self.should_stop = should_stop or (lambda:False)
        self.vars: dict[str,str] = {}
        self.browser_manager = None
        self.browser = None
        self.page = None
        self.live_capture = None
        self.memory_watch = None
        self.owned_processes: dict[int, tuple[int, float]] = {}
        self.execution_id = None

    def expand(self, value):
        if not isinstance(value,str):
            return value
        def repl(match):
            key=match.group(1)
            if key not in self.vars:
                raise KeyError(f"Variable not set: {key}")
            return str(self.vars[key])
        return INTERPOLATE.sub(repl,value)

    def abort_if_requested(self):
        if self.memory_watch is not None and self.memory_watch.cancel_reason:
            raise Cancelled(self.memory_watch.cancel_reason)
        if self.should_stop():
            raise Cancelled("Execution cancelled by operator")

    def sleep(self, seconds):
        deadline = time.monotonic() + max(0,float(seconds))
        while time.monotonic()<deadline:
            self.abort_if_requested()
            time.sleep(min(0.2,deadline-time.monotonic()))

    def browser_page(self):
        if self.page is None:
            raise RuntimeError("Open a browser URL first")
        return self.page

    def wait_for_window(self, title: str, state: str = "appears", timeout: float = 30.0):
        from pywinauto import Desktop
        deadline=time.monotonic()+timeout
        while True:
            self.abort_if_requested()
            found=any(title.casefold() in w.window_text().casefold() for w in Desktop(backend="uia").windows())
            if found==(state=="appears"):
                return
            if time.monotonic()>=deadline:
                raise TimeoutError(f"Window did not {state}: {title}")
            self.sleep(.2)

    def run_action(self, step: dict):
        kind=step["type"]
        if kind not in ACTIONS:
            raise ValueError(f"Unknown action: {kind}")
        p={k:self.expand(v) for k,v in step.get("params",{}).items()}
        self.abort_if_requested()
        if kind == 'memory_snapshot':
            from .resources import sample_resources
            pid = int(p.get('pid') or self.vars.get('process_id') or 0)
            report = sample_resources(pid, include_gpu=bool(p.get('include_gpu',False)))
            self.vars['memory_process_ram_mb'] = str(report.process_ram_mb)
            self.vars['memory_system_available_mb'] = str(report.available_ram_mb)
            self.vars['memory_system_used_percent'] = str(report.system_used_percent)
            self.vars['memory_gpu_vram_mb'] = (str(report.process_gpu_vram_mb)
                                                  if report.process_gpu_vram_mb is not None else 'unavailable')
            if self.execution_id is not None:
                self.store.event(self.execution_id,'INFO',
                    f'Resource snapshot PID={pid}: process RAM={report.process_ram_mb:.1f} MiB; '
                    f'available RAM={report.available_ram_mb:.1f} MiB; '
                    f'NVIDIA compute VRAM={self.vars["memory_gpu_vram_mb"]}')
        elif kind == 'memory_watch_start':
            from .resources import MemoryWatch
            if self.memory_watch is not None:
                raise RuntimeError('A resource guard is already active; stop it before starting another')
            pid = int(p.get('pid') or self.vars.get('process_id') or 0)
            if pid <= 0:
                raise ValueError('Resource guard requires a PID (launch a program first or enter a PID)')
            response = p.get('response','warn')
            from .resources import process_identity
            # Snapshot PID identity even for warning-only guards so the
            # watcher never switches silently to an unrelated recycled PID.
            observed = process_identity(pid)
            owned = self.owned_processes.get(pid)
            if response == 'terminate_owned':
                if owned is None:
                    raise ValueError('Cannot terminate arbitrary processes: PID must have been launched by this workflow')
                if abs(observed[1]-owned[1])>0.01:
                    raise RuntimeError('Owned PID creation time changed (PID reuse); refusing resource guard termination')
            def record(level,message):
                if self.execution_id is not None:
                    self.store.event(self.execution_id,level,message)
                self.on_event('resource',0,{'level':level,'message':message})
            watch = MemoryWatch(pid, process_ram_limit_mb=float(p.get('process_ram_limit_mb',0)),
                minimum_available_ram_mb=float(p.get('minimum_available_ram_mb',0)),
                process_gpu_vram_limit_mb=float(p.get('process_gpu_vram_limit_mb',0)),
                interval=float(p.get('interval',2)),response=response,owned_identity=owned,
                on_event=record, observed_identity=observed)
            self.memory_watch = watch.start()
            self.vars['memory_guard_pid'] = str(pid)
            self.abort_if_requested()
        elif kind == 'memory_watch_stop':
            if self.memory_watch is None:
                raise RuntimeError('No resource guard is running')
            # Do not swallow a cancellation that arrived after the initial
            # abort check but while the watcher was stopping/joining.
            watch = self.memory_watch
            report = watch.stop()
            stop_reason = watch.cancel_reason
            self.memory_watch = None
            self.vars['memory_peak_process_mb'] = str(report['peak_process_mb'])
            self.vars['memory_sample_count'] = str(report['samples'])
            if self.execution_id is not None:
                self.store.event(self.execution_id,'INFO',
                    f'Resource guard stopped: {report["samples"]} samples, '
                    f'peak process RAM {report["peak_process_mb"]:.1f} MiB')
            if stop_reason:
                raise Cancelled(stop_reason)
        elif kind=='wait_ocr':
            from .ocr import read_region,stable_text_condition
            result=stable_text_condition(
                lambda:read_region(p.get('region',''),float(p.get('confidence',.45))),
                str(p.get('text','')),p.get('condition','contains'),int(p.get('stable_frames',2)),
                bool(p.get('case_sensitive',False)),abort=self.abort_if_requested,
                sleep=self.sleep,timeout=float(p.get('timeout',180)),poll=float(p.get('poll',.8)))
            self.vars[p.get('name','ocr_text')]=result
        elif kind=="load_secret":
            from .vault import Vault
            self.vars[p['name']]=Vault().get(p['secret_name'])
        elif kind=="click_image":
            from .observability import wait_until, image_location
            point=[None]
            def locate():
                point[0]=image_location(p["image"],p.get("region", ""),float(p.get("confidence",.88)))
                return point[0] is not None
            wait_until(locate,float(p.get("timeout",45)),float(p.get("poll",.4)),self.sleep,self.abort_if_requested)
            if sys.platform=="win32":
                from . import winmouse
                winmouse.click(*point[0],button=p.get("button","left"))
            else:
                import pyautogui
                pyautogui.click(*point[0],button=p.get("button","left"))
        elif kind=="wait_screen":
            from .observability import wait_until, screen_image, image_match
            from .visual_verification import significant_change
            mode=p.get("mode","changed")
            region=str(p.get("region", ""))
            reference=screen_image(region) if mode=="changed" else None
            def matches():
                if mode=="changed":return significant_change(reference,screen_image(region))
                found=image_match(p["image"],region,float(p.get("confidence",.88)))
                return found if mode=="image_appears" else not found
            if mode!="changed" and not p.get("image"):
                raise ValueError("Visual image condition requires a reference image file")
            wait_until(matches,float(p.get("timeout",180)),float(p.get("poll",.5)),self.sleep,self.abort_if_requested)
        elif kind=="wait_content":
            from .observability import wait_until,window_text
            import pyperclip
            source=p.get("source","window")
            def read():
                if source=="window":return window_text(p["target"])
                if source=="browser":return self.browser_page().locator(p.get("target") or "body").inner_text(timeout=1000)
                if source=="file":return Path(p["target"]).expanduser().read_text(encoding="utf-8",errors="replace")[-4_000_000:]
                return pyperclip.paste()
            if p.get("condition")=="changed":
                try:baseline=read()
                except (LookupError,FileNotFoundError):baseline=""
            else:baseline=""
            observed=[None]
            def condition_matches():
                observed[0]=read()
                desired=str(p.get("text", ""))
                condition=p.get("condition","contains")
                return ((desired in observed[0]) if condition=="contains" else
                        (desired not in observed[0]) if condition=="absent" else
                        observed[0]!=baseline)
            if p.get("condition")!="changed" and not p.get("text"):
                raise ValueError("Text appears/absent conditions need expected text")
            wait_until(condition_matches,float(p.get("timeout",180)),float(p.get("poll",.5)),self.sleep,self.abort_if_requested)
            self.vars[p.get("name","observed_text")]=observed[0]
        elif kind=="capture_live_start":
            from .observability import LiveCapture
            if getattr(self, "live_capture", None) is not None:
                raise RuntimeError("A live capture is already active; stop it before starting another")
            monitor=LiveCapture(p["mode"],p["destination"],p.get("source", ""),
                float(p.get("interval",.5)),int(p.get("max_captures",1000)),p.get("region", ""))
            self.live_capture=monitor.start()
            self.vars["capture_directory"]=str(monitor.destination)
        elif kind=="capture_live_stop":
            monitor=getattr(self,"live_capture",None)
            if monitor is None:raise RuntimeError("No live capture running")
            self.vars["capture_manifest"]=str(monitor.stop())
            self.vars["capture_count"]=str(monitor.count)
            if monitor.error:raise RuntimeError(f"Capture failed: {monitor.error}")
            self.live_capture=None
        elif kind=="clipboard_image":
            from PIL import Image,ImageGrab
            content=ImageGrab.grabclipboard()
            if not isinstance(content,Image.Image):
                raise LookupError("No image is present on the clipboard")
            dest=Path(p["path"]).expanduser();dest.parent.mkdir(parents=True,exist_ok=True)
            content.save(dest,format="PNG")
            self.vars["last_image"]=str(dest)
        elif kind=="capture_program_output":
            import shlex
            path=Path(p["output"]).expanduser();path.parent.mkdir(parents=True,exist_ok=True)
            if sys.platform=="win32":
                cmd=subprocess.list2cmdline([p["path"]])+(" "+p.get("arguments", "") if p.get("arguments") else "")
            else:cmd=[p["path"]]+shlex.split(p.get("arguments", ""))
            with open(path,"ab", buffering=0) as output:
                process=subprocess.Popen(cmd,stdout=output,stderr=subprocess.STDOUT)
                deadline=time.monotonic()+float(p.get("timeout",300))
                try:
                    while process.poll() is None:
                        self.abort_if_requested()
                        if time.monotonic()>=deadline:
                            raise TimeoutError(f"Program did not finish in time: {p['path']}")
                        self.sleep(.1)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:process.wait(timeout=3)
                        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
                if process.returncode:raise RuntimeError(f"Program exited with code {process.returncode}")
            self.vars["last_file"]=str(path)
        elif kind in ("click","move","drag","scroll","type","key","hotkey","paste","copy","close_window","screenshot"):
            native_mouse = kind in ("click","move","drag","scroll") and sys.platform=="win32"
            if not native_mouse and not (kind=="type" and sys.platform=="win32"):
                import pyautogui as pg
                pg.FAILSAFE = True
                pg.PAUSE = 0.08
            if native_mouse:
                from . import winmouse
                if kind=="click":
                    from .precision import resolve_adaptive
                    from .observability import wait_until
                    destination=[None]
                    def find_target():
                        try:
                            destination[0]=resolve_adaptive(
                                int(p['x']),int(p['y']),p.get('window_title',''),
                                float(p.get('window_rx',0)),float(p.get('window_ry',0)),
                                p.get('control_name',''),p.get('automation_id',''),
                                p.get('reference_image',''),float(p.get('confidence',.88)),
                                bool(p.get('allow_relative_fallback',True)),
                                bool(p.get('strict_target',False)))
                            return True
                        except LookupError:
                            return False
                    wait_until(find_target,float(p.get('target_timeout',20)),.35,
                               self.sleep,self.abort_if_requested)
                    target=destination[0]
                    self.vars['last_target_method']=target.method
                    self.vars['last_target_confidence']=f'{target.confidence:.3f}'
                    winmouse.click(target.x,target.y,p.get('button','left'),int(p.get('clicks',1)))
                elif kind=="move":winmouse.move(int(p["x"]),int(p["y"]),float(p.get("duration",0.2)))
                elif kind=="drag":winmouse.drag(int(p["x1"]),int(p["y1"]),int(p["x2"]),int(p["y2"]),float(p.get("duration",0.5)))
                elif kind=="scroll":winmouse.scroll(int(p["amount"]))
            elif kind=="click": pg.click(x=int(p["x"]),y=int(p["y"]),clicks=int(p.get("clicks",1)),button=p.get("button","left"))
            elif kind=="move": pg.moveTo(int(p["x"]),int(p["y"]),duration=float(p.get("duration",0.2)))
            elif kind=="drag":
                pg.moveTo(int(p["x1"]),int(p["y1"]))
                pg.dragTo(int(p["x2"]),int(p["y2"]),duration=float(p.get("duration",0.5)))
            elif kind=="scroll": pg.scroll(int(p["amount"]))
            elif kind=="type":
                text=str(p["text"])
                if sys.platform=="win32":
                    # Native Unicode SendInput does not call PyAutoGUI's shared
                    # GetCursorPos signature and never overwrites the clipboard.
                    from . import wininput
                    wininput.send_text(text,float(p.get("interval",0.02)),self.sleep)
                else:
                    if any(ord(c)>127 for c in text):
                        import pyperclip
                        pyperclip.copy(text)
                        pg.hotkey("ctrl","v")
                    else:pg.write(text,interval=float(p.get("interval",0.02)))
            elif kind=="key": pg.press(str(p["key"]), presses=int(p.get("presses",1)))
            elif kind=="hotkey": pg.hotkey(*[k.strip() for k in p["keys"].split("+") if k.strip()])
            elif kind=="paste": pg.hotkey("ctrl","v")
            elif kind=="copy":
                import pyperclip
                pg.hotkey("ctrl","c")
                self.sleep(.2)
                self.vars["clipboard"] = pyperclip.paste()
            elif kind=="close_window": pg.hotkey("alt","f4")
            elif kind=="screenshot":
                import mss
                from mss.tools import to_png
                with mss.mss() as snap:
                    full=snap.monitors[0]
                    shot=snap.grab(full)
                    path=Path(p["path"]).expanduser()
                    path.parent.mkdir(parents=True,exist_ok=True)
                    to_png(shot.rgb,shot.size,output=str(path))
                    self.vars["last_screenshot"]=str(path)
        elif kind=="wait": self.sleep(p["seconds"])
        elif kind=="wait_window":
            self.wait_for_window(p["title"], p.get("state","appears"), float(p.get("timeout",30)))
        elif kind=="wait_file":
            path=Path(p["path"]).expanduser()
            deadline=time.monotonic()+float(p.get("timeout",30))
            while True:
                self.abort_if_requested()
                if path.exists()==(p.get("state","exists")=="exists"):
                    break
                if time.monotonic()>=deadline:
                    raise TimeoutError(f"File condition not met: {p['state']}: {path}")
                self.sleep(0.2)
        elif kind=="browser_wait_state":
            self.browser_page().locator(p["selector"]).first.wait_for(
                state=p.get("state","visible"),timeout=int(float(p.get("timeout",20))*1000))
        elif kind=="browser_select":
            argument=p["choice"] if p["method"] != "index" else int(p["choice"])
            self.browser_page().locator(p["selector"]).select_option(**{p["method"]:argument})
        elif kind=="browser_expand_all":
            import json
            from .collection import expand_browser_controls
            result=expand_browser_controls(self.browser_page(),p["selector"],int(p["max_controls"]),self.sleep)
            self.vars[p["name"]]=json.dumps(result,ensure_ascii=False,indent=2)
            self.vars["dropdown_count"]=str(result["details_opened"]+result["aria_opened"]+result["select_count"])
        elif kind=="browser_scroll_text":
            from .collection import capture_browser_scrolling_text
            content,scrolls=capture_browser_scrolling_text(self.browser_page(),p["selector"],
                int(p["max_scrolls"]),int(p["step_px"]),float(p["pause_seconds"]),self.sleep)
            self.vars[p["name"]]=content
            self.vars["scroll_count"]=str(scrolls)
            if p.get("copy_to_clipboard",True):
                import pyperclip
                pyperclip.copy(content)
                self.vars["clipboard"]=content
        elif kind=="desktop_expand_all":
            import json
            from .collection import expand_desktop_controls
            result=expand_desktop_controls(p.get("title", ""),int(p["max_controls"]),self.sleep)
            self.vars[p["name"]]=json.dumps(result,ensure_ascii=False,indent=2)
            self.vars["dropdown_count"]=str(result["count"])
        elif kind=="desktop_scroll_text":
            from .collection import capture_desktop_scrolling_text
            content,scrolls=capture_desktop_scrolling_text(p.get("title", ""),int(p["max_scrolls"]),
                int(p["wheel_notches"]),float(p["pause_seconds"]),self.sleep)
            self.vars[p["name"]]=content
            self.vars["scroll_count"]=str(scrolls)
            if p.get("copy_to_clipboard",True):
                import pyperclip
                pyperclip.copy(content)
                self.vars["clipboard"]=content
        elif kind=="http_get":
            from urllib.request import Request, urlopen
            request=Request(p["url"],headers={"User-Agent":"TaskRunner/1.0"})
            with urlopen(request,timeout=float(p.get("timeout",30))) as response:
                payload=response.read(20_000_001)
                if len(payload)>20_000_000:
                    raise ValueError("HTTP response exceeds 20 MB")
                charset=response.headers.get_content_charset() or "utf-8"
                self.vars[p["name"]]=payload.decode(charset,errors="replace")
                self.vars["http_status"]=str(response.status)
                self.vars["current_url"]=response.geturl()
        elif kind in ("if_var","else","endif","repeat","end_repeat","break_loop","continue_loop"):
            # Flow actions are dispatched by execute(), not by this method.
            raise RuntimeError(f"{kind} requires the structured workflow dispatcher")
        elif kind=="set_var": self.vars[p["name"]]=str(p["value"])
        elif kind=="clipboard_read":
            import pyperclip
            self.vars[p["name"]]=pyperclip.paste()
            self.vars["clipboard"]=self.vars[p["name"]]
        elif kind=="clipboard_write":
            import pyperclip
            pyperclip.copy(p["text"])
            self.vars["clipboard"]=p["text"]
        elif kind=="launch":
            import shlex
            arguments=p.get("arguments", "").strip()
            if sys.platform=="win32":
                # Preserve Windows argument-quoting and backslashes exactly.
                cmd=subprocess.list2cmdline([p["path"]]) + (" " + arguments if arguments else "")
            else:
                cmd=[p["path"]] + shlex.split(arguments)
            proc=subprocess.Popen(cmd,cwd=p.get("cwd") or None)
            self.vars["process_id"]=str(proc.pid)
            try:
                from .resources import process_identity
                self.owned_processes[proc.pid]=process_identity(proc.pid)
            except Exception as error:
                # Launch remains functional if the OS denies process inspection.
                # Only optional owned-process termination is unavailable.
                if self.execution_id is not None:
                    self.store.event(self.execution_id, 'WARNING',
                        f'Cannot track launched process ownership for PID {proc.pid}: {error}')
            if p.get("wait_for_exit",False):
                while proc.poll() is None:
                    # Waiting for a GUI program must remain cancellable.
                    self.sleep(.2)
                if proc.returncode != 0:
                    raise RuntimeError(f"Program exited with code {proc.returncode}")
            if p.get("wait_for_window_title", "").strip():
                self.wait_for_window(p["wait_for_window_title"], "appears", float(p.get("window_timeout",30)))
        elif kind=="open_path":
            if sys.platform!="win32": raise RuntimeError("Opening Windows shell targets requires Windows")
            os.startfile(p["path"])
            if p.get("wait_for_window_title", "").strip():
                self.wait_for_window(p["wait_for_window_title"], "appears", float(p.get("window_timeout",30)))
        elif kind=="activate":
            from pywinauto import Desktop
            cutoff=time.monotonic()+float(p.get("timeout",10.0))
            while True:
                candidates=[w for w in Desktop(backend="uia").windows() if p["title"].lower() in w.window_text().lower()]
                if candidates:
                    candidates[0].set_focus()
                    break
                if time.monotonic()>=cutoff: raise TimeoutError(f"Window not found: {p['title']}")
                self.sleep(.3)
        elif kind in ("save_clipboard","write_file","read_file"):
            path=Path(p["path"]).expanduser()
            if kind=="read_file": self.vars[p["name"]]=path.read_text(encoding="utf-8")
            else:
                path.parent.mkdir(parents=True,exist_ok=True)
                if kind=="save_clipboard":
                    import pyperclip
                    body=pyperclip.paste()
                else: body=p["text"]
                if p.get("append"):
                    with path.open("a", encoding="utf-8") as file:
                        file.write(body)
                else:
                    atomic_write_text(path, body)
                self.vars["last_file"]=str(path)
        elif kind=="browser_open":
            setup_browser_path()
            if self.page is None:
                from playwright.sync_api import sync_playwright
                self.browser_manager=sync_playwright().start()
                self.browser=self.browser_manager.chromium.launch(headless=bool(p.get("headless",False)))
                self.page=self.browser.new_page()
            self.page.goto(p["url"],wait_until=p.get("wait_until","domcontentloaded"),timeout=60000)
            self.vars["current_url"]=self.page.url
        elif kind=="browser_click": self.browser_page().locator(p["selector"]).click(timeout=int(float(p.get("timeout",20))*1000))
        elif kind=="browser_fill": self.browser_page().locator(p["selector"]).fill(p["text"],timeout=int(float(p.get("timeout",20))*1000))
        elif kind=="browser_press":
            if p.get("selector"): self.browser_page().locator(p["selector"]).press(p["key"])
            else: self.browser_page().keyboard.press(p["key"])
        elif kind=="browser_wait": self.browser_page().locator(p["selector"]).wait_for(state="visible",timeout=int(float(p.get("timeout",20))*1000))
        elif kind=="browser_text":
            self.vars[p["name"]] = self.browser_page().locator(p["selector"]).inner_text()
        elif kind=="browser_html": self.vars[p["name"]]=self.browser_page().content()
        elif kind=="soup_select":
            from bs4 import BeautifulSoup
            source=self.vars.get(p["source"])
            if source is None: raise KeyError(f"HTML variable not found: {p['source']}")
            results=BeautifulSoup(source,"lxml").select(p["selector"])
            if not results: raise LookupError(f"Beautiful Soup selector matched nothing: {p['selector']}")
            selected=[r.get(p["attribute"],"") if p.get("attribute") else r.get_text(" ",strip=True) for r in results]
            self.vars[p["name"]]="\n".join(map(str,selected)) if p.get("all_matches") else str(selected[0])
        elif kind=="browser_close":
            self.close_browser()
        elif kind=="browser_download":
            path=Path(p["path"]).expanduser()
            path.parent.mkdir(parents=True,exist_ok=True)
            with self.browser_page().expect_download(timeout=int(float(p.get("timeout",60))*1000)) as download_info:
                self.browser_page().locator(p["selector"]).click()
            download_info.value.save_as(str(path))
            self.vars["last_file"]=str(path)
        elif kind=="browser_screenshot":
            path=Path(p["path"]).expanduser()
            path.parent.mkdir(parents=True,exist_ok=True)
            self.browser_page().screenshot(path=str(path),full_page=bool(p.get("full_page",True)))
            self.vars["last_screenshot"]=str(path)
        elif kind in ("mkdir","copy_file","move_file","delete_file","list_dir"):
            from shutil import copy2, move as move_fs, rmtree
            if kind=="mkdir":
                Path(p["path"]).expanduser().mkdir(parents=True,exist_ok=True)
            elif kind=="list_dir":
                self.vars[p["name"]]="\n".join(sorted(x.name for x in Path(p["path"]).expanduser().iterdir()))
            elif kind=="delete_file":
                target=Path(p["path"]).expanduser()
                if not target.is_file():
                    raise ValueError(f"Delete file requires an existing regular file: {target}")
                target.unlink()
            else:
                source=Path(p["source"]).expanduser()
                destination=Path(p["destination"]).expanduser()
                if not source.exists():raise FileNotFoundError(source)
                if source.resolve()==destination.resolve():
                    raise ValueError("Source and destination cannot be the same path")
                if kind=="copy_file" and not source.is_file():
                    raise ValueError("Copy file requires a regular file")
                if kind=="copy_file":
                    atomic_copy_file(source, destination, overwrite=bool(p.get("overwrite",False)))
                else:
                    if destination.exists():
                        if not p.get("overwrite",False):
                            raise FileExistsError(f"Destination exists (overwrite disabled): {destination}")
                        # Retain the existing move-file / move-directory behavior.
                        if destination.is_dir():rmtree(destination)
                        else:destination.unlink()
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    move_fs(str(source),str(destination))
                self.vars["last_file"]=str(destination)
        elif kind=="shutdown":
            if sys.platform!="win32": raise RuntimeError("Shutdown action requires Windows")
            delay=max(0,int(p.get("delay",60)))
            subprocess.run(["shutdown.exe","/s","/t",str(delay)],check=True)
        elif kind=="abort_shutdown":
            if sys.platform!="win32": raise RuntimeError("Shutdown action requires Windows")
            subprocess.run(["shutdown.exe","/a"],check=True)

    def verify(self, spec: dict, before=None) -> None:
        kind=spec.get("kind","none")
        if kind=="none": return
        target=self.expand(spec.get("target",""))
        deadline=time.monotonic()+max(0,float(spec.get("timeout",10.0)))
        while True:
            self.abort_if_requested()
            if kind=="file_exists": ok=Path(target).exists()
            elif kind=="file_missing": ok=not Path(target).exists()
            elif kind in ("window_exists", "window_missing"):
                from pywinauto import Desktop
                present=any(target.casefold() in w.window_text().casefold() for w in Desktop(backend="uia").windows())
                ok=present if kind=="window_exists" else not present
            elif kind=="clipboard_contains":
                import pyperclip
                ok=target in pyperclip.paste()
            elif kind=="browser_visible": ok=self.browser_page().locator(target).first.is_visible()
            elif kind=="browser_hidden": ok=not self.browser_page().locator(target).first.is_visible()
            elif kind=="screen_changed":
                from .visual_verification import take_sample,significant_change
                if before is None:
                    raise RuntimeError("screen_changed verification requires a pre-action reference frame")
                ok=significant_change(before,take_sample(target))
            elif kind=="image_visible":
                import pyautogui as pg
                try: ok=pg.locateOnScreen(target,confidence=0.85) is not None
                except pg.ImageNotFoundException: ok=False
            else: raise ValueError(f"Unknown verification kind: {kind}")
            if ok: return
            if time.monotonic()>=deadline: raise TimeoutError(f"Verification failed: {kind}: {target}")
            self.sleep(.3)

    def cleanup(self):
        watch=getattr(self,'memory_watch',None)
        if watch is not None:
            try:
                summary=watch.stop()
                if self.execution_id is not None:
                    self.store.event(self.execution_id,'INFO',
                        f'Resource guard cleanup: {summary["samples"]} samples; '
                        f'peak RAM {summary["peak_process_mb"]:.1f} MiB')
            except Exception:
                pass
            self.memory_watch=None
        monitor=getattr(self,"live_capture",None)
        if monitor is not None:
            try:
                manifest=monitor.stop()
                self.vars["capture_manifest"]=str(manifest)
                self.vars["capture_count"]=str(monitor.count)
            except Exception:
                pass
            self.live_capture=None
        self.close_browser()

    def close_browser(self):
        if self.browser:
            try: self.browser.close()
            except Exception: pass
        if self.browser_manager:
            try: self.browser_manager.stop()
            except Exception: pass
        self.browser=self.browser_manager=self.page=None

    def execute(self, job_id: int, execution_id: int):
        self.execution_id=execution_id
        job=self.store.get_job(job_id)
        if job is None:
            self.store.finish(job_id,execution_id,"failed","Job was deleted before execution")
            return "failed"
        self.vars={"task_name":job["name"],"task_id":str(job_id)}
        status="success"
        result="Completed all workflow steps"
        try:
            from .modules import expand_modules
            steps=expand_modules(self.store,job["actions"],ancestors=(job_id,))
            validate_workflow(steps)  # Preflight before any potentially destructive action.
            self.store.execution_plan(execution_id,steps)
            previous_run=self.store.execution_by_id(execution_id)
            resume_index=int(previous_run.get('resume_index',0)) if previous_run else 0
            if resume_index:
                from .recovery import validate_resume
                validate_resume(steps,resume_index)
                self.store.event(execution_id,'WARNING',f'Operator-approved checkpoint continuation at step {resume_index+1}')
            jumps=compile_flow(steps)
            debugger=PlaybackDebugger(self.store,execution_id,self.should_stop)
            repeats: dict[int,int]={}
            index=resume_index
            operations=0
            while index<len(steps):
                self.abort_if_requested()
                operations+=1
                if operations>100000:
                    raise RuntimeError("Workflow exceeded 100000 executed steps (loop safety limit)")
                step=steps[index]
                kind=step["type"]
                step_number=index+1
                debugger.before(step_number)
                debugger.capture(step_number,'before')
                attempts=max(1,1+int(step.get("retry_count",0)))
                attempt=0
                manual_retries=0
                while True:
                    attempt+=1
                    correction=self.store.correction_for(execution_id,step_number)
                    if correction is not None:
                        step=dict(step,params=dict(correction))
                    try:
                        started=time.monotonic()
                        self.store.event(execution_id,"INFO",f"{ACTIONS[kind].name} (attempt {attempt}/{attempts}; before={step.get('delay_before',0)}s; after={step.get('delay_after',0)}s)",step_number)
                        self.on_event("start",step_number,step)
                        self.sleep(step.get("delay_before",0))
                        verification=step.get("verify",{"kind":"none"})
                        before=None
                        if verification.get("kind")=="screen_changed":
                            from .visual_verification import take_sample
                            before=take_sample(self.expand(verification.get("target","")))
                        jump=None
                        if kind=="if_var":
                            params=step.get("params",{})
                            name=self.expand(params["name"])
                            actual=str(self.vars.get(name,""))
                            desired=str(self.expand(params.get("value","")))
                            if not condition(actual,params["operator"],desired):
                                jump=jumps[index]+1
                        elif kind=="else":
                            jump=jumps[index]+1
                        elif kind=="endif":
                            pass
                        elif kind=="repeat":
                            times=int(step.get("params",{}).get("times",0))
                            if times==0:
                                jump=jumps[index]+1
                            else:
                                repeats[index]=times
                                self.vars["loop_iteration"]="1"
                        elif kind=="end_repeat":
                            beginning=jumps[index]
                            if beginning not in repeats:
                                raise RuntimeError("End repeat executed without an active repeat")
                            repeats[beginning]-=1
                            if repeats[beginning]>0:
                                total=int(steps[beginning]["params"]["times"])
                                self.vars["loop_iteration"]=str(total-repeats[beginning]+1)
                                jump=beginning+1
                            else:
                                repeats.pop(beginning)
                        elif kind=="break_loop":
                            beginning=jumps[index]
                            if beginning not in repeats:
                                raise RuntimeError("Break repeat executed outside an active loop")
                            repeats.pop(beginning)
                            jump=jumps[beginning]+1
                        elif kind=="continue_loop":
                            beginning=jumps[index]
                            if beginning not in repeats:
                                raise RuntimeError("Continue repeat executed outside an active loop")
                            jump=jumps[beginning]
                        else:
                            self.run_action(step)
                        self.verify(verification,before)
                        self.sleep(step.get("delay_after",0))
                        self.store.event(execution_id,"SUCCESS",f"Completed in {time.monotonic()-started:.2f}s (action plus delays and verification)",step_number)
                        self.on_event("success",step_number,step)
                        debugger.capture(step_number,'after')
                        debugger.completed(step_number)
                        if jump is None or jump==index+1:
                            self.store.execution_checkpoint(execution_id,step_number)
                        index=jump if jump is not None else index+1
                        break
                    except (Cancelled, DebugAbort):raise
                    except Exception as error:
                        self.store.event(execution_id,"ERROR",f"attempt {attempt}: {type(error).__name__}: {error}",step_number)
                        debugger.capture(step_number,'failed')
                        if attempt>=attempts:
                            if manual_retries>=25 or not debugger.failed(step_number,error):
                                raise
                            manual_retries+=1
                            continue
                        self.sleep(step.get("retry_delay",1.0))
        except (Cancelled, DebugAbort) as error:
            status="cancelled";result=str(error)
        except Exception as error:
            status="failed";result=f"{type(error).__name__}: {error}"
            self.store.event(execution_id,"ERROR",result)
            try:
                from .sounds import Preferences
                if Preferences().get("save_failure_screenshots"):
                    import mss
                    from mss.tools import to_png
                    folder=data_root()/"failures"
                    folder.mkdir(parents=True,exist_ok=True)
                    path=folder/f"job-{job_id}-run-{execution_id}.png"
                    with mss.mss() as capture:
                        shot=capture.grab(capture.monitors[0])
                        to_png(shot.rgb,shot.size,output=str(path))
                    self.store.event(execution_id,"INFO",f"Failure screenshot: {path}")
            except Exception as screenshot_error:
                self.store.event(execution_id,"WARNING",f"Failure screenshot unavailable: {screenshot_error}")
        finally:
            self.cleanup()
            self.store.finish(job_id,execution_id,status,result)
            if self.store.debug_status(execution_id):
                self.store.debug_state(execution_id, status, 0, result if status!='success' else '')
            self.on_event("finish",0,{"status":status,"message":result})
        return status
