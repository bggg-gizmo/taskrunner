"""Reliable, polling-based filesystem event predicates for local scheduling.

The Windows heartbeat runs at one-minute granularity; file events are not
claimed with an unrealistic sub-second guarantee when the GUI is closed.
"""
from __future__ import annotations
from pathlib import Path
import json

EVENTS=('created','modified','removed','any')


def validate(config):
    if not isinstance(config,dict) or not str(config.get('path','')).strip():
        raise ValueError('File-trigger schedules require an absolute monitored path')
    location=Path(config['path']).expanduser()
    if not location.is_absolute():
        raise ValueError('File event watch path must be absolute')
    if config.get('event','modified') not in EVENTS:
        raise ValueError(f'File event must be one of {", ".join(EVENTS)}')


def fingerprint(path):
    location=Path(path).expanduser()
    try:
        info=location.stat()
        return json.dumps({'exists':True,'size':info.st_size,'modified_ns':info.st_mtime_ns,
                           'file_id':info.st_ino,'is_dir':location.is_dir()},sort_keys=True)
    except FileNotFoundError:
        return json.dumps({'exists':False},sort_keys=True)


def event_between(previous,current):
    old=json.loads(previous);new=json.loads(current)
    if not old.get('exists') and new.get('exists'):return 'created'
    if old.get('exists') and not new.get('exists'):return 'removed'
    if old!=new:return 'modified'
    return None
