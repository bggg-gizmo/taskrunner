"""Bounded, cancellable browser and Windows UIA collection helpers.

Browser disclosures are actual openable DOM controls. HTML <select> elements
cannot all be kept visually open, so their choices are enumerated instead.
Native ComboBox lists similarly expand one at a time using UI Automation.
"""
from __future__ import annotations

import json
import time
from typing import Callable


def expand_browser_controls(page, selector: str = "body", max_controls: int = 250,
                            pause: Callable[[float], None] | None = None) -> dict:
    """Expand native HTML details and ARIA controls; collect select choices.

    Does not submit forms or change <select> values. Playwright keeps the
    original page context and may trigger site-defined disclosure handlers.
    """
    if not 1 <= max_controls <= 2000:
        raise ValueError("max_controls must be 1–2000")
    pause = pause or (lambda _: None)
    host = page.locator(selector).first
    host.wait_for(state="attached", timeout=20000)
    # Details is a semantic disclosure and can be opened without a click.
    opened_details = host.evaluate("""(root, limit) => {
      const nodes = [root, ...root.querySelectorAll('details')].filter(e => e.matches('details') && !e.open);
      for (const e of nodes.slice(0,limit)) e.open = true;
      return Math.min(nodes.length,limit);
    }""", max_controls)
    opened_aria = 0
    seen = set()
    # Re-query after each click because expanding a menu may mutate the DOM.
    for _ in range(max_controls):
        candidates = host.locator('[aria-expanded="false"]')
        found = False
        for i in range(min(candidates.count(), max_controls)):
            node = candidates.nth(i)
            try:
                if not node.is_visible() or not node.is_enabled():
                    continue
                signature = node.evaluate("""el => {
                    let n=el, path='';
                    while (n && n.nodeType===1 && path.length<400) {
                      const index = n.parentElement ? Array.prototype.indexOf.call(n.parentElement.children,n) : 0;
                      path = n.tagName+':'+index+'/'+path;
                      n=n.parentElement;
                    }
                    return path;
                }""")
                if signature in seen:
                    continue
                seen.add(signature)
                node.click(timeout=2000)
                opened_aria += 1
                pause(0.05)
                found = True
                break
            except Exception:
                continue  # Detached, covered or site-controlled element.
        if not found:
            break
    options = host.evaluate("""root => Array.from(root.querySelectorAll('select')).map(select => ({
        name: select.name || select.id || '(unnamed)',
        options: Array.from(select.options).map(o => ({label: o.text, value:o.value}))
    }))""")
    return {"details_opened": opened_details, "aria_opened": opened_aria,
            "selects": options, "select_count": len(options),
            "note": "HTML select options are listed; browser native choice popups cannot all stay expanded."}


def capture_browser_scrolling_text(page, selector: str = "body", max_scrolls: int = 100,
                                   step_px: int = 700, pause_seconds: float = 0.3,
                                   pause: Callable[[float], None] | None = None) -> tuple[str, int]:
    """Scroll page and descendant scroll containers to load text then capture.

    Capture every state to retain text removed by virtualized lists. Each
    already-seen line is deduplicated across snapshots (known tradeoff for
    repeated identical lines); the captured text can be placed on clipboard.
    """
    if not 1 <= int(max_scrolls) <= 10000:
        raise ValueError("max_scrolls must be 1–10000")
    if not 1 <= int(step_px) <= 5000:
        raise ValueError("step_px must be 1–5000")
    if not 0 <= float(pause_seconds) <= 60:
        raise ValueError("pause_seconds must be 0–60")
    pause = pause or (lambda _: None)
    host = page.locator(selector).first
    host.wait_for(state="visible",timeout=20000)
    lines: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    scrolls = 0
    still = 0
    for index in range(max_scrolls + 1):
        text = host.inner_text(timeout=30000)
        if len(text) > 5_000_000:
            raise ValueError("Visible page text exceeds 5 MB; use a narrower selector")
        for line in text.splitlines():
            value = line.strip()
            if value and value not in seen:
                total_chars += len(value) + 1
                if total_chars > 20_000_000:
                    raise ValueError("Collected text exceeds 20 MB; narrow the selector or scroll limit")
                seen.add(value)
                lines.append(value)
        if index == max_scrolls:
            break
        state = host.evaluate("""(root, amount) => {
          const all = [document.scrollingElement,root,...root.querySelectorAll('*')].filter(Boolean);
          let moved=0, pending=0;
          for (const el of new Set(all)) {
            if (el.scrollHeight <= el.clientHeight+2) continue;
            if (el!==document.scrollingElement && el!==root) {
              const style=getComputedStyle(el);
              if (!['auto','scroll','overlay'].includes(style.overflowY)) continue;
            }
            const before=el.scrollTop;
            el.scrollTop=Math.min(el.scrollHeight,el.scrollTop+amount);
            if (el.scrollTop>before+1) moved++;
            if (el.scrollTop+el.clientHeight<el.scrollHeight-2) pending++;
          }
          return {moved,pending};
        }""",step_px)
        scrolls += 1
        pause(pause_seconds)
        # Two stable passes, allowing delayed infinite-scrolling DOM updates.
        if not state["moved"] and not state["pending"]:
            still += 1
            if still >= 2:
                break
        else:
            still = 0
    return "\n".join(lines), scrolls


def _native_window(title: str):
    from pywinauto import Desktop
    windows = Desktop(backend="uia").windows()
    if title:
        windows = [win for win in windows if title.casefold() in win.window_text().casefold()]
    else:
        windows = [win for win in windows if win.is_active()]
    if not windows:
        raise LookupError(f"Windows application window not found: {title or '(active window)'}")
    return windows[0]


def expand_desktop_controls(title: str = "", max_controls: int = 100,
                            pause: Callable[[float], None] | None = None) -> dict:
    """Enumerate UIA ComboBox / disclosure controls, expanding each in turn."""
    if not 1 <= max_controls <= 2000:
        raise ValueError("max_controls must be 1–2000")
    pause = pause or (lambda _: None)
    window = _native_window(title)
    controls = [item for item in window.descendants()
                if item.element_info.control_type in ("ComboBox", "Button", "TreeItem")]
    report = []
    for control in controls[:max_controls]:
        try:
            interface = control.iface_expand_collapse
            if interface is None:
                continue
            original = int(interface.CurrentExpandCollapseState)
            if original == 0:  # Collapsed; UIA ExpandCollapseState.Collapsed.
                interface.Expand()
                pause(0.1)
            entries = []
            if control.element_info.control_type == "ComboBox":
                entries = [e.window_text() for e in control.descendants()
                           if e.element_info.control_type in ("ListItem", "Text") and e.window_text()]
            report.append({"name": control.window_text(), "type": control.element_info.control_type,
                           "items": entries})
            # Only one native dropdown can stay visible; restore prior state.
            if original == 0:
                interface.Collapse()
        except Exception:
            continue
    return {"window": window.window_text(), "controls": report,
            "count": len(report), "note": "Native dropdowns inspected sequentially, without altering their selected values."}


def capture_desktop_scrolling_text(title: str = "", max_scrolls: int = 50,
                                   wheel_notches: int = 5, pause_seconds: float = 0.3,
                                   pause: Callable[[float], None] | None = None) -> tuple[str, int]:
    """Try complete UIA TextPattern; fallback to bounded Ctrl+A/C and scrolling.

    UIA is preferred because it can read offscreen text in compatible apps.
    Fallback requires the application to support Ctrl+A/C and wheel scrolling.
    The original clipboard is restored only by higher-level callers if desired.
    """
    if not 1 <= max_scrolls <= 10000 or not 1 <= wheel_notches <= 100:
        raise ValueError("Scroll limits outside supported ranges")
    pause = pause or (lambda _: None)
    window = _native_window(title)
    window.set_focus()
    # Try the text/document accessibility provider first.
    nodes = [window, *window.descendants()]
    candidates = []
    for node in nodes:
        try:
            pattern = node.iface_text
            if pattern is not None:
                value = pattern.DocumentRange.GetText(-1)
                if value and value.strip():
                    if len(value)>20_000_000:
                        raise ValueError("Windows UIA document text exceeds 20 MB")
                    candidates.append(value)
        except ValueError:
            raise
        except Exception:
            continue
    if candidates:
        # UIA may expose several document/text areas. A first match might only
        # contain a short title; retain the largest and other disjoint sections.
        candidates.sort(key=len, reverse=True)
        combined=[candidates[0]]
        for piece in candidates[1:]:
            if not any(piece in whole for whole in combined):
                if sum(map(len,combined))+len(piece)>20_000_000:
                    raise ValueError("Combined Windows UIA text exceeds 20 MB")
                combined.append(piece)
        return "\n".join(combined), 0
    import pyautogui as pg
    import pyperclip
    saved_clipboard = pyperclip.paste()
    samples = []
    seen = set()
    unchanged = 0
    index = 0
    try:
        pg.hotkey("ctrl", "home")
        for index in range(max_scrolls + 1):
            # Clear clipboard text first so a failed Ctrl+C cannot re-read
            # unrelated clipboard contents as if they came from this window.
            pyperclip.copy("")
            pg.hotkey("ctrl", "a")
            pg.hotkey("ctrl", "c")
            pause(0.15)
            chunk = pyperclip.paste()
            if chunk and chunk not in seen:
                seen.add(chunk)
                samples.append(chunk)
                unchanged = 0
            else:
                unchanged += 1
            if unchanged >= 3 or index == max_scrolls:
                break
            pg.scroll(-wheel_notches)
            pause(pause_seconds)
    finally:
        # Leave the clipboard untouched by a read-only text collection.
        # The caller separately overwrites it if copy_to_clipboard=True.
        pyperclip.copy(saved_clipboard)
    if not samples:
        raise RuntimeError("The application did not expose or copy any text. Try targeting a text/document control.")
    return max(samples,key=len) if len(samples)==1 else "\n".join(samples), index
