"""Native Windows pointer input with virtual-desktop (including negative) pixel coordinates.

Keyboard input is handled separately by PyAutoGUI. The mouse helpers here avoid
PyAutoGUI's primary-monitor-only coordinate assumptions on Windows.
"""
import ctypes
import math
import sys
import time
from functools import lru_cache
from ctypes import wintypes

LEFT_DOWN=0x0002
LEFT_UP=0x0004
RIGHT_DOWN=0x0008
RIGHT_UP=0x0010
MIDDLE_DOWN=0x0020
MIDDLE_UP=0x0040
WHEEL=0x0800
BUTTONS={"left":(LEFT_DOWN,LEFT_UP),"right":(RIGHT_DOWN,RIGHT_UP),"middle":(MIDDLE_DOWN,MIDDLE_UP)}


class _POINT(ctypes.Structure):
    _fields_=[("x",wintypes.LONG),("y",wintypes.LONG)]


@lru_cache(maxsize=1)
def _user32():
    if sys.platform!="win32":
        raise RuntimeError("Windows native pointer input requires Windows")
    # Private WinDLL handle: DO NOT mutate ctypes.windll.user32.GetCursorPos.
    # PyAutoGUI defines a different POINT structure and invokes that shared
    # function. Changing its argtypes breaks keyboard input after a mouse click.
    lib=ctypes.WinDLL("user32", use_last_error=True)
    lib.SetCursorPos.argtypes=[ctypes.c_int,ctypes.c_int]
    lib.SetCursorPos.restype=wintypes.BOOL
    lib.GetCursorPos.argtypes=[ctypes.POINTER(_POINT)]
    lib.GetCursorPos.restype=wintypes.BOOL
    lib.mouse_event.argtypes=[wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.c_ulong]
    return lib


def location():
    point=_POINT()
    if not _user32().GetCursorPos(ctypes.byref(point)):
        raise OSError("Cannot read Windows cursor position")
    return point.x,point.y


def emergency_stop():
    # Conventional primary-screen top-left failsafe; supports other monitors at negative coordinates.
    x,y=location()
    if 0<=x<=3 and 0<=y<=3:
        raise RuntimeError("Mouse fail-safe triggered at primary monitor's top-left corner")


def move(x:int,y:int,duration:float=0.0):
    emergency_stop()
    start=location()
    duration=max(0,float(duration))
    steps=max(1,int(duration*60))
    for i in range(1,steps+1):
        f=i/steps
        px=round(start[0]+(x-start[0])*f)
        py=round(start[1]+(y-start[1])*f)
        if not _user32().SetCursorPos(px,py):
            raise OSError(f"SetCursorPos failed at ({px}, {py}); check Windows desktop permissions")
        if duration>0:time.sleep(duration/steps)


def _event(flag:int,data:int=0):
    _user32().mouse_event(flag,0,0,data & 0xFFFFFFFF,0)


def click(x:int,y:int,button="left",clicks=1):
    if button not in BUTTONS:raise ValueError(f"Unsupported mouse button: {button}")
    move(x,y)
    down,up=BUTTONS[button]
    for i in range(int(clicks)):
        _event(down);time.sleep(0.04);_event(up)
        if i<int(clicks)-1:time.sleep(0.09)


def drag(x1:int,y1:int,x2:int,y2:int,duration=0.5):
    move(x1,y1)
    _event(LEFT_DOWN)
    try:move(x2,y2,duration)
    finally:_event(LEFT_UP)


def scroll(notches:int):
    emergency_stop()
    _event(WHEEL,int(notches)*120)


def resolve_target(x: int, y: int, window_title: str = '', window_rx: float = 0,
                   window_ry: float = 0, control_name: str = '',
                   automation_id: str = '') -> tuple[int, int]:
    """Prefer UI Automation targets and window-relative geometry over stale pixels.

    A recorded click with a named window must find that window before it clicks;
    it will never silently click a different application at the old coordinates.
    """
    if not window_title.strip():
        return int(x), int(y)
    from pywinauto import Desktop
    matches = [w for w in Desktop(backend='uia').windows()
               if window_title.casefold() in w.window_text().casefold()]
    if not matches:
        raise LookupError(f'Recorded target window is not open: {window_title}')
    # Multiple windows can share a title. Prefer the one nearest the original
    # recorded click rather than assuming enumeration order is stable.
    def distance(candidate):
        rect=candidate.rectangle()
        center_x=rect.left+rect.width()/2
        center_y=rect.top+rect.height()/2
        return (center_x-x)**2+(center_y-y)**2
    window = min(matches,key=distance)
    box = window.rectangle()
    if box.width() <= 0 or box.height() <= 0:
        raise RuntimeError(f'Window target has invalid bounds: {window_title}')
    expected_x = round(box.left + float(window_rx)*box.width())
    expected_y = round(box.top + float(window_ry)*box.height())
    if automation_id:
        matches_by_id = []
        for element in window.descendants()[:1500]:
            try:
                info = element.element_info
                if info.automation_id != automation_id:
                    continue
                if control_name and info.name != control_name:
                    continue
                if not element.is_visible() or not element.is_enabled():
                    continue
                bounds = element.rectangle()
                if bounds.width()>0 and bounds.height()>0:
                    cx=int(bounds.left + bounds.width()/2)
                    cy=int(bounds.top + bounds.height()/2)
                    matches_by_id.append((cx,cy))
            except Exception:
                continue
        if matches_by_id:
            # An app may reuse an automation ID. Prefer the element nearest
            # the recorded relative location rather than the first match.
            return min(matches_by_id,key=lambda p:(p[0]-expected_x)**2+(p[1]-expected_y)**2)
    return expected_x,expected_y
