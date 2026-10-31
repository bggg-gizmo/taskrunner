"""Local OCR on an exact desktop region, including confidence filtering.

Uses maintained RapidOCR 3.x and ONNX Runtime with models bundled locally.
No cloud inference, model downloads, or remote service fallback.
The result normalizer preserves support for legacy injected OCR callbacks.
"""
from __future__ import annotations
from functools import lru_cache


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError('Offline OCR requires rapidocr and onnxruntime. Run CHECK_DEPENDENCIES.cmd.') from exc
    try:
        import onnxruntime  # noqa: F401 - fail early if the ONNX inference engine is absent
    except ImportError as exc:
        raise RuntimeError('Offline OCR requires onnxruntime. Run CHECK_DEPENDENCIES.cmd.') from exc
    return RapidOCR()


def _lines_from_result(result):
    """Normalize RapidOCR 3.x (`txts`/`scores`) or older tuple results.

    Legacy tuple-shaped return values occur in injected adapters and old
    dependencies, but the production engine is always the maintained RapidOCR.
    """
    if result is None:
        return ()
    if hasattr(result, 'txts') and hasattr(result, 'scores'):
        texts=result.txts
        scores=result.scores
        if texts is None or scores is None:
            return ()
        return zip(texts, scores)
    if isinstance(result, tuple) and len(result)==2:
        result=result[0]
    return ((line[1],line[2]) for line in (result or ()) if len(line)>=3)


def read_region(region='', confidence=.45, engine=None, image=None):
    import numpy as np
    if image is None:
        from .visual_verification import take_sample
        image=take_sample(region)
    if image is None:
        raise ValueError('No screenshot available to recognize')
    frame=np.asarray(image.convert('RGB'))
    output=(engine if engine is not None else _engine())(frame)
    pieces=[]
    for value, probability in _lines_from_result(output):
        if value is None or probability is None:
            continue
        if float(probability)>=float(confidence) and str(value).strip():
            pieces.append(str(value))
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
