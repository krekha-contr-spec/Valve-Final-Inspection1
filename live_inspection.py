import cv2
import time
import os
import numpy as np
from camera_manager import start_camera_service, capture_frame
import re
BASE_DIR = os.path.dirname(__file__)
MASTER_DIR = os.path.join(BASE_DIR, "masters")
SAVE_FOLDER = os.path.join(BASE_DIR, "static/uploads")
os.makedirs(SAVE_FOLDER, exist_ok=True)
EDGE_LOW = 50
EDGE_HIGH = 150
EDGE_SIZE = (512, 512)      

OVERLAP_THRESHOLD = 0.90
TOLERANCE_PIXELS = 2
CAPTURE_INTERVAL = 3
def sanitize_filename(s):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', str(s))

def extract_edges(frame):
    
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, EDGE_LOW, EDGE_HIGH)
    return edges.astype(np.uint8)

def calculate_overlap(master, live):
  
    if master.shape != live.shape:
        live = cv2.resize(live, (master.shape[1], master.shape[0]))

    master = master.astype(np.uint8)
    live = live.astype(np.uint8)

    kernel = np.ones((TOLERANCE_PIXELS, TOLERANCE_PIXELS), np.uint8)
    master_dilated = cv2.dilate(master, kernel, iterations=1)

    overlap = cv2.bitwise_and(master_dilated, live)

    live_pixels = np.count_nonzero(live)
    if live_pixels == 0:
        return 0.0

    return np.count_nonzero(overlap) / live_pixels
PART_NUMBER = "48460"
MASTER_FILE = os.path.join(MASTER_DIR, f"{PART_NUMBER}_master.jpg")

if not os.path.exists(MASTER_FILE):
    raise FileNotFoundError(f"Master edge not found: {MASTER_FILE}")

master_edges = cv2.imread(MASTER_FILE, cv2.IMREAD_GRAYSCALE)
if master_edges is None:
    raise FileNotFoundError(f"Failed to load master edge image: {MASTER_FILE}")
master_edges = cv2.resize(master_edges, EDGE_SIZE)
master_edges = master_edges.astype(np.uint8)
start_camera_service()
time.sleep(2)
print("Valve Inspection Started | Press 'q' to quit")

last_capture = 0

try:
    while True:
        frame = capture_frame()
        if frame is None:
            continue
        live_edges_full = extract_edges(frame)
        live_edges_small = cv2.resize(live_edges_full, EDGE_SIZE)
        overlap = calculate_overlap(master_edges, live_edges_small)

        if overlap >= OVERLAP_THRESHOLD:
            status = "PASS"
            color = (0, 255, 0)
        else:
            status = "FAIL"
            color = (0, 0, 255)

        overlay = frame.copy()

        master_col = np.zeros_like(overlay)
        live_col = np.zeros_like(overlay)
        master_display = cv2.resize(
            master_edges,
            (overlay.shape[1], overlay.shape[0])
        )
        master_col[master_display > 0] = (255, 0, 0)  
        live_col[live_edges_full > 0] = (0, 255, 0)   

        overlay = cv2.addWeighted(overlay, 1, master_col, 0.8, 0)
        overlay = cv2.addWeighted(overlay, 1, live_col, 0.8, 0)
        cv2.putText(
            overlay,
            f"{status} ({overlap*100:.1f}%)",
            (30, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            color,
            3
        )

        cv2.imshow("Valve Edge Inspection", overlay)
        now = time.time()
        if now - last_capture >= CAPTURE_INTERVAL:
            cv2.imwrite(
                os.path.join(SAVE_FOLDER, f"inspection_{int(now * 1000)}.jpg"),
                overlay
            )
            last_capture = now

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    cv2.destroyAllWindows()
