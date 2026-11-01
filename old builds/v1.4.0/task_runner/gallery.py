"""Local capture gallery indexing, duplicate analysis, and lossless archive export."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

ALLOWED={'.png','.jpg','.jpeg','.webp','.bmp','.gif','.txt','.json','.log','.html','.csv'}
MAX_GALLERY_FILES=10000
MAX_FILE_BYTES=512*1024*1024
MAX_EXPORT_BYTES=2*1024*1024*1024


def gallery_entries(folder, include_subfolders=True):
    root=Path(folder).expanduser().resolve(strict=True)
    if not root.is_dir():raise NotADirectoryError(root)
    files=root.rglob('*') if include_subfolders else root.iterdir()
    out=[]
    for file in files:
        if len(out)>=MAX_GALLERY_FILES:break
        if file.is_symlink() or not file.is_file() or file.suffix.lower() not in ALLOWED:
            continue
        stat=file.stat()
        if stat.st_size>MAX_FILE_BYTES:continue
        out.append({'path':str(file),'relative':file.relative_to(root).as_posix(),
                    'name':file.name,'bytes':stat.st_size,'modified_ns':stat.st_mtime_ns,
                    'kind':'image' if file.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.bmp','.gif'} else 'text'})
    out.sort(key=lambda x:(-x['modified_ns'],x['relative']))
    return out


def _hash_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def duplicates(entries):
    """Return groups of identical files; equal filenames alone are not duplicates."""
    sizes={}
    for item in entries:
        sizes.setdefault(item['bytes'],[]).append(item)
    groups={}
    for equal_size in sizes.values():
        if len(equal_size)<2:continue
        for item in equal_size:
            digest=_hash_file(item['path'])
            groups.setdefault(digest,[]).append(item['relative'])
    return {digest:names for digest,names in groups.items() if len(names)>1}


def export_gallery(folder,destination,entries=None):
    """Create a deterministic manifest and a ZIP of selected local captures.

    No symlinks, traversals, or unrelated source files are packed. Caller
    chooses the selection and explicitly confirms when data may be sensitive.
    """
    root=Path(folder).expanduser().resolve(strict=True)
    destination=Path(destination).expanduser().resolve()
    selected=list(entries if entries is not None else gallery_entries(root))
    total=0
    manifest=[]
    for item in selected:
        path=Path(item['path'])
        if path.is_symlink() or not path.is_file():raise ValueError('Gallery entry is not a regular file')
        full=path.resolve(strict=True)
        if not full.is_relative_to(root):raise ValueError(f'Capture is outside the selected directory: {full}')
        if full==destination:raise ValueError('Cannot include archive in itself')
        stat=full.stat()
        total+=stat.st_size
        if stat.st_size>MAX_FILE_BYTES or total>MAX_EXPORT_BYTES:
            raise ValueError('Capture archive exceeds size safety limits')
        manifest.append({'path':full.relative_to(root).as_posix(),'size':stat.st_size,
                         'sha256':_hash_file(full)})
    destination.parent.mkdir(parents=True,exist_ok=True)
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(dir=destination.parent,prefix='.gallery-',suffix='.zip',delete=False) as stage:
        staged=Path(stage.name)
    try:
        with ZipFile(staged,'w',ZIP_DEFLATED,compresslevel=6) as archive:
            archive.writestr('manifest.json',json.dumps({'format':'TaskRunnerCaptureGallery',
                'version':1,'files':manifest},indent=2,ensure_ascii=False)+'\n')
            for item in manifest:
                archive.write(root/item['path'],arcname='captures/'+item['path'])
        staged.replace(destination)
        return destination
    finally:staged.unlink(missing_ok=True)
