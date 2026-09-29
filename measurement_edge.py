import cv2
import numpy as np
import pandas as pd
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VALVE_CSV_PATH = os.path.join(BASE_DIR, "Valve_Details.csv")  # Updated CSV path

if not os.path.exists(VALVE_CSV_PATH):
    raise FileNotFoundError(f"CSV file not found: {VALVE_CSV_PATH}")
df_valves = pd.read_csv(VALVE_CSV_PATH)
df_valves.columns = [c.strip() for c in df_valves.columns]  # Clean columns
def pixels_to_mm(pixels, dpi=96):
    mm_per_inch = 25.4
    return pixels * (mm_per_inch / dpi)


def detect_edges(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    return edges

def detect_and_measure_edges(frame, part_number):
    part_number = str(part_number)
    if part_number not in df_valves['Part Number'].astype(str).values:
        return frame, {}, f"Part number {part_number} not found"

    row = df_valves[df_valves['Part Number'].astype(str) == part_number].iloc[0]
    features_to_measure = {
        "End Radius": row.get('End Radius'),
        "Stem Diameter": row.get('Stem Diameter'),
        "Head Diameter": row.get('Head Diameter'),
        "Groove Diameter": row.get('Groove Diameter'),
    }

    if not features_to_measure:
        return frame, {}, "No features defined for this part"

    edges = detect_edges(frame)
    frame_overlay = frame.copy()
    height, width = edges.shape

    measurement_results = {}
    overall_pass = True

    for feature_name, tolerance_str in features_to_measure.items():
        if pd.isna(tolerance_str):
            measurement_results[feature_name] = "N/A"
            continue
        try:
            tol_str = str(tolerance_str).replace(" ", "")
            if "+/-" in tol_str:
                val, tol = map(float, tol_str.split("+/-"))
                min_val = val - tol
                max_val = val + tol
            elif "+" in tol_str and "-" in tol_str:
                val_str, rest = tol_str.split("+")
                val = float(val_str)
                plus_str, minus_str = rest.split("/")
                max_val = val + float(plus_str)
                min_val = val - float(minus_str)
            else:
                val = float(tol_str)
                min_val = max_val = val
        except Exception as e:
            measurement_results[feature_name] = f"Parse Error: {tolerance_str}"
            overall_pass = False
            continue
        measured_pixels = cv2.countNonZero(edges)
        measured_mm = pixels_to_mm(measured_pixels)

        status = "PASS" if min_val <= measured_mm <= max_val else "FAIL"
        if status == "FAIL":
            overall_pass = False

        measurement_results[feature_name] = {
            "measured_mm": round(measured_mm, 2),
            "expected_min": min_val,
            "expected_max": max_val,
            "status": status
        }
        cv2.putText(frame_overlay,
                    
                    f"{feature_name}: {status}",
                    (10, 30 + 30 * list(features_to_measure.keys()).index(feature_name)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0) if status == "PASS" else (0, 0, 255),
                    2)
    frame_overlay[edges != 0] = [0, 255, 255]  # yellow edges
    overall_status = "PASS" if overall_pass else "FAIL"
    cv2.putText(frame_overlay,
                f"Overall: {overall_status}",
                (10, height - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0) if overall_status == "PASS" else (0, 0, 255),
                3)

    return frame_overlay, measurement_results, overall_status

def save_inspection(frame, output_path):
    cv2.imwrite(output_path, frame)
