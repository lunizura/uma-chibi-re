"""
pipeline.py - End-to-End Modular Umamusume Chibi 3D Asset Extraction Pipeline.

Coordinates database lookups, AES-256-CBC / 88-byte XOR decryption, UnityPy asset
deserialization, and binary glTF 2.0 generation for modular (Head, Body, Face, Tail)
3D character models.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from PIL import Image
import UnityPy

from .meta_reader import MetaDatabase, AssetRecord
from .asset_decryptor import AssetDecryptor
from .mesh_processor import MeshProcessor, MeshData
from .gltf_exporter import GLTFBuilder


class ChibiPipeline:
    """
    Orchestrates extraction of modular Umamusume Chibi models from local game files.
    """

    def __init__(
        self,
        meta_path: Optional[Path | str] = None,
        data_root: Optional[Path | str] = None,
    ):
        if data_root:
            self.data_root = Path(data_root)
        else:
            self.data_root = Path(
                r"D:\SteamLibrary\steamapps\common\UmamusumePrettyDerby\UmamusumePrettyDerby_Data\Persistent"
            )

        self.meta_db = MetaDatabase(meta_path=meta_path)

    def extract_bundle_assets(
        self, record: AssetRecord
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, Image.Image]]]:
        """
        Decrypts an asset bundle and extracts its constituent Mesh (OBJ strings)
        and Texture2D (PIL Images) components.
        """
        bundle_file = record.get_bundle_file(self.data_root)
        if not bundle_file.exists():
            raise FileNotFoundError(f"Asset bundle file missing on disk: {bundle_file}")

        decrypted_bytes = AssetDecryptor.decrypt_file(bundle_file, record.key)
        env = UnityPy.load(io.BytesIO(decrypted_bytes))

        meshes: List[Tuple[str, str]] = []
        textures: List[Tuple[str, Image.Image]] = []

        for obj in env.objects:
            if obj.type.name == "Mesh":
                m = obj.read()
                name = getattr(m, "m_Name", "Mesh")
                obj_str = m.export()
                if obj_str:
                    meshes.append((name, obj_str))
            elif obj.type.name == "Texture2D":
                t = obj.read()
                name = getattr(t, "m_Name", "Texture")
                try:
                    img = t.image
                    if img:
                        textures.append((name, img))
                except Exception:
                    pass

        return meshes, textures

    def compile_modular_glb(
        self,
        mesh_objs: List[Tuple[str, str]],
        textures: List[Tuple[str, Image.Image]],
        output_path: Path,
        model_name: str,
    ) -> Path:
        """
        Takes raw OBJ mesh strings and PIL images and compiles a self-contained GLB.
        """
        builder = GLTFBuilder(model_name)

        # 1. Embed primary texture if available
        mat_idx = None
        if textures:
            # Prefer diffuse textures
            diff_tex = next((img for name, img in textures if "diff" in name.lower()), textures[0][1])
            png_bytes = MeshProcessor.pil_image_to_png_bytes(diff_tex)
            mat_idx = builder.add_texture_png(png_bytes, name=f"{model_name}_Mat")

        # 2. Add each submesh
        for mesh_name, obj_str in mesh_objs:
            mesh_data = MeshProcessor.parse_obj_string(obj_str, name=mesh_name)
            if mesh_data.vertex_count > 0:
                builder.add_mesh(
                    positions=mesh_data.positions,
                    indices=mesh_data.indices,
                    normals=mesh_data.normals,
                    uvs=mesh_data.uvs,
                    material_index=mat_idx,
                    name=mesh_name,
                )

        return builder.export_glb(output_path)

    def extract_character(
        self,
        chara_id: str,
        output_dir: Path | str,
        body_id: str = "0002_00",
        tail_id: str = "0001_00",
        build_assembled: bool = True,
    ) -> Dict[str, Path]:
        """
        Extracts a full modular chibi character set:
        - hair.glb
        - body.glb
        - face.glb
        - tail.glb
        - assembled.glb (optional combined full avatar)
        """
        out_dir = Path(output_dir) / f"chibi_{chara_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        results: Dict[str, Path] = {}

        clean_id = chara_id.replace("mchr", "")
        # If user passes 1001, normalize to 1001_00
        tag_id = clean_id if "_" in clean_id else f"{clean_id}_00"
        base_num = tag_id.split("_")[0]

        with self.meta_db as db:
            # Resolve body: if 'auto', check for signature costume first
            actual_body_id = body_id
            if body_id == "auto" or body_id is None:
                sig_body = db.find_assets(f"%mini/body/mbdy{tag_id}%pfb%")
                actual_body_id = tag_id if sig_body else "0002_00"

            # 1. HAIR
            hair_records = db.find_assets(f"%mini/head/mchr{tag_id}%pfb%hair%")
            hair_mat_records = db.find_assets(f"%mini/head/mchr{tag_id}%materials%hair%")

            if hair_records:
                hair_meshes, _ = self.extract_bundle_assets(hair_records[0])
                hair_textures = []
                if hair_mat_records:
                    _, hair_textures = self.extract_bundle_assets(hair_mat_records[0])

                hair_glb = self.compile_modular_glb(
                    hair_meshes, hair_textures, out_dir / "hair.glb", f"Chibi_{tag_id}_Hair"
                )
                results["hair"] = hair_glb

            # 2. BODY
            body_records = db.find_assets(f"%mini/body/mbdy{actual_body_id}%pfb_mbdy{actual_body_id}%")
            if not body_records:
                body_records = db.find_assets(f"%mini/body/mbdy{actual_body_id}%pfb%")

            body_tex_records = db.find_assets(f"%mini/body/mbdy{actual_body_id}%diff%")
            if not body_tex_records:
                body_tex_records = db.find_assets(f"%materials/mtl_mbdy{actual_body_id}%")

            if body_records:
                body_meshes, _ = self.extract_bundle_assets(body_records[0])
                body_textures = []
                if body_tex_records:
                    _, body_textures = self.extract_bundle_assets(body_tex_records[0])

                body_glb = self.compile_modular_glb(
                    body_meshes, body_textures, out_dir / "body.glb", f"Chibi_Body_{actual_body_id}"
                )
                results["body"] = body_glb

            # 3. FACE
            face_records = db.find_assets("%mini/head/mchr0001_00/pfb%face0%")
            face_tex_records = db.find_assets("%mini/head/mchr0001_00%face0_0_diff%")
            if face_records:
                face_meshes, _ = self.extract_bundle_assets(face_records[0])
                face_textures = []
                if face_tex_records:
                    _, face_textures = self.extract_bundle_assets(face_tex_records[0])

                face_glb = self.compile_modular_glb(
                    face_meshes, face_textures, out_dir / "face.glb", "Chibi_Face_Base"
                )
                results["face"] = face_glb

            # 4. TAIL
            tail_records = db.find_assets(f"%mini/tail/mtail{tail_id}%pfb_mtail%")
            tail_tex_records = db.find_assets(f"%mini/tail/mtail{tail_id}%{base_num}_diff%")
            if not tail_tex_records:
                tail_tex_records = db.find_assets(f"%mini/tail/mtail{tail_id}%1001_diff%")

            if tail_records:
                tail_meshes, _ = self.extract_bundle_assets(tail_records[0])
                tail_textures = []
                if tail_tex_records:
                    _, tail_textures = self.extract_bundle_assets(tail_tex_records[0])

                tail_glb = self.compile_modular_glb(
                    tail_meshes, tail_textures, out_dir / "tail.glb", f"Chibi_Tail_{tail_id}"
                )
                results["tail"] = tail_glb

            # 5. ASSEMBLED (Combined all-in-one GLB)
            if build_assembled and "hair" in results and "body" in results:
                assembled_builder = GLTFBuilder(f"Chibi_{tag_id}_Assembled")
                
                # Component bundles to stitch
                components = [
                    ("Hair", hair_meshes, hair_textures),
                    ("Body", body_meshes, body_textures),
                    ("Face", face_meshes, face_textures),
                    ("Tail", tail_meshes, tail_textures),
                ]

                for comp_name, m_list, t_list in components:
                    mat_idx = None
                    if t_list:
                        diff_tex = next((img for name, img in t_list if "diff" in name.lower()), t_list[0][1])
                        png_bytes = MeshProcessor.pil_image_to_png_bytes(diff_tex)
                        mat_idx = assembled_builder.add_texture_png(png_bytes, name=f"{comp_name}_Mat")

                    for m_name, obj_s in m_list:
                        m_data = MeshProcessor.parse_obj_string(obj_s, name=f"{comp_name}_{m_name}")
                        if m_data.vertex_count > 0:
                            assembled_builder.add_mesh(
                                positions=m_data.positions,
                                indices=m_data.indices,
                                normals=m_data.normals,
                                uvs=m_data.uvs,
                                material_index=mat_idx,
                                name=f"{comp_name}_{m_name}",
                            )

                assembled_path = out_dir / "assembled.glb"
                assembled_builder.export_glb(assembled_path)
                results["assembled"] = assembled_path

        return results
