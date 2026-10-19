"""
mesh_processor.py - 3D Geometry and Texture Extraction Pipeline.

Converts UnityPy mesh objects, submeshes, and OBJ streams into normalized,
compliant vertex attribute buffers for Khronos glTF 2.0 serialization.
"""

from __future__ import annotations

import io
from typing import Optional, Tuple, List, Dict
from PIL import Image


class MeshData:
    """Encapsulates indexed geometry buffers for a single 3D mesh."""

    def __init__(
        self,
        name: str,
        positions: List[Tuple[float, float, float]],
        indices: List[int],
        normals: Optional[List[Tuple[float, float, float]]] = None,
        uvs: Optional[List[Tuple[float, float]]] = None,
    ):
        self.name = name
        self.positions = positions
        self.indices = indices
        self.normals = normals or []
        self.uvs = uvs or []

    @property
    def vertex_count(self) -> int:
        return len(self.positions)

    @property
    def triangle_count(self) -> int:
        return len(self.indices) // 3


class MeshProcessor:
    """Transforms raw mesh representations into normalized GLTF geometry."""

    @staticmethod
    def parse_obj_string(obj_text: str, name: str = "SubMesh") -> MeshData:
        """
        Parses Wavefront OBJ text into deduplicated vertex attribute arrays.
        Inverts UV V coordinate (1.0 - v) to adhere to glTF 2.0 texture mapping standard.
        """
        raw_positions: List[Tuple[float, float, float]] = []
        raw_uvs: List[Tuple[float, float]] = []
        raw_normals: List[Tuple[float, float, float]] = []

        comb_positions: List[Tuple[float, float, float]] = []
        comb_uvs: List[Tuple[float, float]] = []
        comb_normals: List[Tuple[float, float, float]] = []
        indices: List[int] = []

        vert_map: Dict[Tuple[int, Optional[int], Optional[int]], int] = {}

        for line in obj_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            tag = parts[0]

            if tag == "v":
                raw_positions.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif tag == "vt":
                raw_uvs.append((float(parts[1]), float(parts[2])))
            elif tag == "vn":
                raw_normals.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif tag == "f":
                face_indices: List[int] = []
                for p in parts[1:]:
                    tokens = p.split("/")
                    v_i = int(tokens[0]) - 1
                    vt_i = int(tokens[1]) - 1 if len(tokens) > 1 and tokens[1] else None
                    vn_i = int(tokens[2]) - 1 if len(tokens) > 2 and tokens[2] else None

                    key = (v_i, vt_i, vn_i)
                    if key not in vert_map:
                        new_idx = len(comb_positions)
                        vert_map[key] = new_idx
                        comb_positions.append(raw_positions[v_i])

                        if vt_i is not None and vt_i < len(raw_uvs):
                            u, v = raw_uvs[vt_i]
                            comb_uvs.append((u, 1.0 - v))
                        else:
                            comb_uvs.append((0.0, 0.0))

                        if vn_i is not None and vn_i < len(raw_normals):
                            comb_normals.append(raw_normals[vn_i])
                        else:
                            comb_normals.append((0.0, 1.0, 0.0))

                    face_indices.append(vert_map[key])

                # Fan-triangulation for quads and n-gons
                for i in range(1, len(face_indices) - 1):
                    indices.extend([face_indices[0], face_indices[i], face_indices[i + 1]])

        return MeshData(
            name=name,
            positions=comb_positions,
            indices=indices,
            normals=comb_normals if comb_normals else None,
            uvs=comb_uvs if comb_uvs else None,
        )

    @staticmethod
    def pil_image_to_png_bytes(image: Image.Image) -> bytes:
        """Encodes PIL Image into optimized PNG byte buffer for binary glTF embedding."""
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
