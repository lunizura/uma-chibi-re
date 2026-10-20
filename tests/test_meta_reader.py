import unittest
from pathlib import Path
import sys

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uma_core.meta_reader import MetaDatabase, AssetRecord


class TestMetaReader(unittest.TestCase):
    """Automated tests for SQLite3MC meta database decryptor and query engine."""

    @classmethod
    def setUpClass(cls):
        try:
            with MetaDatabase() as db:
                pass
        except Exception as e:
            raise unittest.SkipTest(f"Skipping meta reader integration tests (requires local game installation): {e}")

    def test_database_connection_and_auth(self):
        with MetaDatabase() as db:
            self.assertTrue(db._is_open)
            records = db.find_assets("%mini/body%", limit=5)
            self.assertGreater(len(records), 0)
            for r in records:
                self.assertIsInstance(r, AssetRecord)
                self.assertTrue(len(r.hash) == 32)
                self.assertNotEqual(r.key, 0)

    def test_get_chibi_characters(self):
        with MetaDatabase() as db:
            characters = db.get_chibi_characters()
            self.assertGreater(len(characters), 10)
            chara_ids = [c["chara_id"] for c in characters]
            # Special Week (1001_00) should be present
            self.assertTrue(any("1001" in cid for cid in chara_ids))

    def test_character_asset_bundle_set(self):
        with MetaDatabase() as db:
            assets = db.get_character_asset_bundle_set("1001_00")
            self.assertIn("hair", assets)
            self.assertIn("body", assets)
            self.assertIn("tail", assets)
            self.assertGreater(len(assets["hair"]), 0)


if __name__ == "__main__":
    unittest.main()
