import cv2
import time
import os
import numpy as np
from camera_manager import start_camera_service, capture_frame
SAVE_FOLDER = r"D:\C102641-Data\copy_folder\Valve_Final_Inspection - Copy\static\uploads"
os.makedirs(SAVE_FOLDER, exist_ok=True)

DISPLAY_HEIGHT = 600
CAPTURE_INTERVAL = 10
MAX_IMAGES = 10

CANNY_LOW = 80
CANNY_HIGH = 180
THICKNESS = 5   
def cleanup_old_images(folder, max_images):
    imgs = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith('.jpg')]
    imgs.sort(key=os.path.getmtime)
    for img in imgs[:-max_images]:
        os.remove(img)
start_camera_service()
time.sleep(2)
print("Camera Started")

last_capture = 0

while True:
    frame = capture_frame()
    if frame is None:
        continue
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray_blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(gray_blur, 30, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        continue

    valve_cnt = max(contours, key=cv2.contourArea)
    valve_mask = np.zeros_like(mask)
    cv2.drawContours(valve_mask, [valve_cnt], -1, 255, -1)

    valve_gray = cv2.bitwise_and(gray_blur, gray_blur, mask=valve_mask)
    edges = cv2.Canny(valve_gray, CANNY_LOW, CANNY_HIGH)
    thick_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (THICKNESS, THICKNESS)
    )
    thick_edges = cv2.dilate(edges, thick_kernel, iterations=1)
    thick_edges = cv2.morphologyEx(
        thick_edges, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    )
    output = frame.copy()
    output[thick_edges > 0] = (0, 255, 0)

    scale = DISPLAY_HEIGHT / output.shape[0]
    output = cv2.resize(output, (int(output.shape[1] * scale), DISPLAY_HEIGHT))
    cv2.imshow("Thick Valve Edges", output)
    now = time.time()
    if now - last_capture >= CAPTURE_INTERVAL:
        cv2.imwrite(
            os.path.join(SAVE_FOLDER, f"valve_edge_{int(now * 1000)}.jpg"),
            output
        )
        cleanup_old_images(SAVE_FOLDER, MAX_IMAGES)
        last_capture = now

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()
