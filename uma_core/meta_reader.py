"""
meta_reader.py - Secure SQLite3MC Metadata Database Reader for Umamusume: Pretty Derby.

Handles SQLite3MultipleCiphers AES-256-CBC encrypted metadata storage (`meta`),
extracting file hashes, sizes, and XOR decryption keys for asset bundles.
"""

from __future__ import annotations

import ctypes
from ctypes import c_char_p, c_int, c_int64, c_void_p, byref, POINTER
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Generator


@dataclass(frozen=True)
class AssetRecord:
    """Represents a registered asset bundle in Umamusume's meta catalog."""
    manifest: str
    name: str
    hash: str
    size: int
    key: int

    @property
    def bundle_subpath(self) -> str:
        """Returns relative path within dat/ storage (e.g. 'CO/CO34Z...')."""
        return f"{self.hash[:2]}/{self.hash}"

    def get_bundle_file(self, data_root: Path) -> Path:
        """Resolves absolute path to bundle file under Persistent/dat/."""
        return data_root / "dat" / self.hash[:2] / self.hash


class MetaDatabase:
    """
    Interface for querying Umamusume's encrypted `meta` SQLite database using `sqlite3mc`.
    """

    DEFAULT_BASE_KEY = bytes([
        0xF1, 0x70, 0xCE, 0xA4, 0xDF, 0xCE, 0xA3, 0xE1, 0xA5, 0xD8, 0xC7, 0x0B, 0xD1
    ])

    DEFAULT_KEY_GLOBAL = bytes([
        0x36, 0x23, 0x6B, 0x4C, 0x2A, 0x39, 0x21, 0x75, 0x52, 0x26, 0x32, 0x76, 0x25,
        0x50, 0x3F, 0x35, 0x5D, 0x77, 0x58, 0x6D, 0x40, 0x71, 0x38, 0x5E, 0x4C, 0x31,
        0x28, 0x74, 0x29, 0x59, 0x37, 0x24, 0x53
    ])

    def __init__(
        self,
        meta_path: Optional[Path | str] = None,
        dll_path: Optional[Path | str] = None,
    ):
        pkg_dir = Path(__file__).resolve().parent
        self.dll_path = Path(dll_path) if dll_path else pkg_dir / "sqlite3mc_x64.dll"
        if not self.dll_path.exists():
            raise FileNotFoundError(f"sqlite3mc library not found at: {self.dll_path}")

        if meta_path:
            self.meta_path = Path(meta_path)
        else:
            # Auto-detect default steam directory
            steam_default = Path(
                r"D:\SteamLibrary\steamapps\common\UmamusumePrettyDerby\UmamusumePrettyDerby_Data\Persistent\meta"
            )
            local_default = Path.home() / "AppData/LocalLow/Cygames/umamusume/meta"
            if steam_default.exists():
                self.meta_path = steam_default
            elif local_default.exists():
                self.meta_path = local_default
            else:
                self.meta_path = steam_default

        self._db = c_void_p()
        self._mc = self._init_bindings()
        self._is_open = False

    def _init_bindings(self):
        mc = ctypes.cdll.LoadLibrary(str(self.dll_path))
        mc.sqlite3_open.argtypes = [c_char_p, POINTER(c_void_p)]
        mc.sqlite3_open.restype = c_int

        mc.sqlite3_key.argtypes = [c_void_p, c_char_p, c_int]
        mc.sqlite3_key.restype = c_int

        mc.sqlite3_prepare_v2.argtypes = [c_void_p, c_char_p, c_int, POINTER(c_void_p), c_void_p]
        mc.sqlite3_prepare_v2.restype = c_int

        mc.sqlite3_step.argtypes = [c_void_p]
        mc.sqlite3_step.restype = c_int

        mc.sqlite3_column_text.argtypes = [c_void_p, c_int]
        mc.sqlite3_column_text.restype = c_char_p

        mc.sqlite3_column_int64.argtypes = [c_void_p, c_int]
        mc.sqlite3_column_int64.restype = c_int64

        mc.sqlite3_finalize.argtypes = [c_void_p]
        mc.sqlite3_finalize.restype = c_int

        mc.sqlite3_close.argtypes = [c_void_p]
        mc.sqlite3_close.restype = c_int
        return mc

    def open(self) -> None:
        """Opens and authenticates the encrypted SQLite database."""
        if self._is_open:
            return

        if not self.meta_path.exists():
            raise FileNotFoundError(f"Umamusume meta database file not found: {self.meta_path}")

        rc = self._mc.sqlite3_open(str(self.meta_path).encode("utf-8"), byref(self._db))
        if rc != 0:
            raise RuntimeError(f"sqlite3_open failed with status code {rc}")

        # Derive 33-byte AES-256-CBC decryption key
        derived_key = bytes([
            self.DEFAULT_KEY_GLOBAL[i] ^ self.DEFAULT_BASE_KEY[i % len(self.DEFAULT_BASE_KEY)]
            for i in range(len(self.DEFAULT_KEY_GLOBAL))
        ])

        rc = self._mc.sqlite3_key(self._db, derived_key, len(derived_key))
        if rc != 0:
            self.close()
            raise RuntimeError(f"sqlite3_key decryption failed with code {rc}")

        # Verify key with PRAGMA quick check
        stmt = c_void_p()
        rc = self._mc.sqlite3_prepare_v2(self._db, b"PRAGMA quick_check(1);", -1, byref(stmt), None)
        if rc != 0 or self._mc.sqlite3_step(stmt) != 100:
            if stmt:
                self._mc.sqlite3_finalize(stmt)
            self.close()
            raise RuntimeError("Database key authentication failed (invalid key or corrupted database).")
        self._mc.sqlite3_finalize(stmt)
        self._is_open = True

    def close(self) -> None:
        """Closes the database connection."""
        if self._is_open and self._db:
            self._mc.sqlite3_close(self._db)
            self._db = c_void_p()
            self._is_open = False

    def __enter__(self) -> MetaDatabase:
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def query(self, sql: str) -> List[AssetRecord]:
        """Executes a SELECT query returning AssetRecords from table `a`."""
        if not self._is_open:
            self.open()

        stmt = c_void_p()
        rc = self._mc.sqlite3_prepare_v2(self._db, sql.encode("utf-8"), -1, byref(stmt), None)
        if rc != 0:
            raise RuntimeError(f"Failed to prepare SQL statement: {sql} (code {rc})")

        records: List[AssetRecord] = []
        try:
            while self._mc.sqlite3_step(stmt) == 100:  # SQLITE_ROW
                m_raw = self._mc.sqlite3_column_text(stmt, 0)
                n_raw = self._mc.sqlite3_column_text(stmt, 1)
                h_raw = self._mc.sqlite3_column_text(stmt, 2)
                l_val = self._mc.sqlite3_column_int64(stmt, 3)
                e_val = self._mc.sqlite3_column_int64(stmt, 4)

                records.append(
                    AssetRecord(
                        manifest=m_raw.decode("utf-8", "ignore") if m_raw else "",
                        name=n_raw.decode("utf-8", "ignore") if n_raw else "",
                        hash=h_raw.decode("utf-8", "ignore") if h_raw else "",
                        size=int(l_val),
                        key=int(e_val),
                    )
                )
        finally:
            self._mc.sqlite3_finalize(stmt)

        return records

    def find_assets(self, pattern: str, limit: int = 100) -> List[AssetRecord]:
        """Finds assets matching a SQL LIKE pattern."""
        sql = f"SELECT m, n, h, l, e FROM a WHERE n LIKE '{pattern}' LIMIT {limit};"
        return self.query(sql)

    def get_chibi_characters(self) -> List[Dict[str, str]]:
        """
        Discovers all unique Chibi character models available in the database.
        Returns a list of dictionaries with chara_id, hair_prefab, and clothing codes.
        """
        sql = "SELECT m, n, h, l, e FROM a WHERE n LIKE '3d/chara/mini/head/%/pfb%hair';"
        records = self.query(sql)
        
        characters = []
        seen = set()
        for r in records:
            # Example path: 3d/chara/mini/head/mchr1001_00/pfb_mchr1001_00_hair
            parts = r.name.split("/")
            if len(parts) >= 5:
                tag = parts[4]  # mchr1001_00
                chara_id = tag.replace("mchr", "")
                if chara_id not in seen:
                    seen.add(chara_id)
                    characters.append({
                        "tag": tag,
                        "chara_id": chara_id,
                        "hair_path": r.name,
                        "hash": r.hash,
                        "key": r.key,
                    })
        return sorted(characters, key=lambda x: x["chara_id"])

    def get_character_asset_bundle_set(self, chara_id: str) -> Dict[str, List[AssetRecord]]:
        """
        Retrieves all relevant asset bundles for a given character ID (e.g. '1001_00' or '1001').
        Categorizes them into: hair_mesh, hair_textures, face_mesh, face_textures, body_mesh, tail_mesh.
        """
        clean_id = chara_id.replace("mchr", "")
        base_id = clean_id.split("_")[0]  # e.g. 1001

        assets = {
            "hair": self.find_assets(f"%mini/head/mchr{clean_id}%pfb%hair%"),
            "hair_mat": self.find_assets(f"%mini/head/mchr{clean_id}%materials%hair%"),
            "hair_textures": self.find_assets(f"%mini/head/mchr{clean_id}%textures%"),
            "face": self.find_assets(f"%mini/head/mchr0001_00/pfb%face0%"),
            "face_textures": self.find_assets(f"%mini/head/mchr0001_00/textures%"),
            "body": self.find_assets(f"%mini/body/mbdy0002_00/pfb%"),
            "tail": self.find_assets(f"%mini/tail/mtail0001_00/pfb_mtail%"),
            "tail_textures": self.find_assets(f"%mini/tail/mtail0001_00/textures%"),
        }
        return assets
