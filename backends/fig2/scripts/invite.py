"""Single-order permits, encrypted locally for safe retry; never a balance credit."""
import re
from credentials import transform


def encrypt(code):
    if not isinstance(code, str) or not re.fullmatch(r'fgp_inv_[A-Za-z0-9_-]{32,64}', code.strip()):
        raise ValueError('请提供有效的 Figure Pro 一次性邀请码')
    return transform(code.strip().encode('utf-8'), True).hex()


def decrypt(state):
    value = state.get('invite_ciphertext')
    if not value:
        return None  # Old accepted order replays remain valid without a permit.
    return transform(bytes.fromhex(value), False).decode('utf-8')
