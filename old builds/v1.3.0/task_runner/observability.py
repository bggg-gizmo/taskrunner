"""Wait predicates and user-requested live-output/image capture.

All continuous monitors are bounded, cooperative, and owned by one workflow run.
They never monitor or persist user activity unless a saved task explicitly starts
capture. Monitoring stops on cancellation, completion, or explicit stop action.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def window_text(title: str = '') -> str:
    from pywinauto import Desktop
    windows = Desktop(backend='uia').windows()
    window = next((w for w in windows if title.casefold() in w.window_text().casefold()), None) if title else Desktop(backend='uia').from_handle(__import__('ctypes').windll.user32.GetForegroundWindow())
    if window is None:
        raise LookupError(f'No window matching {title!r}')
    chunks = [window.window_text()]
    for c in window.descendants()[:1500]:
        try:
            text = c.window_text()
            if text and text not in chunks:
                chunks.append(text)
            if c.element_info.control_type in ('Edit', 'Document'):
                pattern = c.iface_value
                val = pattern.CurrentValue
                if val and val not in chunks:
                    chunks.append(val)
        except Exception:
            pass
    return '\n'.join(chunks)


def screen_image(region: str = ''):
    from .visual_verification import take_sample
    return take_sample(region)


def image_location(template: str, region: str = '', confidence: float = 0.88):
    """Return absolute virtual-desktop click point for a matched reference image."""
    from .visual_verification import parse_region
    import cv2
    import mss
    import numpy as np
    from PIL import Image
    from pathlib import Path
    path = Path(template).expanduser()
    if not path.is_file():raise FileNotFoundError(path)
    with mss.mss() as camera:
        bounds = parse_region(region) if region else camera.monitors[0]
        frame = np.asarray(Image.frombytes('RGB',
            (int(bounds['width']),int(bounds['height'])),
            camera.grab(bounds).rgb))
    reference = np.asarray(Image.open(path).convert('RGB'))
    height,width = reference.shape[:2]
    if width > frame.shape[1] or height > frame.shape[0]:return None
    a=cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY)
    b=cv2.cvtColor(reference,cv2.COLOR_RGB2GRAY)
    if np.std(b)<2:
        scores=cv2.matchTemplate(a,b,cv2.TM_SQDIFF_NORMED)
        value,_,loc,_=cv2.minMaxLoc(scores)
        if value > 1-confidence:return None
    else:
        scores=cv2.matchTemplate(a,b,cv2.TM_CCOEFF_NORMED)
        _,value,_,loc=cv2.minMaxLoc(scores)
        if value < confidence:return None
    return (int(bounds['left']+loc[0]+width/2),int(bounds['top']+loc[1]+height/2))


def image_match(template: str, region: str = '', confidence: float = 0.88) -> bool:
    from pathlib import Path
    import cv2
    import numpy as np
    from PIL import Image
    file = Path(template).expanduser()
    if not file.is_file():
        raise FileNotFoundError(file)
    frame = np.asarray(screen_image(region).convert('RGB'))
    templ = np.asarray(Image.open(file).convert('RGB'))
    h, w = templ.shape[:2]
    if w > frame.shape[1] or h > frame.shape[0]:
        return False
    if w == frame.shape[1] and h == frame.shape[0]:
        # Equal-size exact references should not be matched with degenerate
        # constant-template normalized cross-correlation.
        return float(np.mean(cv2.absdiff(frame, templ))) <= (1 - confidence) * 255
    a = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    b = cv2.cvtColor(templ, cv2.COLOR_RGB2GRAY)
    result = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
    if not np.isfinite(result).all() or np.std(b) < 2:
        result = cv2.matchTemplate(a, b, cv2.TM_SQDIFF_NORMED)
        return float(np.min(result)) <= (1-confidence)
    return float(result.max()) >= confidence


def wait_until(predicate: Callable[[], bool], timeout: float, poll: float = 0.25,
               sleep=None, abort=None) -> None:
    clock = time.monotonic
    deadline = clock() + float(timeout)
    while True:
        if abort:abort()
        try:
            if predicate():return
        except (LookupError, FileNotFoundError):
            pass
        if clock() >= deadline:
            raise TimeoutError('Timed out waiting for the requested condition')
        (sleep or time.sleep)(min(poll, max(.01, deadline - clock())))


def safe_output(base: str) -> Path:
    path = Path(base).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


class LiveCapture:
    """Captures evolving output without blocking subsequent workflow actions."""
    def __init__(self, mode: str, destination: str, source: str = '', interval: float = .5,
                 max_captures: int = 1000, region: str = '', stop_event=None,
                 on_capture=None, max_bytes: int = 536870912):
        if mode not in ('screen', 'clipboard', 'clipboard_image', 'image_folder', 'file', 'window'):
            raise ValueError(f'Unsupported live capture source: {mode}')
        if mode in ('file','window','image_folder') and not source.strip():
            raise ValueError(f'{mode} capture requires a file path or window title')
        if not 0.1 <= float(interval) <= 60:
            raise ValueError('Capture interval must be 0.1–60 seconds')
        if not 1 <= int(max_captures) <= 100000:
            raise ValueError('Capture maximum must be 1–100000')
        self.mode, self.source, self.region = mode, source, region
        self.destination = safe_output(destination)
        self.interval, self.max_captures = float(interval), int(max_captures)
        self.stop_event = stop_event or threading.Event()
        self.on_capture = on_capture
        self.thread = None
        self.count = 0
        self.error = None
        self.files = []
        self.max_bytes = int(max_bytes)
        self.bytes_written = 0
        self._previous = None
        self._sequence = 0
        self._image_observations = {}
        self._images_copied = set()

    def sample(self):
        if self.mode == 'screen':
            from .visual_verification import significant_change
            frame = screen_image(self.region)
            previous = self._previous
            changed = previous is None or significant_change(previous,frame)
            self._previous = frame.copy()
            return frame if changed else None
        if self.mode == 'clipboard_image':
            from PIL import Image, ImageGrab
            import hashlib
            frame = ImageGrab.grabclipboard()
            if not isinstance(frame, Image.Image):return None
            digest = hashlib.sha256(frame.tobytes()).hexdigest()
            if digest == self._previous:return None
            self._previous = digest
            return frame
        if self.mode == 'clipboard':
            import pyperclip
            value = pyperclip.paste()
        elif self.mode == 'window':
            value = window_text(self.source)
        else:
            file = Path(self.source).expanduser()
            if not file.exists():return None
            if not file.is_file():raise ValueError('Capture source must be a regular file')
            # Bound file size in the background so a huge log does not exhaust RAM.
            with file.open('rb') as stream:
                size = file.stat().st_size
                stream.seek(max(0,size-4_000_000))
                value = stream.read().decode('utf-8', errors='replace')
        if value == self._previous:return None
        self._previous = value
        return value

    def _copy_new_image(self):
        """Copy an output image once its size/mtime is stable across polls."""
        from .fileops import atomic_copy_file
        directory = Path(self.source).expanduser()
        if not directory.exists():return None
        if not directory.is_dir():raise ValueError('Image output source must be a directory')
        candidates = sorted((f for f in directory.iterdir() if f.is_file()
                             and f.suffix.casefold() in {'.png','.jpg','.jpeg','.webp','.bmp','.gif'}),
                             key=lambda f: (f.stat().st_mtime_ns, f.name))
        for candidate in candidates[:5000]:
            stat = candidate.stat()
            marker = (str(candidate.resolve()),stat.st_mtime_ns,stat.st_size)
            if marker in self._images_copied:continue
            previous=self._image_observations.get(str(candidate))
            self._image_observations[str(candidate)] = marker
            if previous != marker or stat.st_size==0:continue
            if self.bytes_written + stat.st_size > self.max_bytes:
                self.stop_event.set()
                self.error = f'Capture storage limit reached ({self.max_bytes} bytes)'
                return None
            self._sequence += 1
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
            target=self.destination/f'{stamp}-{self._sequence:06d}-{candidate.name}'
            atomic_copy_file(candidate,target,overwrite=False)
            self._images_copied.add(marker)
            self.files.append(str(target))
            self.count += 1
            self.bytes_written += target.stat().st_size
            if self.on_capture:self.on_capture(target)
            return target
        return None

    def capture(self):
        if self.mode=='image_folder':return self._copy_new_image()
        value = self.sample()
        if value is None:return None
        self._sequence += 1
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        suffix = '.png' if self.mode in ('screen','clipboard_image') else '.txt'
        path = self.destination / f'{stamp}-{self._sequence:06d}{suffix}'
        if self.mode in ('screen','clipboard_image'):
            value.save(path, format='PNG')
        else:
            # Capture complete observed text for each distinct update. No
            # clipboard modifications or destructive source operations.
            path.write_text(str(value), encoding='utf-8')
        self.files.append(str(path))
        self.bytes_written += path.stat().st_size
        self.count += 1
        if self.bytes_written >= self.max_bytes:
            self.stop_event.set()
            self.error = f"Capture storage limit reached ({self.max_bytes} bytes)"
        if self.on_capture:self.on_capture(path)
        return path

    def _work(self):
        while not self.stop_event.is_set() and self.count < self.max_captures:
            try:
                self.capture()
            except (LookupError, FileNotFoundError):
                pass
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'
                break
            if self.stop_event.wait(self.interval):break

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Capture already started')
        self.thread = threading.Thread(target=self._work, name='TaskRunnerLiveCapture', daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=max(3.0, self.interval+2))
        manifest = self.destination / 'capture-manifest.json'
        manifest.write_text(json.dumps({'mode': self.mode, 'source': self.source,
                   'region': self.region, 'files': self.files, 'error': self.error,
                   'captured': self.count, 'bytes_written': self.bytes_written}, indent=2), encoding='utf-8')
        return manifest
