"""Validated, ambiguity-aware desktop target selection.

Separates ranking from Windows input so recordings can be regression tested on
Linux. A target is clicked only after its identity and location are resolved.
"""
from dataclasses import dataclass
from math import hypot


class AmbiguousTargetError(ValueError):
    pass


@dataclass(frozen=True)
class TargetCandidate:
    x: int
    y: int
    method: str
    confidence: float


def choose(candidates, expected=None, ambiguity_gap=.015, min_separation=24):
    """Pick the best candidate, requiring clear visual/semantic disambiguation.

    Nearby duplicate detections of the same element are treated as one match;
    far-apart alternatives of almost equal confidence are rejected.
    """
    values=sorted(candidates,key=lambda c:c.confidence,reverse=True)
    if not values:
        raise LookupError('Target cannot be located')
    best=values[0]
    others=[c for c in values[1:] if hypot(c.x-best.x,c.y-best.y)>=min_separation]
    if others and others[0].confidence >= best.confidence-ambiguity_gap:
        # A recorded window-relative point may disambiguate repeated buttons.
        if expected is not None:
            distances=sorted(((hypot(c.x-expected[0],c.y-expected[1]),c) for c in values),key=lambda a:a[0])
            if len(distances)==1 or distances[1][0]-distances[0][0]>=min_separation:
                return distances[0][1]
        raise AmbiguousTargetError('Multiple equally likely controls or images found. Teach a more specific target.')
    return best


def image_candidates(image_path, region='', confidence=.88, limit=12):
    """Find screenshot-template matches over the actual virtual desktop.

    Uses mss for virtual monitor origins and OpenCV for normalized matching.
    A solid-color template is rejected because it produces false positives.
    """
    from pathlib import Path
    import cv2
    import numpy as np
    import mss
    from .visual_verification import parse_region
    template=cv2.imread(str(Path(image_path).expanduser()),cv2.IMREAD_COLOR)
    if template is None:
        raise FileNotFoundError(f'Cannot read reference image: {image_path}')
    h,w=template.shape[:2]
    if h<6 or w<6 or float(template.std())<1.0:
        raise ValueError('Reference image is too small or uniform for accurate targeting')
    with mss.mss() as capture:
        base=dict(capture.monitors[0])
        if region:
            base=parse_region(region)
        pixels=np.array(capture.grab(base))
    screen=cv2.cvtColor(pixels,cv2.COLOR_BGRA2BGR)
    if h>screen.shape[0] or w>screen.shape[1]:
        return []
    matches=cv2.matchTemplate(screen,template,cv2.TM_CCOEFF_NORMED)
    # Nonmaximum suppression on score map; suppress adjacent detections.
    candidates=[]
    suppression=max(6,min(w,h)//2)
    for _ in range(max(1,min(limit,32))):
        _,score,_,point=cv2.minMaxLoc(matches)
        if score<float(confidence):break
        cx=base['left']+point[0]+w//2
        cy=base['top']+point[1]+h//2
        candidates.append(TargetCandidate(int(cx),int(cy),'image',float(score)))
        x0=max(0,point[0]-suppression)
        y0=max(0,point[1]-suppression)
        x1=min(matches.shape[1],point[0]+suppression+1)
        y1=min(matches.shape[0],point[1]+suppression+1)
        matches[y0:y1,x0:x1]=-1
    return candidates


def resolve_adaptive(x,y,window_title='',window_rx=0.,window_ry=0.,control_name='',automation_id='',
                     reference_image='',confidence=.88,allow_relative_fallback=True,strict_target=False,
                     image_search=None,window_search=None):
    """Identity -> reference pixels -> window-relative -> absolute (legacy).

    Target-confidence values represent reliability of the *method* for
    semantic controls; visual scores are actual template correlation.
    """
    image_search=image_search or image_candidates
    expected=(int(x),int(y))
    bounds=None
    if window_title:
        if window_search is None:
            from .winmouse import window_candidates
            window_search=window_candidates
        win=window_search(window_title,expected)
        if win is None:
            raise LookupError(f'Recorded target window is not open: {window_title}')
        bounds=win['bounds']
        expected=(round(bounds[0]+float(window_rx)*bounds[2]),
                  round(bounds[1]+float(window_ry)*bounds[3]))
        controls=win.get('controls',[])
        for key,value,score in (('automation_id',automation_id,.99),('control_name',control_name,.94)):
            if not value:continue
            candidates=[TargetCandidate(int(c['x']),int(c['y']),key,score)
                        for c in controls if c.get(key)==value and
                        (not control_name or key!='automation_id' or c.get('control_name')==control_name)]
            if candidates:
                return choose(candidates,expected)
    if reference_image:
        try:
            found=image_search(reference_image,'',float(confidence))
        except (FileNotFoundError,ValueError):
            if strict_target:raise
            found=[]
        if bounds:
            left,top,width,height=bounds
            found=[c for c in found if left<=c.x<left+width and top<=c.y<top+height]
        if found:return choose(found,expected)
        if strict_target:
            raise LookupError(f'Reference image not found: {reference_image}')
    if strict_target and (automation_id or control_name or reference_image):
        raise LookupError('Precise target not found; refusing an unverified coordinate click')
    if bounds and allow_relative_fallback:
        return TargetCandidate(*expected,'window-relative',.7)
    if window_title and not allow_relative_fallback:
        raise LookupError('Target not found; window-relative fallback disabled')
    if strict_target:
        raise LookupError('Strict target requires a reference image or accessible control')
    return TargetCandidate(int(x),int(y),'absolute',.35)
