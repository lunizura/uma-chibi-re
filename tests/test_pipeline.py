import unittest
from pathlib import Path
import struct
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from uma_core.pipeline import ChibiPipeline


class TestPipeline(unittest.TestCase):
    """Integration test suite for the complete modular Chibi 3D extraction pipeline."""

    @classmethod
    def setUpClass(cls):
        cls.pipeline = ChibiPipeline()
        cls.output_dir = PROJECT_ROOT / "tests" / "temp_output"
        cls.results = cls.pipeline.extract_character(
            chara_id="1001_00",
            output_dir=cls.output_dir,
            build_assembled=True,
        )

    def test_modular_components_exported(self):
        for comp in ["hair", "body", "face", "tail", "assembled"]:
            self.assertIn(comp, self.results, f"Component {comp} was not generated.")
            file_path = self.results[comp]
            self.assertTrue(file_path.exists(), f"File {file_path} does not exist.")
            self.assertGreater(file_path.stat().st_size, 1000)

    def test_gltf_binary_header_validity(self):
        for comp, file_path in self.results.items():
            data = file_path.read_bytes()
            magic, ver, length = struct.unpack("<4sII", data[:12])
            self.assertEqual(magic, b"glTF", f"{file_path.name} magic header is invalid.")
            self.assertEqual(ver, 2, f"{file_path.name} glTF version is not 2.")
            self.assertEqual(length, len(data), f"{file_path.name} length field does not match file size.")


if __name__ == "__main__":
    unittest.main()
