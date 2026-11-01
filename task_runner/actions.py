"""Explicit workflow action schema used by GUI and executor."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"
    default: object = ""
    options: tuple[str, ...] = ()
    required: bool = False

@dataclass(frozen=True)
class Action:
    name: str
    category: str
    description: str
    fields: tuple[Field, ...]

T=Field
ACTIONS = {
 "memory_snapshot": Action("Record RAM / VRAM snapshot", "Resource monitor",
     "Log current system RAM, the selected PID process-tree RAM and optional NVIDIA compute-process VRAM; save values to workflow variables.",
     (T("pid","PID (blank = last launched process; 0 = system only)","text",""),
      T("include_gpu","Check NVIDIA compute VRAM (optional)","bool",False))),
 "memory_watch_start": Action("Start RAM / VRAM guard", "Resource monitor",
     "Watch a process tree during later actions. Zero thresholds disable that check. Warnings are default; optionally cancel workflow or stop ONLY an explicitly owned launched program.",
     (T("pid","PID (blank = last launched program)","text",""),
      T("process_ram_limit_mb","Process tree RAM limit MiB (0 = off)","float",0.0),
      T("minimum_available_ram_mb","Minimum free system RAM MiB (0 = off)","float",0.0),
      T("process_gpu_vram_limit_mb","NVIDIA compute VRAM limit MiB (0 = off)","float",0.0),
      T("interval","Polling every (seconds)","float",2.0),
      T("response","Threshold response","choice","warn",("warn","cancel_workflow","terminate_owned")))),
 "memory_watch_stop": Action("Stop RAM / VRAM guard", "Resource monitor",
     "Stop this workflow's resource watcher; save the peak RAM and sample count in workflow variables.", ()),

 "click_image": Action("Click on-screen image", "Visual triggers", "Find a matching button or icon in a screen region, then click its current position instead of an old fixed coordinate.", (T("image","Reference image PNG","path","",required=True),T("region","Search region x,y,width,height (blank = all monitors)","text",""),T("confidence","Confidence (0–1)","float",0.88),T("timeout","Wait for image (seconds)","float",45.0),T("poll","Check every (seconds)","float",0.4),T("button","Button","choice","left",("left","right","middle")))),
 "wait_screen": Action("Wait for visual change", "Visual triggers", "Continue when a selected screen region changes, or a reference image becomes visible/hidden. Works with desktop apps.", (T("mode","Condition","choice","changed",("changed","image_appears","image_disappears")),T("region","Screen region: x,y,width,height (blank = full screen)","text",""),T("image","Reference image file (for image conditions)","path",""),T("confidence","Image matching confidence","float",0.88),T("timeout","Wait up to (seconds)","float",180.0),T("poll","Check every (seconds)","float",0.5))),
 "wait_content": Action("Wait for text / code / output", "Visual triggers", "Wait for text in a Windows window, open browser page, file, or clipboard; use contains, absent, or changed conditions.", (T("source","Monitor","choice","window",("window","browser","file","clipboard")),T("target","Window title, CSS selector, file path (blank = clipboard)","text",""),T("condition","Condition","choice","contains",("contains","absent","changed")),T("text","Expected text (contains/absent)","multiline",""),T("timeout","Wait up to (seconds)","float",180.0),T("poll","Check every (seconds)","float",0.5),T("name","Store captured text as variable","text","observed_text"))),
 "capture_live_start": Action("Start live output / image capture", "Output capture", "Collect changed screen images or text from a window, log file, or clipboard while later workflow steps continue.", (T("mode","Capture source","choice","screen",("screen","window","file","clipboard","clipboard_image","image_folder")),T("source","Window title or file path","text",""),T("destination","Output folder","path","",required=True),T("region","Screen region x,y,width,height (optional)","text",""),T("interval","Capture every (seconds)","float",0.5),T("max_captures","Maximum changed captures","int",1000))),
 "capture_live_stop": Action("Stop live output capture", "Output capture", "Stop background capture and write a JSON manifest listing every saved image/text snapshot.", ()),
 "clipboard_image": Action("Save clipboard image", "Output capture", "Preserve an image already copied to the Windows clipboard as a PNG file.", (T("path","Save image to PNG","path","",required=True),)),
 "capture_program_output": Action("Run process and continuously save output", "Output capture", "Run an executable, stream stdout/stderr to a UTF-8 log as it appears; wait for process exit or a timeout.", (T("path","Executable path","path","",required=True),T("arguments","Arguments","text",""),T("output","Output log file","path","",required=True),T("timeout","Maximum seconds","float",300.0))),
 "click": Action("Click target", "Desktop", "Click an absolute screen position; use a screenshot to choose the point.", (T("x","Screen X","int",0),T("y","Screen Y","int",0),T("button","Mouse button","choice","left",("left","right","middle")),T("clicks","Clicks","int",1),T("window_title","Target window title (optional)","text",""),T("window_rx","Horizontal position inside window (0–1)","float",0.0),T("window_ry","Vertical position inside window (0–1)","float",0.0),T("control_name","UI Automation control name (optional)","text",""),T("automation_id","UI Automation ID (optional)","text",""),
       T("reference_image","Reference image (optional)","path",""),
       T("confidence","Minimum visual match (0–1)","float",0.88),
       T("target_timeout","Wait for precise target (seconds)","float",20.0),
       T("allow_relative_fallback","Allow original window-relative fallback","bool",True),
       T("strict_target","Require verified control or image (no coordinate fallback)","bool",False))),
 "move": Action("Move mouse", "Desktop", "Move pointer to an absolute screen position.", (T("x","Screen X","int",0),T("y","Screen Y","int",0),T("duration","Duration (seconds)","float",0.2))),
 "drag": Action("Drag mouse", "Desktop", "Drag between two points, with configurable duration.", (T("x1","From X","int",0),T("y1","From Y","int",0),T("x2","To X","int",0),T("y2","To Y","int",0),T("duration","Duration (seconds)","float",0.5))),
 "scroll": Action("Scroll wheel", "Desktop", "Positive for up, negative for down.", (T("amount","Notches","int",-3),)),
 "type": Action("Type text", "Keyboard", "Type literal text or ${variables}; supports Unicode using clipboard paste.", (T("text","Text to type","multiline","",required=True),T("interval","Key interval (seconds)","float",0.02))),
 "key": Action("Press key", "Keyboard", "Press a keyboard key such as enter, tab, escape, or f5.", (T("key","Key","text","enter",required=True),T("presses","Repetitions","int",1))),
 "hotkey": Action("Keyboard shortcut", "Keyboard", "Keys separated by +, e.g. ctrl+shift+s.", (T("keys","Shortcut","text","ctrl+c",required=True),)),
 "paste": Action("Paste clipboard", "Keyboard", "Paste using Ctrl+V.", ()),
 "copy": Action("Copy selection", "Keyboard", "Copy using Ctrl+C, then capture clipboard text in ${clipboard}.", ()),
 "wait": Action("Wait", "Flow", "Pause the workflow for a fixed number of seconds.", (T("seconds","Seconds","float",1.0),)),
 "wait_window": Action("Wait for Windows window", "Windows", "Wait until a titled window appears or disappears; useful for slow launches or closing programs.", (T("title","Window title contains","text","",required=True),T("state","Wait until","choice","appears",("appears","disappears")),T("timeout","Maximum wait (seconds)","float",30.0))),
 "wait_file": Action("Wait for file or folder", "Files", "Wait until a file or directory exists, or has been removed.", (T("path","File or folder path","path","",required=True),T("state","Wait until","choice","exists",("exists","missing")),T("timeout","Maximum wait (seconds)","float",30.0))),
 "browser_wait_state": Action("Wait for browser element state", "Browser", "Wait for visible, hidden, attached, or detached element.", (T("selector","Selector","text","",required=True),T("state","Desired state","choice","visible",("visible","hidden","attached","detached")),T("timeout","Maximum wait (seconds)","float",20.0))),
 "browser_select": Action("Select browser dropdown choice", "Browser", "Choose a native HTML select option by label, value or index, without screen coordinates.", (T("selector","Select CSS selector","text","select",required=True),T("method","Match by","choice","label",("label","value","index")),T("choice","Option label, value, or zero-based index","text","",required=True))),
 "browser_expand_all": Action("Expand browser page dropdowns", "Browser", "Open HTML details and ARIA disclosures; collect native select choices without changing their selected values.", (T("selector","Within CSS selector","text","body",required=True),T("max_controls","Maximum controls","int",250),T("name","Result JSON variable","text","expanded_controls",required=True))),
 "browser_scroll_text": Action("Capture entire scrolling web text", "Browser", "Scroll lazy-loaded pages and nested scrollers, collect text into a variable; optionally copy to clipboard.", (T("selector","Page/container selector","text","body",required=True),T("name","Text output variable","text","page_text",required=True),T("max_scrolls","Max scroll increments","int",100),T("step_px","Pixels each increment","int",700),T("pause_seconds","Pause after scroll (seconds)","float",0.3),T("copy_to_clipboard","Copy gathered text to clipboard","bool",True))),
 "desktop_expand_all": Action("Inspect Windows app dropdowns", "Windows", "Expand UI Automation combo/disclosure controls sequentially and collect their choices.", (T("title","Window title contains (blank = active)","text",""),T("max_controls","Maximum controls","int",100),T("name","Result JSON variable","text","window_dropdowns",required=True))),
 "desktop_scroll_text": Action("Capture scrolling Windows app text", "Windows", "Read UIA document text or scroll and copy with Ctrl+A/C in an interactive window.", (T("title","Window title contains (blank = active)","text",""),T("name","Text output variable","text","window_text",required=True),T("max_scrolls","Maximum scroll increments","int",50),T("wheel_notches","Scroll notches per step","int",5),T("pause_seconds","Pause after scroll (seconds)","float",0.3),T("copy_to_clipboard","Copy gathered text to clipboard","bool",True))),
 "wait_ocr": Action("Wait for visible text (offline OCR)", "Visual triggers", "Recognize text on a chosen desktop region with bundled local OCR and proceed only when the condition stays stable across consecutive screenshots.", (T("region","Screen region x,y,width,height (blank = all screens)","text",""),T("condition","Wait until","choice","contains",("contains","absent","changed")),T("text","Expected screen text","text",""),T("confidence","Minimum OCR confidence (0–1)","float",0.45),T("stable_frames","Consecutive matching screenshots","int",2),T("case_sensitive","Case-sensitive match","bool",False),T("timeout","Timeout (seconds)","float",180.0),T("poll","Poll every seconds","float",0.8),T("name","Save recognized text as variable","text","ocr_text",required=True))),
 "load_secret": Action("Read protected vault credential", "Security", "Load a Windows DPAPI-protected local secret into a workflow variable without putting the value in task JSON.", (T("secret_name","Stored vault name","text","",required=True),T("name","Variable name","text","credential",required=True))),
 "run_module": Action("Run reusable task module", "Flow", "Run the actions of a saved task by its ID in the current workflow context. Refuses cycles, preserves variables, and never activates the module's schedule.", (T("task_id","Saved Task ID","int",1,required=True),)),
 "set_var": Action("Set variable", "Flow", "Set a variable available to later steps as ${variable_name}.", (T("name","Variable name","text","result",required=True),T("value","Variable value","multiline",""))),
 "clipboard_read": Action("Read clipboard", "Flow", "Store clipboard text in the named variable and ${clipboard}.", (T("name","Variable name","text","clipboard",required=True),)),
 "clipboard_write": Action("Write clipboard", "Flow", "Put literal or variable-expanded text on the clipboard.", (T("text","Clipboard text","multiline","",required=True),)),
 "launch": Action("Launch program", "Windows", "Start an executable and optionally wait for its window to actually appear.", (T("path","Executable path","path","",required=True),T("arguments","Arguments","text",""),T("cwd","Working directory","path",""),T("wait_for_exit","Wait for process exit","bool",False),T("wait_for_window_title","Wait for window title containing (optional)","text",""),T("window_timeout","Wait for window up to (seconds)","float",30.0))),
 "open_path": Action("Open file or folder", "Windows", "Open a file/directory/URL and optionally wait for a matching window.", (T("path","Path or URL","path","",required=True),T("wait_for_window_title","Wait for window title containing (optional)","text",""),T("window_timeout","Wait for window up to (seconds)","float",30.0))),
 "activate": Action("Activate window", "Windows", "Bring an existing application window to the foreground by title substring.", (T("title","Window title contains","text","",required=True),T("timeout","Wait up to seconds","float",10.0))),
 "close_window": Action("Close active window", "Windows", "Send Alt+F4 to the currently active window.", ()),
 "save_clipboard": Action("Save clipboard to file", "Files", "Write clipboard text to a real file at the chosen path.", (T("path","Output filename","path","",required=True),T("append","Append instead of replace","bool",False))),
 "write_file": Action("Write text file", "Files", "Write text or variables to a file, creating parent directories.", (T("path","Output filename","path","",required=True),T("text","Text","multiline","",required=True),T("append","Append instead of replace","bool",False))),
 "read_file": Action("Read text file", "Files", "Read a text file into a variable.", (T("path","Filename","path","",required=True),T("name","Variable name","text","file_text",required=True))),
 "browser_open": Action("Open browser URL", "Browser", "Launch Chromium with Playwright if necessary, navigate to URL.", (T("url","URL","text","",required=True),T("headless","Headless browser","bool",False),T("wait_until","Wait until","choice","domcontentloaded",("load","domcontentloaded","networkidle")))),
 "browser_click": Action("Click browser element", "Browser", "Playwright selector, e.g. button:has-text('Submit').", (T("selector","Locator / CSS selector","text","",required=True),T("timeout","Timeout (seconds)","float",20.0))),
 "browser_fill": Action("Fill browser field", "Browser", "Fill input located by Playwright selector.", (T("selector","Locator / CSS selector","text","",required=True),T("text","Text to enter","multiline","",required=True),T("timeout","Timeout (seconds)","float",20.0))),
 "browser_press": Action("Press browser key", "Browser", "Press a key on an element or the page.", (T("selector","Selector (empty = page)","text",""),T("key","Key name","text","Enter",required=True))),
 "browser_wait": Action("Wait for browser element", "Browser", "Wait until selector becomes visible.", (T("selector","Selector","text","",required=True),T("timeout","Timeout (seconds)","float",20.0))),
 "browser_text": Action("Extract browser text", "Browser", "Extract element text to a variable.", (T("selector","Selector","text","body",required=True),T("name","Variable name","text","web_text",required=True))),
 "browser_html": Action("Get browser HTML", "Browser", "Capture rendered page HTML to a variable.", (T("name","Variable name","text","html",required=True),)),
 "soup_select": Action("Parse HTML with Beautiful Soup", "Web parsing", "Parse HTML from a previous browser_html or other variable and extract CSS selector matches.", (T("source","HTML variable","text","html",required=True),T("selector","CSS selector","text","title",required=True),T("attribute","Attribute (empty = text)","text",""),T("name","Output variable","text","parsed",required=True),T("all_matches","All matches","bool",False))),
 "browser_screenshot": Action("Save browser screenshot", "Browser", "Full-page browser screenshot to a PNG.", (T("path","PNG output path","path","",required=True),T("full_page","Full page","bool",True))),
 "screenshot": Action("Save desktop screenshot", "Desktop", "Capture the entire virtual desktop and save as PNG.", (T("path","PNG output path","path","",required=True),)),
 "shutdown": Action("Shutdown Windows", "System", "Request Windows shutdown; scheduled actions require an explicitly saved shutdown step.", (T("delay","Countdown seconds","int",60),)),
 "abort_shutdown": Action("Cancel pending shutdown", "System", "Cancel an already-requested Windows shutdown.", ()),
 "http_get": Action("Fetch HTML (no browser)", "Web parsing", "Download HTML directly with Python, then parse it with Beautiful Soup. Stores HTML and HTTP status.", (T("url","URL","text","",required=True), T("name","HTML output variable","text","html",required=True),T("timeout","Request timeout (seconds)","float",30.0))),
 "browser_close": Action("Close automated browser", "Browser", "Close Playwright's Chromium browser before continuing desktop tasks.", ()),
 "browser_download": Action("Download browser file", "Browser", "Click an element and save the resulting Playwright download.", (T("selector","Download trigger selector","text","",required=True),T("path","Save to absolute path","path","",required=True),T("timeout","Download timeout (seconds)","float",60.0))),
 "mkdir": Action("Create folder", "Files", "Create a folder and required parent folders.", (T("path","Directory path","path","",required=True),)),
 "copy_file": Action("Copy file", "Files", "Copy a file to a destination and preserve file metadata.", (T("source","Source file","path","",required=True),T("destination","Destination file","path","",required=True),T("overwrite","Allow overwrite","bool",False))),
 "move_file": Action("Move file", "Files", "Move or rename a file or folder.", (T("source","Source path","path","",required=True),T("destination","Destination path","path","",required=True),T("overwrite","Allow overwrite","bool",False))),
 "delete_file": Action("Delete file", "Files", "Delete a file (permanent; not Recycle Bin).", (T("path","Path to file","path","",required=True),)),
 "list_dir": Action("List directory", "Files", "Store filenames in a variable, separated by newline characters.", (T("path","Directory","path","",required=True),T("name","Output variable","text","files",required=True))),
 "if_var": Action("If variable matches", "Flow", "Run the following actions only when the condition is true. Close with End if; optional Else.", (T("name","Variable name","text","",required=True),T("operator","Comparison","choice","equals",("equals","not equals","contains","not contains","empty","not empty","regex matches")),T("value","Compare with","text",""))),
 "else": Action("Else", "Flow", "Alternate branch of the closest matching If variable action.", ()),
 "endif": Action("End if", "Flow", "Close the nearest matching If variable block.", ()),
 "repeat": Action("Repeat actions", "Flow", "Repeat actions between this step and End repeat; nested blocks are supported.", (T("times","Iterations (0–10000)","int",2),)),
 "end_repeat": Action("End repeat", "Flow", "Close the nearest Repeat actions block.", ()),
 "break_loop": Action("Break repeat loop", "Flow", "Exit the innermost active Repeat block immediately.", ()),
 "continue_loop": Action("Continue repeat loop", "Flow", "Skip to the next iteration of the innermost Repeat block.", ()),
}

VERIFY_KINDS = (
 ("none","No verification"), ("file_exists","File exists"),
 ("window_exists","Window title exists"), ("window_missing","Window is closed"),
 ("file_missing","File or folder removed"), ("clipboard_contains","Clipboard contains text"),
 ("browser_visible","Browser element visible"), ("browser_hidden","Browser element hidden"),
 ("image_visible","Reference image visible on screen"),
 ("screen_changed","Screen region changed after action (optional x,y,width,height)")
)


def default_step(action_type: str) -> dict:
    action = ACTIONS[action_type]
    return {"type": action_type,
            "params": {field.key: field.default for field in action.fields},
            "verify": {"kind":"none", "target":"", "timeout":10.0},
            "retry_count":2 if action_type in ("click", "move", "drag", "browser_click", "browser_fill", "browser_select", "activate", "wait_window", "wait_file", "browser_wait_state", "wait_screen", "wait_content") else 0,
            "retry_delay":1.0,
            "delay_before":0.0,
            "delay_after":1.0 if action_type in ("click", "open_path", "launch", "close_window", "browser_click", "browser_open", "browser_select") else 0.0}


def describe_step(step: dict) -> str:
    action = ACTIONS.get(step.get("type"))
    if not action:
        return f"UNKNOWN: {step.get('type')}"
    params=step.get("params", {})
    detail = next((str(params[field.key]) for field in action.fields
                   if field.key in ("path","url","selector","text","title","seconds","keys","key")
                   and params.get(field.key) not in ("", None)), "")
    if len(detail)>70:
        detail=detail[:67]+"..."
    return action.name + ("  —  " + detail.replace("\n"," ↵ ") if detail else "")
