"""Windows user-bound DPAPI credentials, compatible with SecureString files."""
import ctypes
import os
from ctypes import wintypes
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]


def transform(data, protect):
    if os.name != 'nt':
        raise RuntimeError('DPAPI requires Windows')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    dll = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = dll.CryptProtectData if protect else dll.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError('Unable to open/save Windows credential')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def read_token(path):
    return transform(bytes.fromhex(Path(path).read_text(encoding='utf-8-sig').strip()), False).decode('utf-16-le').rstrip('\0').strip()


def save_token(path, token):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Credential ciphertext only; use exclusive file creation to avoid silent rotation.
    with path.open('x', encoding='ascii') as f:
        f.write(transform(token.encode('utf-16-le'), True).hex())
        f.flush()
        os.fsync(f.fileno())
