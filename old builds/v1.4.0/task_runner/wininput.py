"""Native Windows Unicode text input, independent of PyAutoGUI cursor hooks.

SendInput uses KEYEVENTF_UNICODE (UTF-16 code units) for literal text. This
avoids the GetCursorPos signature conflict seen in existing Windows run logs,
works with international characters, and does not overwrite user clipboard.
"""
from __future__ import annotations
import ctypes
import sys
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
VK_TAB = 0x09
VK_BACK = 0x08


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", INPUTUNION)]


def _keyboard(code: int, down: bool, unicode: bool) -> INPUT:
    flag = (KEYEVENTF_UNICODE if unicode else 0) | (0 if down else KEYEVENTF_KEYUP)
    return INPUT(INPUT_KEYBOARD, INPUTUNION(ki=KEYBDINPUT(
        0 if unicode else code, code if unicode else 0, flag, 0, 0)))


def _send(items: list[INPUT], sender=None):
    if sender is None:
        if sys.platform != "win32":
            raise RuntimeError("Windows SendInput requires an interactive Windows session")
        # A fresh library handle avoids modifying any global PyAutoGUI API function.
        sender = ctypes.WinDLL("user32", use_last_error=True).SendInput
        sender.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        sender.restype = wintypes.UINT
    array = (INPUT * len(items))(*items)
    result = sender(len(items), array, ctypes.sizeof(INPUT))
    if result != len(items):
        raise OSError(f"SendInput delivered {result}/{len(items)} keyboard events; "
                      "check focus, input isolation, and application elevation")


def send_text(text: str, interval: float = 0.02, sleep=None, sender=None):
    """Type arbitrary Unicode; preserve Windows newline/tab semantics.

    The callback `sleep` enables cooperative cancellation between characters.
    The optional sender supports ABI tests without injecting system input.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not 0 <= float(interval) <= 10:
        raise ValueError("typing interval must be 0–10 seconds")
    if sleep is None:
        import time
        sleep = time.sleep
    previous_cr = False
    for character in text:
        if previous_cr and character == "\n":
            previous_cr = False
            continue
        previous_cr = character == "\r"
        if character in "\r\n":
            values = [_keyboard(VK_RETURN, True, False), _keyboard(VK_RETURN, False, False)]
        elif character == "\t":
            values = [_keyboard(VK_TAB, True, False), _keyboard(VK_TAB, False, False)]
        elif character == "\b":
            values = [_keyboard(VK_BACK, True, False), _keyboard(VK_BACK, False, False)]
        else:
            encoded = character.encode("utf-16-le")
            values = []
            for i in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[i:i+2], "little")
                values.extend((_keyboard(unit, True, True), _keyboard(unit, False, True)))
        _send(values, sender)
        sleep(float(interval))
