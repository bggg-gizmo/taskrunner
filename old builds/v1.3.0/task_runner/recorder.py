"""Desktop input recorder for the visual task wizard.

The capture listener is deliberately isolated from Qt.  It never executes a
recorded action, uploads data, or writes screenshots.  Recording is in-memory
until the user explicitly saves the task.
"""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from .actions import default_step

STOP_COMBINATION = frozenset({'ctrl', 'shift', 'f12'})
MODIFIERS = {'ctrl', 'shift', 'alt', 'cmd'}
SHORTCUT_NAMES = {'enter', 'tab', 'esc', 'backspace', 'delete', 'space', 'up', 'down', 'left', 'right',
                  'home', 'end', 'page_up', 'page_down', 'insert'}


def window_at_point(x: int, y: int) -> dict:
    """Capture stable window-relative geometry without modifying user32 signatures."""
    if sys.platform != 'win32':
        return {}
    import ctypes
    from ctypes import wintypes
    class Point(ctypes.Structure):
        _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]
    class Rect(ctypes.Structure):
        _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                    ('right', wintypes.LONG), ('bottom', wintypes.LONG)]
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.WindowFromPoint.argtypes = [Point]
    u.WindowFromPoint.restype = wintypes.HWND
    u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetAncestor.restype = wintypes.HWND
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.restype = ctypes.c_int
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowTextW.restype = ctypes.c_int
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
    u.GetWindowRect.restype = wintypes.BOOL
    handle = u.WindowFromPoint(Point(x, y))
    if not handle:
        return {}
    root = u.GetAncestor(handle, 2) or handle  # GA_ROOT
    length = u.GetWindowTextLengthW(root)
    if length <= 0:
        return {}
    buffer = ctypes.create_unicode_buffer(length + 1)
    u.GetWindowTextW(root, buffer, length + 1)
    bounds = Rect()
    if not u.GetWindowRect(root, ctypes.byref(bounds)):
        return {}
    candidate = {}
    try:
        from pywinauto import Desktop
        control = Desktop(backend="uia").from_point(x, y)
        info = control.element_info
        # Automation ID is the strongest selector; a name alone can repeat
        # across dozens of buttons and should not be treated as unique.
        if str(info.automation_id or '').strip():
            candidate['automation_id'] = str(info.automation_id)
            if str(info.name or '').strip():
                candidate['control_name'] = str(info.name)
    except Exception:
        pass
    w, h = bounds.right - bounds.left, bounds.bottom - bounds.top
    if w <= 0 or h <= 0:
        return {}
    return {'window_title': buffer.value, 'window_rx': round((x - bounds.left) / w, 6),
            'window_ry': round((y - bounds.top) / h, 6), 'window_width': w, 'window_height': h, **candidate}


def key_name(key) -> tuple[str, str]:
    """Return (normalized name, printable character)."""
    char = getattr(key, 'char', None)
    name = str(getattr(key, 'name', '') or '')
    if not name:
        name = str(key).removeprefix('Key.')
    name = name.lower()
    mapping = {'ctrl_l':'ctrl', 'ctrl_r':'ctrl', 'shift_l':'shift', 'shift_r':'shift',
               'alt_l':'alt', 'alt_r':'alt', 'alt_gr':'alt', 'cmd_l':'cmd', 'cmd_r':'cmd',
               'escape':'esc', 'return':'enter', 'space':'space', 'prior':'page_up', 'next':'page_down'}
    name = mapping.get(name, name)
    if not name or name == 'none':
        name = (char or '').lower()
    return name, char if isinstance(char, str) else ''


class Timeline:
    """Pure, timestamped recorder state. The listener is a replaceable adapter."""
    def __init__(self, clock=None, window_info=None, record_typing=True):
        self.clock = clock or time.monotonic
        self.window_info = window_info or window_at_point
        self.record_typing = bool(record_typing)
        self.steps = []
        self._held = set()
        self._last = None
        self._lock = threading.RLock()
        self.stopped = False
        self._text_step = None
        self._text_time = 0.0
        self._last_window = ""
        self._pressed = {}

    def _append(self, step, now):
        if self.stopped:
            return
        previous = self._last
        if previous is not None:
            step['delay_before'] = round(max(0, min(now - previous, 3600.0)), 3)
        self.steps.append(step)
        self._last = now
        self._text_step = None

    def mouse_click(self, x, y, button='left', pressed=True):
        with self._lock:
            now = self.clock()
            name = str(button)
            if not pressed:
                captured = self._pressed.pop(name, None)
                if captured and not self.stopped:
                    start_x,start_y,started,original = captured
                    if (int(x)-start_x)**2+(int(y)-start_y)**2 >= 100:
                        drag = default_step('drag')
                        drag['params'].update({'x1':start_x,'y1':start_y,
                            'x2':int(x),'y2':int(y),
                            'duration':round(max(.05,min(now-started,3600)),3)})
                        drag['delay_before'] = original['delay_before']
                        try:
                            index = next(i for i,step in enumerate(self.steps) if step is original)
                            self.steps[index] = drag
                            self._last = now
                        except StopIteration:
                            pass
                return
            step = default_step('click')
            step['params'].update({'x': int(x), 'y': int(y), 'button': str(button)})
            info = self.window_info(int(x), int(y))
            if info:
                step['params'].update(info)
                title = info.get('window_title','')
                if title and title != self._last_window:
                    wait = default_step('wait_window')
                    wait['params'].update({'title':title, 'state':'appears', 'timeout':180.0})
                    # Check actual window readiness instead of relying solely
                    # on the captured pause while a slow program boots.
                    self._append(wait, now)
                self._last_window = title
            # Merge a real double click, rather than two unrelated steps.
            if self.steps and self.steps[-1]['type']=='click' and self._last is not None \
               and now-self._last < .35 and self.steps[-1]['params'].get('x')==int(x) \
               and self.steps[-1]['params'].get('y')==int(y) \
               and self.steps[-1]['params'].get('button')==str(button):
                self.steps[-1]['params']['clicks']+=1
                self._last=now
                return
            self._append(step, now)
            self._pressed[name]=(int(x),int(y),now,step)

    def mouse_scroll(self, x, y, dx, dy):
        with self._lock:
            if not dy:
                return
            step = default_step('scroll')
            step['params']['amount'] = int(dy)
            self._append(step, self.clock())

    def key_down(self, name, char=''):
        name = name.lower()
        with self._lock:
            if self.stopped:
                return
            if name in self._held:
                return
            self._held.add(name)
            if STOP_COMBINATION.issubset(self._held):
                self.stopped = True
                return
            # Do not add stop-key prefixes or any other pressed modifier as actions.
            if name in MODIFIERS:
                return
            now = self.clock()
            held_modifiers = self._held.intersection(MODIFIERS)
            if held_modifiers and not (held_modifiers == {'shift'} and char and char.isprintable()):
                step = default_step('hotkey')
                step['params']['keys'] = '+'.join(sorted(held_modifiers) + [name])
                self._append(step, now)
            elif self.record_typing and (char and char.isprintable() and char not in ('\r', '\n', '\t')):
                if (self._text_step is not None and now - self._text_time < 1.5
                        and self._text_step is self.steps[-1]):
                    self._text_step['params']['text'] += char
                else:
                    step = default_step('type')
                    step['params']['text'] = char
                    self._append(step, now)
                    self._text_step = step
                self._text_time = now
                self._last = now
            elif name in SHORTCUT_NAMES or name.startswith('f') and name[1:].isdigit():
                step = default_step('key')
                step['params']['key'] = name
                self._append(step, now)

    def key_up(self, name):
        with self._lock:
            self._held.discard(name.lower())

    def result(self):
        with self._lock:
            return [dict(step, params=dict(step['params']), verify=dict(step['verify'])) for step in self.steps]


class DesktopRecorder:
    """Global mouse/keyboard listener started after the Task Runner UI hides."""
    def __init__(self, record_typing=True):
        self.timeline = Timeline(record_typing=record_typing)
        self.listeners = []
        self.error = None

    @property
    def stopped(self):
        return self.timeline.stopped or self.error is not None

    def start(self):
        if sys.platform != 'win32':
            raise OSError('Global desktop recording requires Windows')
        from pynput import mouse, keyboard
        def clicked(x, y, button, pressed):
            try:self.timeline.mouse_click(x, y, getattr(button, 'name', 'left'), pressed)
            except Exception as e:self.error = e
        def scrolled(x, y, dx, dy):
            try:self.timeline.mouse_scroll(x, y, dx, dy)
            except Exception as e:self.error = e
        def down(key):
            try:self.timeline.key_down(*key_name(key))
            except Exception as e:self.error = e
        def up(key):
            try:self.timeline.key_up(key_name(key)[0])
            except Exception as e:self.error = e
        self.listeners = [mouse.Listener(on_click=clicked, on_scroll=scrolled),
                          keyboard.Listener(on_press=down, on_release=up)]
        try:
            for listener in self.listeners:listener.start()
        except Exception:
            self.stop()
            raise

    def stop(self):
        self.timeline.stopped = True
        for listener in self.listeners:
            listener.stop()
        for listener in self.listeners:
            if listener.is_alive() and threading.current_thread() is not listener:
                listener.join(timeout=2)
        return self.timeline.result()
