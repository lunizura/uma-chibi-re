"""
pipeline.py - End-to-End Modular Umamusume Chibi 3D Asset Extraction Pipeline.

Coordinates database lookups, AES-256-CBC / 88-byte XOR decryption, UnityPy asset
deserialization, and binary glTF 2.0 generation for modular (Head, Body, Face, Tail)
3D character models with skeletal alignment and multi-material facial expression mapping.
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

    # Anatomical bone offsets derived from the Umamusume Chibi skeleton hierarchy
    ATTACHMENT_OFFSETS = {
        "body": (0.0, 0.0, 0.0),
        "hair": (0.0, 0.4963, -0.0151),  # Neck joint
        "face": (0.0, 0.4963, -0.0151),  # Neck joint
        "tail": (0.0, 0.3053, -0.1176),  # Tail_Ctrl / Hip joint
    }

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
        offset: Optional[Tuple[float, float, float]] = None,
        alpha_mode: str = "OPAQUE",
    ) -> Path:
        """
        Takes raw OBJ mesh strings and PIL images and compiles a self-contained GLB.
        """
        builder = GLTFBuilder(model_name)

        # 1. Embed primary texture if available
        mat_idx = None
        if textures:
            diff_tex = next((img for name, img in textures if "diff" in name.lower()), textures[0][1])
            png_bytes = MeshProcessor.pil_image_to_png_bytes(diff_tex)
            mat_idx = builder.add_texture_png(png_bytes, name=f"{model_name}_Mat", alpha_mode=alpha_mode)

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
                    offset=offset,
                )

        return builder.export_glb(output_path)

    def compile_face_glb(
        self,
        face_meshes: List[Tuple[str, str]],
        face_textures: Dict[str, Image.Image],
        output_path: Path,
        model_name: str,
        offset: Optional[Tuple[float, float, float]] = None,
    ) -> Path:
        """
        Compiles face geometry with separated materials and alpha blending for
        eyes, eyebrows, cheeks, and mouth expressions.
        """
        builder = GLTFBuilder(model_name)
        mat_cache: Dict[str, Optional[int]] = {}

        for mesh_name, obj_str in face_meshes:
            m_data = MeshProcessor.parse_obj_string(obj_str, name=mesh_name)
            if m_data.vertex_count == 0:
                continue

            lower_name = mesh_name.lower()
            feat_key = "face"
            alpha_mode = "OPAQUE"
            if "eye" in lower_name:
                feat_key = "eye"
                alpha_mode = "BLEND"
            elif "mayu" in lower_name:
                feat_key = "mayu"
                alpha_mode = "BLEND"
            elif "mouth" in lower_name:
                feat_key = "mouth"
                alpha_mode = "BLEND"
            elif "cheek" in lower_name:
                feat_key = "cheek"
                alpha_mode = "BLEND"

            if feat_key not in mat_cache:
                tex_img = face_textures.get(feat_key) or face_textures.get("face")
                if tex_img:
                    png_bytes = MeshProcessor.pil_image_to_png_bytes(tex_img)
                    mat_cache[feat_key] = builder.add_texture_png(
                        png_bytes, name=f"Face_{feat_key.capitalize()}", alpha_mode=alpha_mode
                    )
                else:
                    mat_cache[feat_key] = None

            builder.add_mesh(
                positions=m_data.positions,
                indices=m_data.indices,
                normals=m_data.normals,
                uvs=m_data.uvs,
                material_index=mat_cache.get(feat_key),
                name=mesh_name,
                offset=offset,
            )

        return builder.export_glb(output_path)

    def extract_character(
        self,
        chara_id: str,
        output_dir: Path | str,
        body_id: str = "auto",
        tail_id: str = "0001_00",
        build_assembled: bool = True,
    ) -> Dict[str, Path]:
        """
        Extracts a full modular chibi character set:
        - hair.glb
        - body.glb
        - face.glb (with rendered eyes, eyebrows, cheeks, and mouth)
        - tail.glb
        - assembled.glb (combined full avatar aligned to body skeleton)
        """
        out_dir = Path(output_dir) / f"chibi_{chara_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        results: Dict[str, Path] = {}

        clean_id = chara_id.replace("mchr", "")
        tag_id = clean_id if "_" in clean_id else f"{clean_id}_00"
        base_num = tag_id.split("_")[0]

        with self.meta_db as db:
            # Resolve body: if 'auto', pick character's signature racewear if available
            actual_body_id = body_id
            if body_id == "auto" or body_id is None:
                sig_body = [
                    r for r in db.find_assets(f"%mini/body/mbdy{tag_id}%pfb%")
                    if "cloth" not in r.name.lower()
                ]
                actual_body_id = tag_id if sig_body else "0002_00"

            # 1. HAIR
            hair_records = [
                r for r in db.find_assets(f"%mini/head/mchr{tag_id}%pfb%hair%")
                if "cloth" not in r.name.lower()
            ]
            hair_mat_records = db.find_assets(f"%mini/head/mchr{tag_id}%materials%hair%")

            hair_meshes: List[Tuple[str, str]] = []
            hair_textures: List[Tuple[str, Image.Image]] = []
            if hair_records:
                hair_meshes, _ = self.extract_bundle_assets(hair_records[0])
                if hair_mat_records:
                    _, hair_textures = self.extract_bundle_assets(hair_mat_records[0])

                results["hair"] = self.compile_modular_glb(
                    hair_meshes, hair_textures, out_dir / "hair.glb", f"Chibi_{tag_id}_Hair"
                )

            # 2. BODY
            body_records = [
                r for r in db.find_assets(f"%mini/body/mbdy{actual_body_id}%pfb%")
                if "cloth" not in r.name.lower()
            ]
            body_tex_records = db.find_assets(f"%mini/body/mbdy{actual_body_id}%diff%")
            if not body_tex_records:
                body_tex_records = db.find_assets(f"%materials/mtl_mbdy{actual_body_id}%")

            body_meshes: List[Tuple[str, str]] = []
            body_textures: List[Tuple[str, Image.Image]] = []
            if body_records:
                body_meshes, _ = self.extract_bundle_assets(body_records[0])
                if body_tex_records:
                    _, body_textures = self.extract_bundle_assets(body_tex_records[0])

                results["body"] = self.compile_modular_glb(
                    body_meshes, body_textures, out_dir / "body.glb", f"Chibi_Body_{actual_body_id}"
                )

            # 3. FACE & FACIAL EXPRESSIONS
            face_records = [
                r for r in db.find_assets("%mini/head/mchr0001_00/pfb%face0%")
                if "cloth" not in r.name.lower()
            ]

            face_meshes: List[Tuple[str, str]] = []
            face_tex_map: Dict[str, Image.Image] = {}

            if face_records:
                face_meshes, _ = self.extract_bundle_assets(face_records[0])

                # Query expression textures
                skin_recs = db.find_assets("%mini/head/mchr0001_00%face0_0_diff%")
                eye_recs = db.find_assets(f"%mini/head/mchr{tag_id}%eye_diff%") or db.find_assets(f"%mini/head/mchr{base_num}%eye_diff%")
                mayu_recs = db.find_assets(f"%mini/head/mchr{tag_id}%mayu_diff%") or db.find_assets(f"%mini/head/mchr{base_num}%mayu_diff%")
                mouth_recs = db.find_assets(f"%mini/head/mchr{tag_id}%mouth_diff%") or db.find_assets(f"%mini/head/mchr{base_num}%mouth_diff%")
                cheek_recs = db.find_assets("%mini/head/mchr0001_00%cheek0%")

                for recs, key in [
                    (skin_recs, "face"),
                    (eye_recs, "eye"),
                    (mayu_recs, "mayu"),
                    (mouth_recs, "mouth"),
                    (cheek_recs, "cheek"),
                ]:
                    if recs:
                        _, t_list = self.extract_bundle_assets(recs[0])
                        if t_list:
                            face_tex_map[key] = t_list[0][1]

                results["face"] = self.compile_face_glb(
                    face_meshes, face_tex_map, out_dir / "face.glb", "Chibi_Face_Base"
                )

            # 4. TAIL
            tail_records = [
                r for r in db.find_assets(f"%mini/tail/mtail{tail_id}%pfb_mtail%")
                if "cloth" not in r.name.lower()
            ]
            tail_tex_records = db.find_assets(f"%mini/tail/mtail{tail_id}%{base_num}_diff%")
            if not tail_tex_records:
                tail_tex_records = db.find_assets(f"%mini/tail/mtail{tail_id}%1001_diff%")

            tail_meshes: List[Tuple[str, str]] = []
            tail_textures: List[Tuple[str, Image.Image]] = []
            if tail_records:
                tail_meshes, _ = self.extract_bundle_assets(tail_records[0])
                if tail_tex_records:
                    _, tail_textures = self.extract_bundle_assets(tail_tex_records[0])

                results["tail"] = self.compile_modular_glb(
                    tail_meshes, tail_textures, out_dir / "tail.glb", f"Chibi_Tail_{tail_id}"
                )

            # 5. ASSEMBLED (Combined all-in-one GLB with skeletal alignment)
            if build_assembled and "hair" in results and "body" in results:
                assembled_builder = GLTFBuilder(f"Chibi_{tag_id}_Assembled")

                # (1) Add Body at origin
                body_mat_idx = None
                if body_textures:
                    b_diff = next((img for name, img in body_textures if "diff" in name.lower()), body_textures[0][1])
                    body_mat_idx = assembled_builder.add_texture_png(
                        MeshProcessor.pil_image_to_png_bytes(b_diff), name="Body_Mat"
                    )
                for b_name, b_obj in body_meshes:
                    b_data = MeshProcessor.parse_obj_string(b_obj, name=f"Body_{b_name}")
                    if b_data.vertex_count > 0:
                        assembled_builder.add_mesh(
                            positions=b_data.positions,
                            indices=b_data.indices,
                            normals=b_data.normals,
                            uvs=b_data.uvs,
                            material_index=body_mat_idx,
                            name=f"Body_{b_name}",
                            offset=self.ATTACHMENT_OFFSETS["body"],
                        )

                # (2) Add Tail offset to Tail_Ctrl / Hip bone
                tail_mat_idx = None
                if tail_textures:
                    t_diff = next((img for name, img in tail_textures if "diff" in name.lower()), tail_textures[0][1])
                    tail_mat_idx = assembled_builder.add_texture_png(
                        MeshProcessor.pil_image_to_png_bytes(t_diff), name="Tail_Mat"
                    )
                for t_name, t_obj in tail_meshes:
                    t_data = MeshProcessor.parse_obj_string(t_obj, name=f"Tail_{t_name}")
                    if t_data.vertex_count > 0:
                        assembled_builder.add_mesh(
                            positions=t_data.positions,
                            indices=t_data.indices,
                            normals=t_data.normals,
                            uvs=t_data.uvs,
                            material_index=tail_mat_idx,
                            name=f"Tail_{t_name}",
                            offset=self.ATTACHMENT_OFFSETS["tail"],
                        )

                # (3) Add Hair offset to Neck bone
                hair_mat_idx = None
                if hair_textures:
                    h_diff = next((img for name, img in hair_textures if "diff" in name.lower()), hair_textures[0][1])
                    hair_mat_idx = assembled_builder.add_texture_png(
                        MeshProcessor.pil_image_to_png_bytes(h_diff), name="Hair_Mat"
                    )
                for h_name, h_obj in hair_meshes:
                    h_data = MeshProcessor.parse_obj_string(h_obj, name=f"Hair_{h_name}")
                    if h_data.vertex_count > 0:
                        assembled_builder.add_mesh(
                            positions=h_data.positions,
                            indices=h_data.indices,
                            normals=h_data.normals,
                            uvs=h_data.uvs,
                            material_index=hair_mat_idx,
                            name=f"Hair_{h_name}",
                            offset=self.ATTACHMENT_OFFSETS["hair"],
                        )

                # (4) Add Face offset to Neck bone with multi-material expression mapping
                face_mat_cache: Dict[str, Optional[int]] = {}
                for f_name, f_obj in face_meshes:
                    f_data = MeshProcessor.parse_obj_string(f_obj, name=f"Face_{f_name}")
                    if f_data.vertex_count == 0:
                        continue

                    lower_f = f_name.lower()
                    feat_k = "face"
                    alpha_m = "OPAQUE"
                    if "eye" in lower_f:
                        feat_k = "eye"
                        alpha_m = "BLEND"
                    elif "mayu" in lower_f:
                        feat_k = "mayu"
                        alpha_m = "BLEND"
                    elif "mouth" in lower_f:
                        feat_k = "mouth"
                        alpha_m = "BLEND"
                    elif "cheek" in lower_f:
                        feat_k = "cheek"
                        alpha_m = "BLEND"

                    if feat_k not in face_mat_cache:
                        tex_im = face_tex_map.get(feat_k) or face_tex_map.get("face")
                        if tex_im:
                            png_b = MeshProcessor.pil_image_to_png_bytes(tex_im)
                            face_mat_cache[feat_k] = assembled_builder.add_texture_png(
                                png_b, name=f"Face_{feat_k.capitalize()}", alpha_mode=alpha_m
                            )
                        else:
                            face_mat_cache[feat_k] = None

                    assembled_builder.add_mesh(
                        positions=f_data.positions,
                        indices=f_data.indices,
                        normals=f_data.normals,
                        uvs=f_data.uvs,
                        material_index=face_mat_cache.get(feat_k),
                        name=f"Face_{f_name}",
                        offset=self.ATTACHMENT_OFFSETS["face"],
                    )

                assembled_path = out_dir / "assembled.glb"
                assembled_builder.export_glb(assembled_path)
                results["assembled"] = assembled_path

        return results
