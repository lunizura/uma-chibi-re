"""
asset_decryptor.py - Fast Vectorized UnityFS Asset Bundle Decryption.

Implements the 88-byte rolling XOR de-obfuscation scheme used by Umamusume: Pretty Derby
PC / Steam client for UnityFS asset bundles located in `Persistent/dat/`.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Union
import numpy as np


class AssetDecryptor:
    """High-throughput XOR decryptor for Umamusume UnityFS asset bundles."""

    # 11-byte Cygames base seed constant
    DEFAULT_BASE_KEYS = bytes([
        0x53, 0x2B, 0x46, 0x31, 0xE4, 0xA7, 0xB9, 0x47, 0x3E, 0x7C, 0xFB
    ])

    @classmethod
    def generate_key_schedule(cls, bundle_key: int) -> bytes:
        """
        Derives the 88-byte cyclical XOR keystream from the 64-bit integer asset key.
        """
        key_bytes = struct.pack("<q", bundle_key)
        schedule = bytearray(88)
        for i, b in enumerate(cls.DEFAULT_BASE_KEYS):
            for j in range(8):
                schedule[i * 8 + j] = b ^ key_bytes[j]
        return bytes(schedule)

    @classmethod
    def decrypt_bytes(cls, encrypted_data: Union[bytes, bytearray, memoryview], bundle_key: int) -> bytes:
        """
        Decrypts an in-memory buffer of a UnityFS asset bundle using vectorized NumPy XOR.
        
        Offsets 0..255 remain raw UnityFS headers.
        Offsets 256..end are XOR'd with the 88-byte schedule.
        """
        data_len = len(encrypted_data)
        if data_len <= 256 or bundle_key == 0:
            return bytes(encrypted_data)

        # Generate 88-byte key schedule
        schedule = cls.generate_key_schedule(bundle_key)
        schedule_np = np.frombuffer(schedule, dtype=np.uint8)

        # Convert encrypted payload to mutable uint8 array
        arr = np.frombuffer(bytearray(encrypted_data), dtype=np.uint8).copy()

        # Vectorized rolling XOR over data[256:]
        payload_len = data_len - 256
        start_phase = 256 % 88  # 80
        num_tiles = (payload_len // 88) + 2
        keystream_segment = np.tile(schedule_np, num_tiles)[start_phase : start_phase + payload_len]

        arr[256:] ^= keystream_segment
        return arr.tobytes()

    @classmethod
    def decrypt_file(cls, file_path: Union[str, Path], bundle_key: int) -> bytes:
        """
        Reads and decrypts a UnityFS asset bundle file from disk.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Asset bundle file not found: {path}")

        raw_bytes = path.read_bytes()
        return cls.decrypt_bytes(raw_bytes, bundle_key)
