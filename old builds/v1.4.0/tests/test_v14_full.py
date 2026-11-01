"""Broader v1.4 integration and security tests using real SQLite / filesystem."""
import hashlib
import json
import threading
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image
from task_runner.actions import default_step
from task_runner.gallery import gallery_entries,duplicates,export_gallery
from task_runner.ocr import read_region,stable_text_condition
from task_runner.packages import export_package,import_package
from task_runner.recovery import validate_resume
from task_runner.store import Store
from task_runner.executor import WorkflowEngine


def job(db,name,steps):
    return db.save_job({'name':name,'actions':steps,'schedule_kind':'manual', 'enabled':True})


def test_portable_package_with_image_and_module_roundtrip(tmp_path):
    source=Store(tmp_path/'source.sqlite3')
    image=tmp_path/'reference.png'
    Image.new('RGB',(60,60),'purple').save(image)
    reusable=default_step('set_var')
    reusable['params']={'name':'greeting','value':'hello'}
    module=job(source,'Reusable',[reusable])
    runmodule=default_step('run_module');runmodule['params']['task_id']=module
    click=default_step('click');click['params']['reference_image']=str(image)
    root=job(source,'Main',[runmodule,click])
    bundle=tmp_path/'workflow.trpkg'
    export_package(source,root,bundle)
    assert bundle.exists() and bundle.stat().st_size>100
    with ZipFile(bundle) as package:
        manifest=json.loads(package.read('manifest.json'))
        assert len(manifest['jobs'])==2
        assert len(manifest['assets'])==1
        assert manifest['includes_scripts'] is False
    dest=Store(tmp_path/'target.sqlite3')
    new=import_package(dest,bundle,asset_root=tmp_path/'copied')
    main=dest.get_job(new)
    assert main['enabled']==0
    other=dest.get_job(main['actions'][0]['params']['task_id'])
    assert other['enabled']==0
    assert other['actions'][0]['type']=='set_var'
    asset=Path(main['actions'][1]['params']['reference_image'])
    assert asset.is_file() and asset.read_bytes()==image.read_bytes()


def test_import_rejects_tampered_asset(tmp_path):
    db=Store(tmp_path/'source.sqlite3')
    picture=tmp_path/'reference.png';Image.new('RGB',(60,60),'pink').save(picture)
    step=default_step('click');step['params']['reference_image']=str(picture)
    task=job(db,'Task',[step]);package=tmp_path/'source.trpkg'
    export_package(db,task,package)
    import zipfile
    hacked=tmp_path/'hacked.trpkg'
    with zipfile.ZipFile(package) as original,zipfile.ZipFile(hacked,'w') as altered:
        for filename in original.namelist():
            data=original.read(filename)
            if filename.startswith('assets/'):data=b'CORRUPTED'+data
            altered.writestr(filename,data)
    target=Store(tmp_path/'target.sqlite3')
    with pytest.raises(ValueError,match='digest mismatch|Asset digest mismatch'):
        import_package(target,hacked,asset_root=tmp_path/'copy')
    assert target.all_jobs()==[]


def test_gallery_deduplicates_by_contents_and_exports_verified_archive(tmp_path):
    folder=tmp_path/'gallery';folder.mkdir()
    (folder/'alpha.txt').write_text('same')
    (folder/'beta.txt').write_text('same')
    (folder/'diff.txt').write_text('different')
    entries=gallery_entries(folder)
    assert len(entries)==3
    dups=duplicates(entries)
    assert len(dups)==1
    assert sorted(next(iter(dups.values())))==['alpha.txt','beta.txt']
    zipfile=export_gallery(folder,tmp_path/'captures.zip',entries)
    with ZipFile(zipfile) as package:
        manifest=json.loads(package.read('manifest.json'))
        for item in manifest['files']:
            assert hashlib.sha256(package.read('captures/'+item['path'])).hexdigest()==item['sha256']


def test_gallery_rejects_outside_path_and_symlink(tmp_path):
    folder=tmp_path/'gallery';folder.mkdir()
    outside=tmp_path/'secret.txt';outside.write_text('private')
    fake={'path':str(outside),'relative':'../secret.txt','bytes':7}
    with pytest.raises(ValueError,match='outside'):
        export_gallery(folder,tmp_path/'output.zip',[fake])


def test_ocr_reads_offline_engine_without_network_calls():
    image=Image.new('RGB',(120,40),'white')
    def local_engine(frame):
        assert frame.shape==(40,120,3)
        return [([0,0],'TASK COMPLETE',.99),([0,0],'noise',.10)],.3
    assert read_region(image=image,confidence=.5,engine=local_engine)=='TASK COMPLETE'


def test_ocr_stability_requires_consecutive_agreement():
    observed=iter(['loading','DONE','DONE'])
    result=stable_text_condition(lambda:next(observed),'DONE',required=2,timeout=2,poll=.1)
    assert result=='DONE'
    with pytest.raises(ValueError):stable_text_condition(lambda:'DONE','DONE',required=31)


def test_resume_from_verified_checkpoint_never_reruns_completed_step(tmp_path):
    db=Store(tmp_path/'tasks.sqlite3')
    dest=tmp_path/'one.txt'
    first=default_step('write_file');first['params']['path']=str(dest)
    first['params']['text']='first'
    fail=default_step('read_file');fail['params']['path']=str(tmp_path/'missing.txt')
    last=default_step('write_file');last['params']['path']=str(tmp_path/'last.txt')
    last['params']['text']='last'
    task=job(db,'Task',[first,fail,last])
    execution=db.claim(task,force=True)
    assert WorkflowEngine(db).execute(task,execution)=='failed'
    assert db.checkpoint_for(execution)['completed']==1
    missing=tmp_path/'missing.txt';missing.write_text('available')
    job_id,resumed=db.claim_resume(execution)
    assert job_id==task
    assert db.execution_by_id(resumed)['resume_index']==1
    assert WorkflowEngine(db).execute(task,resumed)=='success'
    assert (tmp_path/'last.txt').read_text()=='last'
    assert db.checkpoint_for(resumed)['completed']==3


def test_resume_refuses_changed_workflow_and_loop(tmp_path):
    store=Store(tmp_path/'store.sqlite3')
    first=default_step('write_file');first['params']['path']=str(tmp_path/'ready')
    first['params']['text']='ok'
    second=default_step('read_file');second['params']['path']=str(tmp_path/'missing')
    task=job(store,'A',[first,second])
    run=store.claim(task,force=True)
    assert WorkflowEngine(store).execute(task,run)=='failed'
    new_steps=store.get_job(task)
    new_steps['actions'][0]['params']['text']='changed'
    store.save_job(new_steps)
    with pytest.raises(ValueError,match='Task changed'):
        store.claim_resume(run)
    with pytest.raises(ValueError,match='linear'):
        validate_resume([default_step('repeat'),default_step('wait'),default_step('end_repeat')],1)


def test_full_engine_debug_step_and_failure_recovery(tmp_path):
    db=Store(tmp_path/'db.sqlite3')
    first=default_step('write_file');first['params']['path']=str(tmp_path/'first')
    first['params']['text']='hello'
    second=default_step('read_file');second['params']['path']=str(tmp_path/'missing')
    third=default_step('write_file');third['params']['path']=str(tmp_path/'third')
    third['params']['text']='complete'
    target=job(db,'Interactive debugger',[first,second,third])
    run=db.claim(target,force=True)
    db.debug_enable(run,paused=True,break_on_failure=True,snapshots=False)
    statuses=[]
    thread=threading.Thread(target=lambda:statuses.append(WorkflowEngine(db).execute(target,run)))
    thread.start()
    def wait_for(fn,seconds=5):
        import time
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if fn():return
            time.sleep(.02)
        raise AssertionError('State not reached')
    wait_for(lambda:db.debug_status(run)['state']=='paused')
    assert not (tmp_path/'first').exists()
    db.debug_command(run,'step')
    wait_for(lambda:(tmp_path/'first').exists() and db.debug_status(run)['step_index']==2
                   and db.debug_status(run)['state']=='paused')
    assert (tmp_path/'first').read_text()=='hello'
    db.debug_command(run,'run')
    wait_for(lambda:db.debug_status(run)['state']=='failed_paused')
    assert not (tmp_path/'third').exists()
    (tmp_path/'missing').write_text('repaired')
    db.debug_command(run,'retry')
    wait_for(lambda:db.debug_status(run)['state']=='paused' and db.debug_status(run)['step_index']==3)
    assert not (tmp_path/'third').exists()
    db.debug_command(run,'run')
    thread.join(5)
    assert not thread.is_alive()
    assert statuses==['success']
    assert (tmp_path/'third').read_text()=='complete'
    assert db.checkpoint_for(run)['completed']==3
