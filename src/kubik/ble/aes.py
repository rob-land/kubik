"""AES-128 in pure Python.

GAN cubes encrypt every 20-byte notification, so the app needs a block cipher.
The packets are tiny and arrive at a few hundred hertz at most, which is well
within what Python can do — and it keeps `python-cryptography` out of the
dependency list, which matters for a Flatpak.
"""

from __future__ import annotations

_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16"
)
_INV_SBOX = bytearray(256)
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i
_INV_SBOX = bytes(_INV_SBOX)

_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


_MUL = [[0] * 256 for _ in range(15)]
for _b in range(256):
    _MUL[1][_b] = _b
    _MUL[2][_b] = _xtime(_b)
    _MUL[3][_b] = _xtime(_b) ^ _b
    _MUL[9][_b] = _xtime(_xtime(_xtime(_b))) ^ _b
    _MUL[11][_b] = _xtime(_xtime(_xtime(_b)) ^ _b) ^ _b
    _MUL[13][_b] = _xtime(_xtime(_xtime(_b) ^ _b)) ^ _b
    _MUL[14][_b] = _xtime(_xtime(_xtime(_b) ^ _b) ^ _b)


class AES128:
    """Single-block AES-128. Key must be 16 bytes."""

    __slots__ = ("_rk",)

    def __init__(self, key: bytes):
        if len(key) != 16:
            raise ValueError("AES-128 needs a 16-byte key")
        rk = [list(key[i:i + 4]) for i in range(0, 16, 4)]
        for i in range(4, 44):
            word = list(rk[i - 1])
            if i % 4 == 0:
                word = word[1:] + word[:1]
                word = [_SBOX[b] for b in word]
                word[0] ^= _RCON[i // 4 - 1]
            rk.append([rk[i - 4][j] ^ word[j] for j in range(4)])
        self._rk = [bytes(b for w in rk[r * 4:r * 4 + 4] for b in w)
                    for r in range(11)]

    @staticmethod
    def _add_round_key(s, k):
        return bytearray(a ^ b for a, b in zip(s, k))

    def encrypt_block(self, block: bytes) -> bytes:
        s = self._add_round_key(block, self._rk[0])
        for rnd in range(1, 10):
            s = bytearray(_SBOX[b] for b in s)
            s = self._shift_rows(s)
            s = self._mix_columns(s)
            s = self._add_round_key(s, self._rk[rnd])
        s = bytearray(_SBOX[b] for b in s)
        s = self._shift_rows(s)
        return bytes(self._add_round_key(s, self._rk[10]))

    def decrypt_block(self, block: bytes) -> bytes:
        s = self._add_round_key(block, self._rk[10])
        for rnd in range(9, 0, -1):
            s = self._inv_shift_rows(s)
            s = bytearray(_INV_SBOX[b] for b in s)
            s = self._add_round_key(s, self._rk[rnd])
            s = self._inv_mix_columns(s)
        s = self._inv_shift_rows(s)
        s = bytearray(_INV_SBOX[b] for b in s)
        return bytes(self._add_round_key(s, self._rk[0]))

    # State is column-major: byte 4*c + r.

    @staticmethod
    def _shift_rows(s):
        return bytearray((s[(i + 4 * (i % 4)) % 16] for i in range(16)))

    @staticmethod
    def _inv_shift_rows(s):
        out = bytearray(16)
        for i in range(16):
            out[(i + 4 * (i % 4)) % 16] = s[i]
        return out

    @staticmethod
    def _mix_columns(s):
        out = bytearray(16)
        for c in range(0, 16, 4):
            a0, a1, a2, a3 = s[c], s[c + 1], s[c + 2], s[c + 3]
            out[c] = _MUL[2][a0] ^ _MUL[3][a1] ^ a2 ^ a3
            out[c + 1] = a0 ^ _MUL[2][a1] ^ _MUL[3][a2] ^ a3
            out[c + 2] = a0 ^ a1 ^ _MUL[2][a2] ^ _MUL[3][a3]
            out[c + 3] = _MUL[3][a0] ^ a1 ^ a2 ^ _MUL[2][a3]
        return out

    @staticmethod
    def _inv_mix_columns(s):
        out = bytearray(16)
        for c in range(0, 16, 4):
            a0, a1, a2, a3 = s[c], s[c + 1], s[c + 2], s[c + 3]
            out[c] = _MUL[14][a0] ^ _MUL[11][a1] ^ _MUL[13][a2] ^ _MUL[9][a3]
            out[c + 1] = _MUL[9][a0] ^ _MUL[14][a1] ^ _MUL[11][a2] ^ _MUL[13][a3]
            out[c + 2] = _MUL[13][a0] ^ _MUL[9][a1] ^ _MUL[14][a2] ^ _MUL[11][a3]
            out[c + 3] = _MUL[11][a0] ^ _MUL[13][a1] ^ _MUL[9][a2] ^ _MUL[14][a3]
        return out


def cbc_decrypt_block(cipher: AES128, iv: bytes, data: bytes) -> bytes:
    """One-block CBC decrypt — GAN never chains beyond a single block."""
    plain = cipher.decrypt_block(data[:16])
    return bytes(a ^ b for a, b in zip(plain, iv))


def cbc_encrypt_block(cipher: AES128, iv: bytes, data: bytes) -> bytes:
    return cipher.encrypt_block(bytes(a ^ b for a, b in zip(data[:16], iv)))
