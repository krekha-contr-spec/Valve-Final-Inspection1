import cv2
import numpy as np
import os
import time
import uuid
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from camera_manager import (
    start_camera_service,
    stop_camera_service,
    get_latest_frame
)

from database_manager import db_manager
from utils import cleanup_uploads



CAMERAS = {
    "cam1": 0,
    "cam2": 1,
    "cam3": 2
}

# Capture exactly one set of synchronized images per inspection cycle
CAPTURE_PER_INSPECTION = 1

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SAVE_ROOT = os.path.join(BASE_DIR, "static", "uploads")
OBJECT_FOLDER_LOCK = threading.Lock()


def analyze_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edge_ratio = np.sum(edges > 0) / (gray.shape[0] * gray.shape[1])

    return "Surface_Damage" if edge_ratio < 0.02 else "No_Defect"


def wait_for_all_cameras(timeout=20):
    start = time.time()

    while time.time() - start < timeout:
        if all(get_latest_frame(cam_id) is not None for cam_id in CAMERAS):
            return True
        time.sleep(0.2)

    return False


def create_object_folder(object_id):
    object_folder = os.path.join(SAVE_ROOT, object_id)
    with OBJECT_FOLDER_LOCK:
        os.makedirs(object_folder, exist_ok=True)
    return object_folder


def capture_from_camera(cam_id, folder, object_id, capture_timestamp):
    frame = get_latest_frame(cam_id)

    if frame is None:
        return None

    unique_id = uuid.uuid4().hex[:8]
    filename = f"{object_id}_{cam_id}_{capture_timestamp}_{unique_id}.jpg"
    filepath = os.path.join(folder, filename)

    cv2.imwrite(filepath, frame)

    result = analyze_image(frame)

    return {
        "filename": f"{object_id}/{filename}",
        "result": result
    }


def run_inspection(object_id):
    os.makedirs(SAVE_ROOT, exist_ok=True)
    object_folder = create_object_folder(object_id)

    for cam_id, idx in CAMERAS.items():
        start_camera_service(cam_id, idx)

    if not wait_for_all_cameras():
        for cam_id in CAMERAS:
            stop_camera_service(cam_id)
        return False

    all_results = []
    capture_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    for count in range(1, CAPTURE_PER_INSPECTION + 1):
        with ThreadPoolExecutor(max_workers=len(CAMERAS)) as executor:
            futures = [
                executor.submit(
                    capture_from_camera,
                    cam_id,
                    object_folder,
                    object_id,
                    capture_timestamp
                )
                for cam_id in CAMERAS
            ]

            for future in futures:
                data = future.result()

                if data:
                    all_results.append(data["result"])
                    db_manager.insert_inspection({
                        "part_number": object_id,
                        "image_name": data["filename"],
                        "ssim_score": 0.95,
                        "result": data["result"],
                        "best_match": "Live Camera",
                        "defect_type": data["result"],
                        "timestamp": datetime.now()
                    })

        time.sleep(0.1)

    for cam_id in CAMERAS:
        stop_camera_service(cam_id)

    if not all_results:
        return False

    # Clean up older inspection folders/images to keep total images below 10
    cleanup_uploads(SAVE_ROOT, max_images=10)

    return "Rejected" if "Surface_Damage" in all_results else "Accepted"