"""Portable, checksummed Task Runner workflows, images, and reusable modules.

Untrusted packages are never executed automatically. Import creates disabled
jobs, verifies all asset hashes before saving anything, and checks traversals,
symlinks, duplicates, and expansion limits.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
from .flow import validate_workflow
from .paths import data_root

FORMAT='TaskRunnerPortableWorkflow'
MAX_FILES=500
MAX_BYTES=128*1024*1024
IMAGE_KEYS={'image','reference_image'}
SCRIPT_SUFFIXES={'.py','.ps1','.cmd','.bat'}


def _digest(data):return hashlib.sha256(data).hexdigest()


def _valid_rel(path):
    from pathlib import PurePosixPath
    target=PurePosixPath(path)
    return bool(path and not target.is_absolute() and '..' not in target.parts and
                '\\' not in path and ':' not in path and all(part not in ('','.','..') for part in target.parts))


def collect_jobs(store,root_id):
    collected={}
    def visit(job_id,chain):
        if job_id in chain:
            raise ValueError(f'Recursive reusable module: {chain+(job_id,)}')
        if job_id in collected:return
        if len(chain)>8 or len(collected)>=100:raise ValueError('Too many reusable modules')
        job=store.get_job(job_id)
        if not job:raise LookupError(f'Module task #{job_id} not found')
        validate_workflow(job['actions'])
        for step in job['actions']:
            if step['type']=='run_module':visit(int(step['params']['task_id']),chain+(job_id,))
        collected[job_id]={k:copy.deepcopy(job[k]) for k in
                           ('name','description','actions','schedule','schedule_kind')}
    visit(int(root_id),())
    return collected


def export_package(store,job_id,destination,include_scripts=False):
    jobs=collect_jobs(store,job_id)
    assets={}
    missing=[]
    def add_file(path):
        location=Path(path).expanduser()
        if not location.is_file() or location.is_symlink():
            missing.append(str(path));return None
        size=location.stat().st_size
        if size>MAX_BYTES:raise ValueError('Referenced asset exceeds package size limit')
        content=location.read_bytes()
        digest=_digest(content)
        suffix=location.suffix.lower()
        remote=f'assets/{digest}{suffix}'
        assets[remote]=content
        return remote
    for task in jobs.values():
        for step in task['actions']:
            for key in IMAGE_KEYS:
                if step['params'].get(key):
                    path=add_file(step['params'][key])
                    if path:step['params'][key]='package://'+path
            if step.get('verify',{}).get('kind')=='image_visible' and step['verify'].get('target'):
                path=add_file(step['verify']['target'])
                if path:step['verify']['target']='package://'+path
            if include_scripts and step['type']=='launch':
                executable=str(step['params'].get('path',''))
                if Path(executable).suffix.lower() in SCRIPT_SUFFIXES:
                    path=add_file(executable)
                    if path:step['params']['path']='package://'+path
    if missing:
        raise FileNotFoundError('Referenced assets are unavailable: '+', '.join(sorted(set(missing))))
    if len(assets)>MAX_FILES or sum(map(len,assets.values()))>MAX_BYTES:
        raise ValueError('Portable asset limit exceeded')
    manifest={'format':FORMAT,'version':1,'root_id':int(job_id),
              'jobs':{str(k):v for k,v in jobs.items()},
              'assets':{path:{'sha256':_digest(content),'bytes':len(content)}
                        for path,content in sorted(assets.items())},
              'includes_scripts':bool(include_scripts)}
    target=Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True,exist_ok=True)
    import tempfile
    fd,staged=tempfile.mkstemp(prefix='.workflow-',suffix='.trpkg',dir=target.parent)
    os.close(fd)
    try:
        with ZipFile(staged,'w',ZIP_DEFLATED,compresslevel=6) as bundle:
            bundle.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
            for path,content in sorted(assets.items()):bundle.writestr(path,content)
        os.replace(staged,target)
    finally:Path(staged).unlink(missing_ok=True)
    return target


def import_package(store,source,asset_root=None,path_remap=None):
    """Verify everything first, then save disabled module jobs and root task."""
    source=Path(source).expanduser().resolve(strict=True)
    location=Path(asset_root or data_root()/'workflow-assets').expanduser().resolve()
    remap=path_remap or {}
    with ZipFile(source) as bundle:
        files=bundle.infolist()
        if len(files)>MAX_FILES+1:raise ValueError('Too many package members')
        names=[x.filename for x in files]
        if len(names)!=len(set(names)) or 'manifest.json' not in names:
            raise ValueError('Duplicate names or missing manifest')
        if any(not _valid_rel(p) for p in names):
            raise ValueError('Unsafe archive path')
        for info in files:
            mode=(info.external_attr>>16)&0o170000
            if mode==0o120000:raise ValueError('Symlinks are forbidden in portable workflows')
        if sum(x.file_size for x in files)>MAX_BYTES:
            raise ValueError('Expanded workflow package is too large')
        if bundle.getinfo('manifest.json').file_size > 2*1024*1024:
            raise ValueError('Portable manifest is unreasonably large')
        manifest=json.loads(bundle.read('manifest.json'))
        if manifest.get('format')!=FORMAT or manifest.get('version')!=1:
            raise ValueError('Not a supported Task Runner portable workflow package')
        jobs=manifest['jobs']
        root=str(manifest['root_id'])
        if root not in jobs or not isinstance(jobs,dict) or len(jobs)>100:
            raise ValueError('Missing root job or too many modules')
        metadata=manifest.get('assets',{})
        if set(metadata)!=set(names)-{'manifest.json'}:
            raise ValueError('Asset list does not match archived files')
        bytes_by_path={}
        for path,record in metadata.items():
            if not path.startswith('assets/') or not _valid_rel(path):raise ValueError('Unsafe asset filename')
            content=bundle.read(path)
            if len(content)!=record['bytes'] or _digest(content)!=record['sha256']:
                raise ValueError('Asset digest mismatch: '+path)
            bytes_by_path[path]=content
        # Validate actions and module graph before modifying the task database.
        seen=set();ordered=[]
        def visit(key,stack):
            if key in stack:raise ValueError('Recursive module in package')
            if key in seen:return
            if key not in jobs:raise LookupError('Referenced module missing: '+key)
            doc=jobs[key]
            validate_workflow(doc['actions'])
            for step in doc['actions']:
                if step['type']=='run_module':visit(str(step['params']['task_id']),stack+(key,))
            seen.add(key);ordered.append(key)
        visit(root,())
        if set(jobs)!=seen:
            raise ValueError('Package contains unreferenced jobs')
        # Stage assets outside the active vault/jobs. Identical digest-based
        # filenames can be safely reused across several imported packages.
        location.mkdir(parents=True,exist_ok=True)
        for path,data in bytes_by_path.items():
            target=location/Path(path).name
            if target.exists() and _digest(target.read_bytes())!=_digest(data):
                raise ValueError('Existing asset hash differs: '+str(target))
            if not target.exists():
                import tempfile
                fd,staged=tempfile.mkstemp(dir=location,prefix='.asset-')
                try:
                    with os.fdopen(fd,'wb') as stream:stream.write(data)
                    os.replace(staged,target)
                finally:Path(staged).unlink(missing_ok=True)
        mapping={}
        for key in ordered:
            task=copy.deepcopy(jobs[key])
            for step in task['actions']:
                for param in step.get('params',{}):
                    value=step['params'][param]
                    if isinstance(value,str) and value.startswith('package://'):
                        path=value.removeprefix('package://')
                        if path not in bytes_by_path:raise ValueError('Asset reference missing: '+path)
                        step['params'][param]=str(location/Path(path).name)
                    elif isinstance(value,str) and param in ('path','source','destination','cwd'):
                        for original,updated in remap.items():
                            if value.startswith(original):
                                step['params'][param]=updated+value[len(original):]
                                break
                verify=step.get('verify',{})
                if str(verify.get('target','')).startswith('package://'):
                    path=verify['target'].removeprefix('package://')
                    if path not in bytes_by_path:raise ValueError('Missing verification reference')
                    verify['target']=str(location/Path(path).name)
                if step['type']=='run_module':
                    step['params']['task_id']=mapping[str(step['params']['task_id'])]
            task['name']=str(task['name'])+' (imported)'
            task['enabled']=False
            task['schedule_kind']='manual'
            task['schedule']={}
            mapping[key]=store.save_job(task)
        return mapping[root]
