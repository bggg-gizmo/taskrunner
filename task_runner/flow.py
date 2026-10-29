"""Validate and compile structured, nested workflow branches and repetitions.

Jumps are precomputed before any action executes, so malformed flows never run
partially. All indices refer to their zero-based positions in the saved steps.
"""
from __future__ import annotations
import re
from .actions import ACTIONS


def compile_flow(steps: list[dict]) -> dict[int, int]:
    stack: list[dict] = []
    links: dict[int, int] = {}
    for pos, step in enumerate(steps):
        if not isinstance(step,dict):
            raise ValueError(f"Step {pos + 1}: expected an action object")
        kind = step.get("type")
        if kind not in ACTIONS:
            raise ValueError(f"Unknown action at step {pos + 1}: {kind}")
        if kind in ("if_var", "repeat"):
            if kind == "repeat":
                count = int(step.get("params", {}).get("times", 0))
                if not 0 <= count <= 10000:
                    raise ValueError(f"Step {pos + 1}: repeat count must be 0–10000")
            stack.append({"kind": kind, "position": pos, "else": None})
        elif kind == "else":
            if not stack or stack[-1]["kind"] != "if_var" or stack[-1]["else"] is not None:
                raise ValueError(f"Step {pos + 1}: Else requires an unmatched If without an existing Else")
            stack[-1]["else"] = pos
        elif kind in ("endif", "end_repeat"):
            expected = "if_var" if kind == "endif" else "repeat"
            if not stack or stack[-1]["kind"] != expected:
                raise ValueError(f"Step {pos + 1}: {kind} does not match the open block")
            active = stack.pop()
            start = active["position"]
            links[start] = active["else"] if active["else"] is not None else pos
            links[pos] = start
            if active["else"] is not None:
                links[active["else"]] = pos
        elif kind in ("break_loop", "continue_loop"):
            loop = next((item for item in reversed(stack) if item["kind"] == "repeat"), None)
            if loop is None:
                raise ValueError(f"Step {pos + 1}: {kind} must appear inside a Repeat block")
            links[pos] = loop["position"]
    if stack:
        item = stack[-1]
        raise ValueError(f"Unclosed {item['kind']} at step {item['position'] + 1}")
    return links


def condition(variable: str, operator: str, desired: str) -> bool:
    checks = {
        "equals": lambda: variable == desired,
        "not equals": lambda: variable != desired,
        "contains": lambda: desired in variable,
        "not contains": lambda: desired not in variable,
        "empty": lambda: not variable,
        "not empty": lambda: bool(variable),
        "regex matches": lambda: re.search(desired, variable) is not None,
    }
    if operator not in checks:
        raise ValueError(f"Unknown variable comparison: {operator}")
    return checks[operator]()


def validate_workflow(steps: list[dict]) -> None:
    """Validate persisted action parameters and verification before scheduling."""
    if not isinstance(steps, list) or not steps:
        raise ValueError("At least one workflow action is required")
    compile_flow(steps)
    from .actions import VERIFY_KINDS
    verify_types={key for key,_ in VERIFY_KINDS}
    for number,step in enumerate(steps,1):
        if not isinstance(step,dict):
            raise ValueError(f"Step {number}: expected an action object")
        code=step["type"]
        params=step.get("params",{})
        if not isinstance(params,dict):
            raise ValueError(f"Step {number}: parameters must be an object")
        for field in ACTIONS[code].fields:
            value=params.get(field.key,field.default)
            if field.required and (value is None or not str(value).strip()):
                raise ValueError(f"Step {number}: {field.label} is required")
            if field.kind=="choice" and value not in field.options:
                raise ValueError(f"Step {number}: unsupported {field.label}: {value}")
            if field.kind=="int":
                try:int(value)
                except (ValueError,TypeError) as exc:
                    raise ValueError(f"Step {number}: {field.label} must be an integer") from exc
            if field.kind=="bool" and not isinstance(value,bool):
                raise ValueError(f"Step {number}: {field.label} must be true or false")
            if field.kind=="float":
                try:float(value)
                except (ValueError,TypeError) as exc:
                    raise ValueError(f"Step {number}: {field.label} must be a number") from exc
        verification=step.get("verify",{"kind":"none"})
        if not isinstance(verification,dict) or verification.get("kind","none") not in verify_types:
            raise ValueError(f"Step {number}: unknown verification method")
        if verification.get("kind","none") not in ("none","screen_changed") and not str(verification.get("target", "")).strip():
            raise ValueError(f"Step {number}: verification target is required")
        if verification.get("kind") == "screen_changed":
            from .visual_verification import parse_region
            try:parse_region(str(verification.get("target","")))
            except ValueError as exc:raise ValueError(f"Step {number}: {exc}") from exc
        for key in ("retry_count","retry_delay","delay_before","delay_after"):
            try:val=float(step.get(key,0))
            except (TypeError,ValueError) as exc:
                raise ValueError(f"Step {number}: {key} must be numeric") from exc
            limit=100 if key=="retry_count" else 3600
            if not 0<=val<=limit or (key=="retry_count" and not val.is_integer()):
                raise ValueError(f"Step {number}: {key} out of range")
        # Validate bounded browser/Windows collectors before executing any steps.
        bounded_int = {
            "browser_expand_all": {"max_controls": (1, 2000)},
            "desktop_expand_all": {"max_controls": (1, 2000)},
            "browser_scroll_text": {"max_scrolls": (1, 10000), "step_px": (1, 5000)},
            "desktop_scroll_text": {"max_scrolls": (1, 10000), "wheel_notches": (1, 100)},
        }
        bounded_float = {
            "browser_scroll_text": {"pause_seconds": (0, 60)},
            "desktop_scroll_text": {"pause_seconds": (0, 60)},
            "wait_window": {"timeout": (0, 3600)},
            "wait_file": {"timeout": (0, 3600)},
            "browser_wait_state": {"timeout": (0, 3600)},
        }
        defaults = {field.key:field.default for field in ACTIONS[code].fields}
        for key,(low,high) in bounded_int.get(code,{}).items():
            amount=int(params.get(key,defaults[key]))
            if not low<=amount<=high:
                raise ValueError(f"Step {number}: {key} must be {low}–{high}")
        for key,(low,high) in bounded_float.get(code,{}).items():
            amount=float(params.get(key,defaults[key]))
            if not low<=amount<=high:
                raise ValueError(f"Step {number}: {key} must be {low}–{high}")
        if code == "browser_select" and params.get("method", "label") == "index":
            try:
                if int(params.get("choice", "")) < 0:
                    raise ValueError("Option index must be non-negative")
            except (ValueError,TypeError) as exc:
                raise ValueError(f"Step {number}: option index must be a non-negative integer") from exc
        if code in ("launch", "open_path") and not 0 <= float(params.get("window_timeout", 30.0)) <= 3600:
            raise ValueError(f"Step {number}: window_timeout must be 0–3600 seconds")
        try:v_timeout=float(verification.get("timeout",10.0))
        except (TypeError,ValueError) as exc:
            raise ValueError(f"Step {number}: invalid verification timeout") from exc
        if not 0<=v_timeout<=3600:
            raise ValueError(f"Step {number}: verification timeout must be 0–3600 seconds")
