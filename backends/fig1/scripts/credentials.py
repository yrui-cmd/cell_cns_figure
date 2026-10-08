"""Windows user-bound DPAPI credentials, compatible with SecureString files."""
import ctypes
import os
import re
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


class CredentialError(RuntimeError):
    pass


def read_token(path):
    path = Path(path)
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError()
        raw = path.read_text(encoding='utf-8-sig').strip()
        if raw.startswith('API_Key'):
            match = re.fullmatch(r'API_Key\s*=\s*"([^"\s]+)"', raw)
            if not match:
                raise ValueError()
            token = match.group(1)
        else:
            token = transform(bytes.fromhex(raw), False).decode('utf-16-le').rstrip('\0').strip()
        if not re.fullmatch(r'img_live_[A-Za-z0-9_.-]+', token):
            raise ValueError()
        return token
    except Exception:
        raise CredentialError('已有 API Key 配置无法读取或格式不受支持，请检查该配置；不会自动更换账户') from None


def shared_config_path():
    # Same Windows Known Folder used by xiaomiao-api-setup, including redirected desktops.
    if os.name == 'nt':
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) != 0:
            raise CredentialError('无法定位小描共享 API 配置，请明确指定凭据文件')
        return Path(buf.value) / 'xiaomiao_api.txt'
    return Path.home() / '.config/xiaomiao/xiaomiao_api.txt'


def resolve_credential(default, explicit=None):
    """Select a fixed known file locally; never scan, disclose keys, or query balances."""
    if explicit is not None:
        path = Path(explicit).expanduser()
        read_token(path)  # Explicit missing/invalid configuration must never fall back.
        return path.resolve()
    default = Path(default)
    if default.exists():
        read_token(default)
        return default.resolve()
    shared = shared_config_path()
    if shared.exists():
        read_token(shared)
        return shared.resolve()
    candidates = []
    for name in ('cell-figure-plus-customer.txt', 'figure_pro-customer.txt', 'cell_figure_ds-customer.txt'):
        path = default.parent / name
        if path.exists():
            candidates.append((path, read_token(path)))
    if not candidates:
        raise CredentialError('未找到已保存的小描 API Key，请提供小描 API Key。')
    if len({token for _, token in candidates}) != 1:
        raise CredentialError('本地有多个不同的 API Key，请指定使用哪个凭据文件。')
    return candidates[0][0].resolve()



def save_token(path, token):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Credential ciphertext only; use exclusive file creation to avoid silent rotation.
    with path.open('x', encoding='ascii') as f:
        f.write(transform(token.encode('utf-16-le'), True).hex())
        f.flush()
        os.fsync(f.fileno())
