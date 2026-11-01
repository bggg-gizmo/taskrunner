"""Windows user-bound local credential vault using DPAPI (no cloud or plaintext fallback)."""
from __future__ import annotations
import ctypes
import os
import re
import sys
from ctypes import wintypes
from pathlib import Path
from .paths import data_root

NAME_PATTERN=re.compile(r'[A-Za-z_][A-Za-z0-9_-]{0,63}\Z')


class _DATA_BLOB(ctypes.Structure):
    _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data):
    buffer=(ctypes.c_ubyte*max(1,len(data)))(*data)
    return _DATA_BLOB(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte))),buffer


def _crypt(data: bytes, encrypt: bool) -> bytes:
    if sys.platform!='win32':
        raise OSError('Task Runner credential vault requires Windows DPAPI')
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    kernel.LocalFree.restype=ctypes.c_void_p
    input_blob,buffer=_blob(data)
    output=_DATA_BLOB()
    flags=0x01 # CRYPTPROTECT_UI_FORBIDDEN
    if encrypt:
        fn=crypt.CryptProtectData
        fn.argtypes=[ctypes.POINTER(_DATA_BLOB),ctypes.c_wchar_p,ctypes.c_void_p,
                     ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(_DATA_BLOB)]
        result=fn(ctypes.byref(input_blob),'TaskRunner local credential',None,None,None,flags,ctypes.byref(output))
    else:
        fn=crypt.CryptUnprotectData
        fn.argtypes=[ctypes.POINTER(_DATA_BLOB),ctypes.c_void_p,ctypes.c_void_p,
                     ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(_DATA_BLOB)]
        result=fn(ctypes.byref(input_blob),None,None,None,None,flags,ctypes.byref(output))
    if not result:
        raise OSError(ctypes.get_last_error(),'Windows DPAPI operation failed')
    try:
        return ctypes.string_at(output.pbData,output.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(output.pbData,ctypes.c_void_p))


class Vault:
    def __init__(self,directory=None,protect=None,unprotect=None):
        self.root=Path(directory) if directory is not None else data_root()/'vault'
        self.protect=protect or (lambda value:_crypt(value,True))
        self.unprotect=unprotect or (lambda value:_crypt(value,False))

    def _path(self,name):
        if not NAME_PATTERN.fullmatch(str(name)):
            raise ValueError('Vault names must be 1–64 letters/numbers/underscores/hyphens, starting with a letter/underscore')
        return self.root/(name+'.dpapi')

    def put(self,name,secret):
        """Overwrite a named secret with user-bound encrypted bytes only."""
        path=self._path(name)
        if not isinstance(secret,str) or not secret:
            raise ValueError('Cannot save an empty secret')
        encoded=self.protect(secret.encode('utf-8'))
        self.root.mkdir(parents=True,exist_ok=True)
        # DPAPI output is binary. Atomic replacement avoids partial secrets.
        import tempfile
        fd,staged=tempfile.mkstemp(prefix='.vault-',dir=self.root)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(encoded);stream.flush();os.fsync(stream.fileno())
            os.replace(staged,path)
        finally:
            Path(staged).unlink(missing_ok=True)

    def get(self,name):
        path=self._path(name)
        return self.unprotect(path.read_bytes()).decode('utf-8')

    def list_names(self):
        if not self.root.exists():return []
        return sorted(p.stem for p in self.root.glob('*.dpapi') if NAME_PATTERN.fullmatch(p.stem))

    def remove(self,name):
        self._path(name).unlink()
