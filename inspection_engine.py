import os
# pyrefly: ignore [missing-import]
import cv2
import time
from datetime import datetime
from typing import Optional, Tuple
import numpy as np
import camera_manager
from database_manager import DatabaseManager

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def load_master_contour(part_number: str) -> Optional[np.ndarray]:
    """Load the master contour/edge image for the given part number.

    Returns the grayscale master image, or None if not found.
    """
    master_path = os.path.join("masters", f"{part_number}_master.jpg")
    if not os.path.exists(master_path):
        print(f"Master contour not found: {master_path}")
        return None
    return cv2.imread(master_path, cv2.IMREAD_GRAYSCALE)


def process_frame(
    frame: np.ndarray,
    master: Optional[np.ndarray],
) -> Tuple[np.ndarray, str]:
    """Compare a live frame against the master contour and return the
    annotated frame together with a status string ('PASS' / 'FAIL').

    If no master is provided the frame is returned as-is with 'FAIL'.
    """
    if master is None:
        return frame, "FAIL — no master loaded"

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)

    if master.shape != edges.shape:
        master = cv2.resize(master, (edges.shape[1], edges.shape[0]))

    overlap = cv2.bitwise_and(master, edges)
    total = np.count_nonzero(edges) or 1
    score = np.count_nonzero(overlap) / total

    status = "PASS" if score >= 0.90 else "FAIL"
    color = (0, 255, 0) if status == "PASS" else (0, 0, 255)
    annotated = frame.copy()
    cv2.putText(annotated, f"{status} ({score*100:.1f}%)",
                (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
    return annotated, status


db = DatabaseManager()
def run_inspection(part_number: str = "UNKNOWN"):
   
    frame = camera_manager.get_latest_frame("cam1")

    if frame is None:
        print("No frame available")
        return False
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR, exist_ok=True)
    timestamp = int(time.time())
    filename = f"inspect_{part_number}_{timestamp}"
    image_path = os.path.join(UPLOAD_DIR, f"{filename}.jpg")
    master = load_master_contour(part_number)
    processed_frame, status_text = process_frame(frame, master)
    result = "PASS" if "PASS" in status_text else "FAIL"
    try:
        success = cv2.imwrite(image_path, processed_frame)
        if not success:
            print(f"Failed to save image to {image_path}")
            return False
        print(f"Image saved to {image_path}")
    except Exception as e:
        print(f"Error saving image: {e}")
        return False
    defect_type = "None" if result == "PASS" else "Geometric Mismatch"
    try:
        db_result = db.insert_inspection(
            data={
                "part_number": part_number,
                "image_name": filename + ".jpg", 
                "result": result,
                "defect_type": defect_type,
                "timestamp": datetime.now(),
                "ssim_score": None,
                "best_match": None,
                "location": "Station_1",
                "shifts": "Day"
            }
        )
        if db_result:
            print(f"Inspection stored in database (ID: {db_result})")
            return True
        else:
            print("Failed to store inspection in database")
            return False
    except Exception as e:
        print(f"Database error: {e}")
        return False
