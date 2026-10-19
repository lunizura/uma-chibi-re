import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uma_core.asset_decryptor import AssetDecryptor


class TestAssetDecryptor(unittest.TestCase):
    """Automated unit tests for asset bundle XOR de-obfuscation."""

    def test_key_schedule_length(self):
        schedule = AssetDecryptor.generate_key_schedule(6552348525337925850)
        self.assertEqual(len(schedule), 88)

    def test_reversibility(self):
        original = b"A" * 256 + b"SUPER_SECRET_PAYLOAD_1234567890" * 50
        key = 1234567891011121314
        encrypted = AssetDecryptor.decrypt_bytes(original, key)
        decrypted = AssetDecryptor.decrypt_bytes(encrypted, key)
        self.assertEqual(original, decrypted)

    def test_header_preservation(self):
        header = b"UnityFS\x00\x00\x00\x00\x07" + b"\x00" * 244
        payload = b"\xFF" * 1024
        full = header + payload
        key = 9876543210
        decrypted = AssetDecryptor.decrypt_bytes(full, key)
        self.assertEqual(decrypted[:256], header)
        self.assertNotEqual(decrypted[256:], payload)

    def test_real_bundle_decryption(self):
        bundle_path = Path(
            r"D:\SteamLibrary\steamapps\common\UmamusumePrettyDerby\UmamusumePrettyDerby_Data\Persistent\dat\CO\CO34ZBCRFFFPHMGRM47AK7HLL5UGSW6T"
        )
        if bundle_path.exists():
            key = 6552348525337925850
            decrypted = AssetDecryptor.decrypt_file(bundle_path, key)
            self.assertTrue(decrypted.startswith(b"UnityFS"))
            self.assertEqual(len(decrypted), bundle_path.stat().st_size)


if __name__ == "__main__":
    unittest.main()
