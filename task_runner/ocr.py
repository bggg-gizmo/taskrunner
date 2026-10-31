"""Offline OCR on an exact desktop region, with confidence filtering.

RapidOCR includes local ONNX models inside the dependency distribution; this
module has no network calls, cloud inference, or remote service fallback.
"""
from __future__ import annotations
from functools import lru_cache


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError('Offline OCR requires rapidocr-onnxruntime. Run CHECK_DEPENDENCIES.cmd.') from exc
    return RapidOCR()


def read_region(region='', confidence=.45, engine=None, image=None):
    import numpy as np
    if image is None:
        from .visual_verification import take_sample
        image=take_sample(region)
    if image is None:
        raise ValueError('No screenshot available to recognize')
    frame=np.asarray(image.convert('RGB'))
    result,_=(engine or _engine())(frame)
    pieces=[]
    for line in (result or []):
        if len(line)<3:continue
        value=str(line[1])
        probability=float(line[2])
        if probability>=float(confidence) and value.strip():
            pieces.append(value)
    return '\n'.join(pieces)


def stable_text_condition(read,expected,condition='contains',required=2,case_sensitive=False,
                          abort=None,sleep=None,timeout=90,poll=.5):
    """Wait for a textual condition to remain true across N successive frames."""
    import time
    if condition not in ('contains','absent','changed'):
        raise ValueError('Unsupported OCR condition')
    if not 1<=int(required)<=30:raise ValueError('OCR stability frames must be 1–30')
    if not 0.1<=float(poll)<=60 or not 0.1<=float(timeout)<=86400:
        raise ValueError('Invalid OCR timeout or polling interval')
    clock=time.monotonic
    deadline=clock()+float(timeout)
    first=read() if condition=='changed' else None
    consecutive=0
    last=''
    while True:
        if abort:abort()
        current=read()
        a=current if case_sensitive else current.casefold()
        b=str(expected) if case_sensitive else str(expected).casefold()
        matched={'contains':lambda:b in a,'absent':lambda:b not in a,
                 'changed':lambda:current!=first}[condition]()
        if matched and current==last:consecutive+=1
        elif matched:consecutive=1
        else:consecutive=0
        last=current
        if consecutive>=int(required):return current
        if clock()>=deadline:raise TimeoutError('OCR text condition not stable before timeout')
        (sleep or time.sleep)(min(float(poll),max(.01,deadline-clock())))
