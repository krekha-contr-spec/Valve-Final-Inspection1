import os
import json
import hashlib
import cv2
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional


class StorageManager:
    """
    Manages traceable folder structure and metadata storage for valve inspections.
    
    Structure:
    inspections/
        YYYY/
            MM/
                DD/
                    INS-YYYYMMDD-XXXX/
                        metadata.json
                        camera_01/
                            image_01.jpg
                        camera_02/
                            image_02.jpg
                        results/
                            inspection_result.json
                            defects.json
    """

    def __init__(self, root_dir: Optional[str] = None):
        if root_dir is None:
            self.root_dir = os.path.join(os.getcwd(), "inspections")
        else:
            self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)

    def get_inspection_folder(self, inspection_id: str, timestamp: Optional[datetime] = None) -> str:
        if timestamp is None:
            timestamp = datetime.now()

        year = timestamp.strftime("%Y")
        month = timestamp.strftime("%m")
        day = timestamp.strftime("%d")

        folder_path = os.path.join(self.root_dir, year, month, day, inspection_id)
        os.makedirs(folder_path, exist_ok=True)
        return folder_path

    def init_inspection_storage(
        self,
        inspection_id: str,
        valve_type: str,
        required_images: int,
        positions: List[str],
        operator: str = "System Operator"
    ) -> str:
        now = datetime.now()
        folder = self.get_inspection_folder(inspection_id, now)

        # Create subdirectories
        os.makedirs(os.path.join(folder, "results"), exist_ok=True)

        metadata = {
            "inspection_id": inspection_id,
            "valve_type": valve_type,
            "required_images": required_images,
            "positions": positions,
            "operator": operator,
            "start_time": now.isoformat(),
            "end_time": None,
            "status": "INSPECTION_STARTED",
            "final_result": "PENDING",
            "captured_images": [],
            "defects": []
        }

        self.save_metadata(inspection_id, metadata, timestamp=now)
        return folder

    def save_metadata(self, inspection_id: str, metadata: Dict[str, Any], timestamp: Optional[datetime] = None) -> None:
        folder = self.get_inspection_folder(inspection_id, timestamp)
        meta_path = os.path.join(folder, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

    def load_metadata(self, inspection_id: str, timestamp: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        # If timestamp not provided, search for inspection_id folder
        if timestamp is not None:
            folder = self.get_inspection_folder(inspection_id, timestamp)
            meta_path = os.path.join(folder, "metadata.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return None

        # Search across date directories
        for root, dirs, files in os.walk(self.root_dir):
            if os.path.basename(root) == inspection_id:
                meta_path = os.path.join(root, "metadata.json")
                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as f:
                        return json.load(f)
        return None

    def calculate_image_hash(self, frame: np.ndarray) -> str:
        """Compute MD5 checksum of frame bytes to detect duplicate image captures."""
        return hashlib.md5(frame.tobytes()).hexdigest()

    def save_captured_image(
        self,
        inspection_id: str,
        camera_id: str,
        position: str,
        frame: np.ndarray,
        timestamp: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        if frame is None or frame.size == 0:
            return None

        if timestamp is None:
            timestamp = datetime.now()

        folder = self.get_inspection_folder(inspection_id, timestamp)
        cam_dir = os.path.join(folder, camera_id.lower().replace("-", "_"))
        os.makedirs(cam_dir, exist_ok=True)

        time_str = timestamp.strftime("%Y%m%d_%H%M%S_%f")
        image_id = f"IMG_{camera_id}_{position.upper()}_{time_str[:17]}"
        filename = f"{image_id}.jpg"
        file_path = os.path.join(cam_dir, filename)

        success = cv2.imwrite(file_path, frame)
        if not success:
            return None

        img_hash = self.calculate_image_hash(frame)
        rel_path = os.path.relpath(file_path, os.getcwd()).replace("\\", "/")

        img_meta = {
            "image_id": image_id,
            "inspection_id": inspection_id,
            "camera_id": camera_id,
            "image_position": position,
            "file_path": rel_path,
            "abs_path": file_path,
            "timestamp": timestamp.isoformat(),
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
            "image_hash": img_hash,
            "status": "VALID"
        }

        # Update metadata.json
        meta = self.load_metadata(inspection_id, timestamp)
        if meta:
            meta["captured_images"].append(img_meta)
            self.save_metadata(inspection_id, meta, timestamp)

        return img_meta

    def save_results(self, inspection_id: str, result_data: Dict[str, Any], defects_data: List[Dict[str, Any]], timestamp: Optional[datetime] = None) -> None:
        folder = self.get_inspection_folder(inspection_id, timestamp)
        results_dir = os.path.join(folder, "results")
        os.makedirs(results_dir, exist_ok=True)

        with open(os.path.join(results_dir, "inspection_result.json"), "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2)

        with open(os.path.join(results_dir, "defects.json"), "w", encoding="utf-8") as f:
            json.dump(defects_data, f, indent=2)


storage_manager = StorageManager()
