"""Regression checks for Windows Python 3.13 OCR and the actual build path."""
from pathlib import Path
from types import SimpleNamespace
import sys

from PIL import Image
from task_runner.ocr import read_region, _engine
from scripts.shared_dependencies import load_requirements

ROOT=Path(__file__).resolve().parents[1]


def test_rapidocr3_result_and_confidence_threshold():
    def engine(frame):
        assert frame.shape == (42, 220, 3)
        return SimpleNamespace(txts=['TASK COMPLETE','noise','NEXT'],
                               scores=[.99,.11,.8])
    image=Image.new('RGB',(220,42),'white')
    assert read_region(image=image,engine=engine,confidence=.5)=='TASK COMPLETE\nNEXT'


def test_no_text_result_is_empty():
    image=Image.new('RGB',(120,60),'white')
    assert read_region(image=image,engine=lambda _:SimpleNamespace(txts=None,scores=None))==''
    assert read_region(image=image,engine=lambda _:None)==''


def test_original_injected_ocr_adapter_remains_supported():
    image=Image.new('RGB',(120,60),'white')
    result=[('polygon','BACKWARD COMPATIBLE',.95)],.1
    assert read_region(image=image,engine=lambda _:result)=='BACKWARD COMPATIBLE'


def test_backend_import_and_initialization(monkeypatch):
    class Stub:
        def __call__(self,frame):
            return SimpleNamespace(txts=['OK'],scores=[1.0])
    monkeypatch.setitem(sys.modules,'rapidocr',SimpleNamespace(RapidOCR=Stub))
    monkeypatch.setitem(sys.modules,'onnxruntime',SimpleNamespace())
    _engine.cache_clear()
    try:
        assert read_region(image=Image.new('RGB',(40,20),'white'))=='OK'
    finally:
        _engine.cache_clear()


def test_full_build_uses_supported_rapidocr_runtime():
    requirements=load_requirements(ROOT/'requirements-build.txt')
    names={req.name.lower().replace('_','-'):req for req in requirements}
    assert 'rapidocr-onnxruntime' not in names
    assert 'rapidocr' in names
    assert 'onnxruntime' in names
    assert names['rapidocr'].specifier.contains('3.10.0')
    assert names['onnxruntime'].specifier.contains('1.31.1')
    script=(ROOT/'BUILD_WINDOWS.cmd').read_text(encoding='utf-8')
    assert '--collect-all rapidocr ' in script
    assert '--collect-all onnxruntime ' in script
    assert 'rapidocr_onnxruntime' not in script
    diagnostics=(ROOT/'task_runner/diagnostics.py').read_text(encoding='utf-8')
    assert 'read_region(image=Image.new' in diagnostics
