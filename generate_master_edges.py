import cv2
import numpy as np
import pandas as pd
import os
import re

MASTER_DIR = "masters"
os.makedirs(MASTER_DIR, exist_ok=True)

IMG_W, IMG_H = 1024, 1024
PIXELS_PER_MM = 8

def extract_number(val):
    if pd.isna(val): return 0.0
    match = re.search(r"[-+]?\d*\.?\d+", str(val))
    return float(match.group()) if match else 0.0

def sanitize_filename(s):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', str(s))

default_excel = os.path.join(os.getcwd(), "Valve_Details.xlsx")
default_csv = os.path.join(os.getcwd(), "Valve_Details.csv")

if os.path.exists(default_excel):
    df = pd.read_excel(default_excel)
elif os.path.exists(default_csv):
    df = pd.read_csv(default_csv)
else:
    raise FileNotFoundError("Neither Valve_Details.xlsx nor Valve_Details.csv found in workspace root")

df.columns = [re.sub(r'[^a-z0-9]+', '_', str(c).strip().lower()) for c in df.columns]
print("Found Columns:", df.columns.tolist())
COL_PART = "part_number"
COL_HEAD = "crown_face_radius_width" if "crown_face_radius_width" in df.columns else "profile_radius"
COL_STEM = "neck_diameter"
COL_LEN  = "overall_length"
required_cols = [COL_PART, COL_HEAD, COL_STEM, COL_LEN]
missing = [c for c in required_cols if c not in df.columns]

if missing:
    print(f"Error: Missing columns {missing}")
    print("Ensure your Excel has: part_number, crown_face_radius_width, neck_diameter, and overall_length")
    exit()

df = df.dropna(subset=[COL_PART])
for _, row in df.iterrows():
    part_no = sanitize_filename(row[COL_PART])
    h_dia = extract_number(row[COL_HEAD])
    s_dia = extract_number(row[COL_STEM])
    o_len = extract_number(row[COL_LEN])
    head_r = (h_dia * PIXELS_PER_MM) / 2
    stem_r = (s_dia * PIXELS_PER_MM) / 2
    total_len = o_len * PIXELS_PER_MM
    head_h = max(20, total_len * 0.1) 
    canvas = np.zeros((IMG_H, IMG_W), dtype=np.uint8)
    cx, cy = IMG_W // 2, IMG_H - 100 
    points = [
        [cx + stem_r, cy],                              
        [cx + stem_r, cy - (total_len - head_h)],        
        [cx + head_r, cy - (total_len - head_h/2)],      
        [cx + head_r, cy - total_len],                   
        [cx - head_r, cy - total_len],                   
        [cx - head_r, cy - (total_len - head_h/2)],      
        [cx - stem_r, cy - (total_len - head_h)],        
        [cx - stem_r, cy]                                
    ]
    pts = np.array(points, np.int32).reshape((-1, 1, 2))
    cv2.polylines(canvas, [pts], isClosed=True, color=(255,), thickness=2)

    save_path = os.path.join(MASTER_DIR, f"{part_no}_master.jpg")
    cv2.imwrite(save_path, canvas)
    print(f"Created Master: {part_no}_master.jpg")