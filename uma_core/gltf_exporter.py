"""
glTF 2.0 Binary (.glb) Exporter for umamusume 3D assets.
Converts extracted mesh channels (positions, normals, UVs, colors, indices) and textures
into standard Khronos glTF 2.0 binary files ready for 1-click Blender import.
"""

import json
import struct
from pathlib import Path
from typing import Optional, Union


class GLTFBuilder:
    """Constructs a compliant, self-contained binary glTF 2.0 (.glb) container."""

    def __init__(self, model_name: str = "Umamusume_Chibi"):
        self.model_name = model_name
        self.bin_buffer = bytearray()
        self.buffer_views = []
        self.accessors = []
        self.meshes = []
        self.nodes = []
        self.materials = []
        self.images = []
        self.textures = []
        self.samplers = []

    def _pad_buffer(self, alignment: int = 4) -> None:
        """Pads the binary buffer to alignment boundary."""
        remainder = len(self.bin_buffer) % alignment
        if remainder > 0:
            self.bin_buffer.extend(b"\x00" * (alignment - remainder))

    def _add_buffer_view(self, data: bytes, target: Optional[int] = None) -> int:
        """Appends bytes to the binary chunk and creates a bufferView entry."""
        self._pad_buffer(4)
        offset = len(self.bin_buffer)
        length = len(data)
        self.bin_buffer.extend(data)

        view = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": length,
        }
        if target is not None:
            view["target"] = target

        view_idx = len(self.buffer_views)
        self.buffer_views.append(view)
        return view_idx

    def add_texture_png(self, png_bytes: bytes, name: str = "Texture") -> int:
        """Embeds a PNG texture directly into the glb binary payload."""
        view_idx = self._add_buffer_view(png_bytes)
        
        image_idx = len(self.images)
        self.images.append({
            "name": name,
            "mimeType": "image/png",
            "bufferView": view_idx,
        })

        if not self.samplers:
            self.samplers.append({
                "magFilter": 9729,  # LINEAR
                "minFilter": 9987,  # LINEAR_MIPMAP_LINEAR
                "wrapS": 10497,     # REPEAT
                "wrapT": 10497,     # REPEAT
            })

        tex_idx = len(self.textures)
        self.textures.append({
            "sampler": 0,
            "source": image_idx,
            "name": f"{name}_Texture",
        })

        mat_idx = len(self.materials)
        self.materials.append({
            "name": f"{name}_Material",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": tex_idx},
                "metallicFactor": 0.0,
                "roughnessFactor": 0.85,
            },
            "doubleSided": True,
        })
        return mat_idx

    def add_mesh(
        self,
        positions: list[tuple[float, float, float]],
        indices: list[int],
        normals: Optional[list[tuple[float, float, float]]] = None,
        uvs: Optional[list[tuple[float, float]]] = None,
        colors: Optional[list[tuple[float, float, float, float]]] = None,
        material_index: Optional[int] = None,
        name: str = "ChibiMesh",
    ) -> int:
        """
        Encodes a 3D submesh with positions, triangle indices, normals, UVs, and vertex colors.
        """
        attributes = {}

        # 1. POSITIONS (Vec3, Float32)
        pos_bytes = bytearray()
        min_pos = [float("inf")] * 3
        max_pos = [float("-inf")] * 3
        for p in positions:
            pos_bytes.extend(struct.pack("<fff", p[0], p[1], p[2]))
            for i in range(3):
                min_pos[i] = min(min_pos[i], p[i])
                max_pos[i] = max(max_pos[i], p[i])

        pos_view = self._add_buffer_view(bytes(pos_bytes), target=34962)  # ARRAY_BUFFER
        pos_acc = len(self.accessors)
        self.accessors.append({
            "bufferView": pos_view,
            "byteOffset": 0,
            "componentType": 5126,  # FLOAT
            "count": len(positions),
            "type": "VEC3",
            "min": min_pos,
            "max": max_pos,
        })
        attributes["POSITION"] = pos_acc

        # 2. NORMALS (Vec3, Float32)
        if normals and len(normals) == len(positions):
            norm_bytes = bytearray()
            for n in normals:
                norm_bytes.extend(struct.pack("<fff", n[0], n[1], n[2]))
            norm_view = self._add_buffer_view(bytes(norm_bytes), target=34962)
            norm_acc = len(self.accessors)
            self.accessors.append({
                "bufferView": norm_view,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3",
            })
            attributes["NORMAL"] = norm_acc

        # 3. TEXCOORD_0 / UVs (Vec2, Float32)
        if uvs and len(uvs) == len(positions):
            uv_bytes = bytearray()
            for uv in uvs:
                uv_bytes.extend(struct.pack("<ff", uv[0], uv[1]))
            uv_view = self._add_buffer_view(bytes(uv_bytes), target=34962)
            uv_acc = len(self.accessors)
            self.accessors.append({
                "bufferView": uv_view,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(uvs),
                "type": "VEC2",
            })
            attributes["TEXCOORD_0"] = uv_acc

        # 4. COLOR_0 (Vec4, Float32)
        if colors and len(colors) == len(positions):
            color_bytes = bytearray()
            for c in colors:
                color_bytes.extend(struct.pack("<ffff", c[0], c[1], c[2], c[3]))
            color_view = self._add_buffer_view(bytes(color_bytes), target=34962)
            color_acc = len(self.accessors)
            self.accessors.append({
                "bufferView": color_view,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(colors),
                "type": "VEC4",
            })
            attributes["COLOR_0"] = color_acc

        # 5. INDICES (Triangles)
        max_idx = max(indices) if indices else 0
        use_uint32 = max_idx > 65535
        idx_bytes = bytearray()
        if use_uint32:
            for idx in indices:
                idx_bytes.extend(struct.pack("<I", idx))
            component_type = 5125  # UNSIGNED_INT
        else:
            for idx in indices:
                idx_bytes.extend(struct.pack("<H", idx))
            component_type = 5123  # UNSIGNED_SHORT

        idx_view = self._add_buffer_view(bytes(idx_bytes), target=34963)  # ELEMENT_ARRAY_BUFFER
        idx_acc = len(self.accessors)
        self.accessors.append({
            "bufferView": idx_view,
            "byteOffset": 0,
            "componentType": component_type,
            "count": len(indices),
            "type": "SCALAR",
        })

        primitive = {
            "attributes": attributes,
            "indices": idx_acc,
            "mode": 4,  # TRIANGLES
        }
        if material_index is not None and material_index < len(self.materials):
            primitive["material"] = material_index

        mesh_idx = len(self.meshes)
        self.meshes.append({
            "name": name,
            "primitives": [primitive],
        })

        node_idx = len(self.nodes)
        self.nodes.append({
            "name": name,
            "mesh": mesh_idx,
        })
        return node_idx

    def export_glb(self, output_path: Union[str, Path]) -> Path:
        """Compiles the full binary glTF (.glb) container and saves to disk."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        gltf_dict = {
            "asset": {
                "version": "2.0",
                "generator": "uma-chibi-pipeline (lunizura)",
            },
            "scene": 0,
            "scenes": [
                {
                    "name": self.model_name,
                    "nodes": list(range(len(self.nodes))),
                }
            ],
            "nodes": self.nodes,
            "meshes": self.meshes,
            "accessors": self.accessors,
            "bufferViews": self.buffer_views,
            "buffers": [{"byteLength": len(self.bin_buffer)}],
        }

        if self.materials:
            gltf_dict["materials"] = self.materials
        if self.textures:
            gltf_dict["textures"] = self.textures
        if self.images:
            gltf_dict["images"] = self.images
        if self.samplers:
            gltf_dict["samplers"] = self.samplers

        # 1. Encode JSON chunk
        json_bytes = json.dumps(gltf_dict, separators=(",", ":")).encode("utf-8")
        # Pad JSON to 4-byte boundary with spaces (0x20)
        json_remainder = len(json_bytes) % 4
        if json_remainder > 0:
            json_bytes += b" " * (4 - json_remainder)
        json_length = len(json_bytes)

        # 2. Pad BIN chunk to 4-byte boundary with null bytes (0x00)
        self._pad_buffer(4)
        bin_length = len(self.bin_buffer)

        # 3. Compute Total .glb file size (12 header + 8 json header + json_len + 8 bin header + bin_len)
        total_size = 12 + 8 + json_length + 8 + bin_length

        with open(out, "wb") as f:
            # Header
            f.write(struct.pack("<4sII", b"glTF", 2, total_size))
            # JSON Chunk
            f.write(struct.pack("<II", json_length, 0x4E4F534A))  # 'JSON'
            f.write(json_bytes)
            # BIN Chunk
            f.write(struct.pack("<II", bin_length, 0x004E4942))  # 'BIN\0'
            f.write(self.bin_buffer)

        return out
