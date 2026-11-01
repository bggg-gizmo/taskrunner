"""Explicit, opt-in checkpoint continuation with conservative safety checks."""
import hashlib
import json
import re

UNSAFE_FLOW={'if_var','else','endif','repeat','end_repeat','break_loop','continue_loop','run_module'}
VOLATILE_STATE={'browser_open','browser_click','browser_fill','browser_press','browser_wait',
                'browser_text','browser_html','browser_download','browser_screenshot','browser_close',
                'browser_expand_all','browser_scroll_text','capture_live_start','capture_live_stop',
                'set_var','clipboard_read','read_file','load_secret','wait_content','wait_ocr','soup_select'}


def plan_hash(steps):
    content=json.dumps(steps,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(content).hexdigest()


def validate_resume(steps,completed):
    if not 0<int(completed)<len(steps):
        raise ValueError('Checkpoint has no remaining steps')
    for index,step in enumerate(steps):
        if step['type'] in UNSAFE_FLOW:
            raise ValueError('Checkpoint continuation is restricted to linear workflows')
        if index<int(completed) and step['type'] in VOLATILE_STATE:
            raise ValueError('Earlier actions depend on volatile browser, capture, or variable state; a fresh run is required')
    for step in steps[int(completed):]:
        if '${' in json.dumps(step['params']):
            raise ValueError('Later steps need variables that would not be restored; a fresh run is required')
    return True
