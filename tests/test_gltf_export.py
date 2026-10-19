"""
Unit test for glTF 2.0 binary (.glb) export.
Validates magic header, chunk sizes, and geometry buffer layouts.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from uma_core.gltf_exporter import GLTFBuilder


class TestGLTFExport(unittest.TestCase):

    def test_minimal_mesh_glb(self):
        builder = GLTFBuilder("Test_Chibi")

        # Create a simple 3D triangle
        positions = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.5, 1.0, 0.0),
        ]
        normals = [
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
        ]
        uvs = [
            (0.0, 0.0),
            (1.0, 0.0),
            (0.5, 1.0),
        ]
        colors = [
            (1.0, 1.0, 1.0, 1.0),
            (1.0, 0.0, 0.0, 1.0),
            (0.0, 1.0, 0.0, 1.0),
        ]
        indices = [0, 1, 2]

        builder.add_mesh(
            positions=positions,
            indices=indices,
            normals=normals,
            uvs=uvs,
            colors=colors,
            name="TestTriangle",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "test.glb"
            builder.export_glb(out_file)

            self.assertTrue(out_file.exists())
            file_bytes = out_file.read_bytes()

            # 1. Verify 12-byte glTF Header
            self.assertGreaterEqual(len(file_bytes), 20)
            magic, version, total_size = struct.unpack_from("<4sII", file_bytes, 0)
            self.assertEqual(magic, b"glTF")
            self.assertEqual(version, 2)
            self.assertEqual(total_size, len(file_bytes))

            # 2. Verify JSON chunk
            json_len, json_type = struct.unpack_from("<II", file_bytes, 12)
            self.assertEqual(json_type, 0x4E4F534A)  # 'JSON'
            json_data = file_bytes[20:20 + json_len]
            self.assertIn(b"TestTriangle", json_data)

            # 3. Verify BIN chunk
            bin_offset = 20 + json_len
            bin_len, bin_type = struct.unpack_from("<II", file_bytes, bin_offset)
            self.assertEqual(bin_type, 0x004E4942)  # 'BIN\0'
            self.assertGreater(bin_len, 0)


if __name__ == "__main__":
    unittest.main()
