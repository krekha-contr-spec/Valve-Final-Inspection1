import os
import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Set
import numpy as np

from storage_manager import storage_manager

logger = logging.getLogger("inspection_session")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

ACTIVE_SESSION_FILE = os.path.join(os.getcwd(), "active_inspection.json")


class InspectionState:
    IDLE = "IDLE"
    INSPECTION_STARTED = "INSPECTION_STARTED"
    CAPTURING = "CAPTURING"
    IMAGE_VALIDATION = "IMAGE_VALIDATION"
    INSPECTION_COMPLETE = "INSPECTION_COMPLETE"
    DEFECT_ANALYSIS = "DEFECT_ANALYSIS"
    FINAL_DECISION = "FINAL_DECISION"
    SAVED = "SAVED"
    READY_FOR_NEXT_OBJECT = "READY_FOR_NEXT_OBJECT"
    ERROR = "ERROR"


def load_config() -> Dict[str, Any]:
    config_path = os.path.join(os.getcwd(), "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading config.json: {e}")
    
    # Default fallback config
    return {
        "valve_types": {
            "Gate Valve": {
                "required_images": 7,
                "positions": ["Front", "Back", "Left", "Right", "Top", "Bottom", "Marking"]
            },
            "Ball Valve": {
                "required_images": 5,
                "positions": ["Front", "Back", "Side", "Top", "Bottom"]
            }
        }
    }


def generate_inspection_id() -> str:
    """Generate a unique ID formatted as INS-YYYYMMDD-XXXX."""
    date_str = datetime.now().strftime("%Y%m%d")
    seq_file = os.path.join(os.getcwd(), ".inspection_sequence.json")
    seq = 1

    with threading.Lock():
        if os.path.exists(seq_file):
            try:
                with open(seq_file, "r") as f:
                    data = json.load(f)
                    if data.get("date") == date_str:
                        seq = data.get("seq", 0) + 1
            except Exception:
                pass
        
        with open(seq_file, "w") as f:
            json.dump({"date": date_str, "seq": seq}, f)

    return f"INS-{date_str}-{seq:04d}"


class InspectionSessionManager:
    """Central Manager for Valve Final Inspection Sessions."""

    def __init__(self):
        self.lock = threading.Lock()
        self.config = load_config()
        self.active_session: Optional[Dict[str, Any]] = None
        self._load_persisted_active_session()

    def _load_persisted_active_session(self):
        """Recover active session state if application restarted mid-inspection."""
        if os.path.exists(ACTIVE_SESSION_FILE):
            try:
                with open(ACTIVE_SESSION_FILE, "r", encoding="utf-8") as f:
                    session_data = json.load(f)
                    if session_data and session_data.get("state") not in [InspectionState.SAVED, InspectionState.IDLE]:
                        self.active_session = session_data
                        logger.warning(f"Incomplete inspection session recovered: {session_data.get('inspection_id')}")
            except Exception as e:
                logger.error(f"Failed to load active inspection session file: {e}")

    def persist_active_session(self):
        with self.lock:
            if self.active_session:
                try:
                    with open(ACTIVE_SESSION_FILE, "w", encoding="utf-8") as f:
                        json.dump(self.active_session, f, indent=2)
                except Exception as e:
                    logger.error(f"Failed to persist active inspection session: {e}")
            elif os.path.exists(ACTIVE_SESSION_FILE):
                try:
                    os.remove(ACTIVE_SESSION_FILE)
                except Exception:
                    pass

    def get_valve_config(self, valve_type: str) -> Dict[str, Any]:
        self.config = load_config()
        valve_types = self.config.get("valve_types", {})
        if valve_type in valve_types:
            return valve_types[valve_type]

        # Default fallback if unknown valve type
        return {
            "required_images": 7,
            "positions": ["Front", "Back", "Left", "Right", "Top", "Bottom", "Marking"]
        }

    def start_new_session(self, valve_type: str, operator: str = "Operator") -> Dict[str, Any]:
        with self.lock:
            if self.active_session and self.active_session.get("state") not in [InspectionState.SAVED, InspectionState.IDLE]:
                logger.warning(f"Session {self.active_session['inspection_id']} is still active!")
                return self.active_session

            inspection_id = generate_inspection_id()
            valve_cfg = self.get_valve_config(valve_type)
            required_images = valve_cfg.get("required_images", 7)
            positions = valve_cfg.get("positions", [])

            self.active_session = {
                "inspection_id": inspection_id,
                "valve_type": valve_type,
                "operator": operator,
                "required_images": required_images,
                "positions": positions,
                "captured_images": [],
                "image_hashes": [],
                "state": InspectionState.INSPECTION_STARTED,
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "final_result": "PENDING",
                "defects": []
            }

            storage_manager.init_inspection_storage(
                inspection_id=inspection_id,
                valve_type=valve_type,
                required_images=required_images,
                positions=positions,
                operator=operator
            )

        self.persist_active_session()
        logger.info(f"Started new inspection session: {inspection_id} for {valve_type} ({required_images} images required)")
        return self.active_session

    def get_next_required_position(self) -> Optional[str]:
        if not self.active_session:
            return None
        captured_positions = {img.get("image_position") for img in self.active_session.get("captured_images", [])}
        for pos in self.active_session.get("positions", []):
            if pos not in captured_positions:
                return pos
        return None

    def validate_captured_frame(self, frame: np.ndarray, inspection_id: str, camera_id: str, position: str) -> Tuple[bool, str]:
        """Validate frame dimensions, non-emptiness, and duplicate protection."""
        if not self.active_session:
            return False, "No active inspection session"

        if self.active_session["inspection_id"] != inspection_id:
            return False, f"Inspection ID mismatch (active: {self.active_session['inspection_id']}, received: {inspection_id})"

        if frame is None or frame.size == 0:
            return False, "Empty or None frame"

        if len(frame.shape) < 2 or frame.shape[0] <= 0 or frame.shape[1] <= 0:
            return False, "Invalid frame dimensions"

        # Check duplicate image hash
        img_hash = storage_manager.calculate_image_hash(frame)
        if img_hash in self.active_session.get("image_hashes", []):
            return False, "Duplicate image capture detected"

        return True, "Valid"

    def record_captured_image(
        self,
        inspection_id: str,
        camera_id: str,
        position: str,
        frame: np.ndarray
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        with self.lock:
            if not self.active_session:
                return False, "No active inspection session", None

            valid, msg = self.validate_captured_frame(frame, inspection_id, camera_id, position)
            if not valid:
                logger.warning(f"Image capture rejected: {msg}")
                return False, msg, None

            self.active_session["state"] = InspectionState.CAPTURING

            img_meta = storage_manager.save_captured_image(
                inspection_id=inspection_id,
                camera_id=camera_id,
                position=position,
                frame=frame
            )

            if not img_meta:
                return False, "Failed to save image file", None

            self.active_session["captured_images"].append(img_meta)
            self.active_session["image_hashes"].append(img_meta["image_hash"])
            self.active_session["state"] = InspectionState.IMAGE_VALIDATION

            # Check if all required images captured
            complete, comp_msg = self.is_inspection_complete_internal(inspection_id)
            if complete:
                self.active_session["state"] = InspectionState.INSPECTION_COMPLETE

        self.persist_active_session()
        return True, "Success", img_meta

    def is_inspection_complete_internal(self, inspection_id: str) -> Tuple[bool, str]:
        """Internal helper for checking completion under lock."""
        if not self.active_session or self.active_session["inspection_id"] != inspection_id:
            return False, "Session not active"

        required_count = self.active_session.get("required_images", 7)
        required_positions = set(self.active_session.get("positions", []))

        captured_images = self.active_session.get("captured_images", [])
        valid_captured = [img for img in captured_images if img.get("status") == "VALID" and os.path.exists(img.get("abs_path", ""))]

        captured_positions = {img.get("image_position") for img in valid_captured}

        if len(valid_captured) < required_count:
            return False, f"Captured {len(valid_captured)} of {required_count} required images"

        missing_positions = required_positions - captured_positions
        if missing_positions:
            return False, f"Missing required position views: {', '.join(missing_positions)}"

        return True, "All required inspection images captured and validated"

    def is_inspection_complete(self, inspection_id: str) -> Tuple[bool, str]:
        """Public central function to check if inspection object is fully captured and ready for final decision."""
        with self.lock:
            return self.is_inspection_complete_internal(inspection_id)

    def finalize_inspection(self, defect_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute final ACCEPTED / REJECTED decision, save results, and reset for next object."""
        with self.lock:
            if not self.active_session:
                raise RuntimeError("No active session to finalize")

            inspection_id = self.active_session["inspection_id"]
            complete, msg = self.is_inspection_complete_internal(inspection_id)
            if not complete:
                raise RuntimeError(f"Cannot finalize incomplete inspection: {msg}")

            self.active_session["state"] = InspectionState.DEFECT_ANALYSIS
            self.active_session["defects"] = defect_results

            # Decision Logic: If any defect found or critical defect present → REJECTED
            critical_defects = [d for d in defect_results if d.get("defect_type") not in ["None", "No_Defect"]]
            final_result = "REJECTED" if len(critical_defects) > 0 else "ACCEPTED"

            self.active_session["final_result"] = final_result
            self.active_session["state"] = InspectionState.FINAL_DECISION
            self.active_session["end_time"] = datetime.now().isoformat()

            # Save results to traceable storage
            result_summary = {
                "inspection_id": inspection_id,
                "valve_type": self.active_session["valve_type"],
                "required_images": self.active_session["required_images"],
                "captured_images_count": len(self.active_session["captured_images"]),
                "final_result": final_result,
                "start_time": self.active_session["start_time"],
                "end_time": self.active_session["end_time"],
                "operator": self.active_session["operator"]
            }

            storage_manager.save_results(inspection_id, result_summary, defect_results)
            self.active_session["state"] = InspectionState.SAVED

            finalized_session = self.active_session.copy()

            # Remove persisted active session file
            if os.path.exists(ACTIVE_SESSION_FILE):
                try:
                    os.remove(ACTIVE_SESSION_FILE)
                except Exception:
                    pass

            self.active_session = None

        logger.info(f"Finalized inspection {inspection_id}: Result = {final_result}")
        return finalized_session

    def reset_or_recover(self, action: str = "discard") -> bool:
        with self.lock:
            if action == "discard":
                self.active_session = None
                if os.path.exists(ACTIVE_SESSION_FILE):
                    try:
                        os.remove(ACTIVE_SESSION_FILE)
                    except Exception:
                        pass
                return True
        return False

    def get_current_status(self) -> Dict[str, Any]:
        with self.lock:
            if not self.active_session:
                return {
                    "active": False,
                    "state": InspectionState.IDLE,
                    "inspection_id": None,
                    "required_images": 0,
                    "captured_count": 0,
                    "progress_pct": 0,
                    "next_required_position": None
                }

            captured_images = self.active_session.get("captured_images", [])
            valid_captured = [img for img in captured_images if img.get("status") == "VALID"]
            req_count = self.active_session.get("required_images", 7)
            cap_count = len(valid_captured)
            pct = int((cap_count / req_count) * 100) if req_count > 0 else 0

            # Find next required position
            captured_positions = {img.get("image_position") for img in valid_captured}
            next_pos = None
            for pos in self.active_session.get("positions", []):
                if pos not in captured_positions:
                    next_pos = pos
                    break

            return {
                "active": True,
                "state": self.active_session.get("state"),
                "inspection_id": self.active_session.get("inspection_id"),
                "valve_type": self.active_session.get("valve_type"),
                "required_images": req_count,
                "captured_count": cap_count,
                "progress_pct": min(100, pct),
                "next_required_position": next_pos,
                "positions": self.active_session.get("positions", []),
                "captured_images": valid_captured,
                "final_result": self.active_session.get("final_result", "PENDING")
            }


session_manager = InspectionSessionManager()
