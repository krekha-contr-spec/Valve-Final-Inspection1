import os
import json
import pandas as pd
from tkinter import Tk, filedialog

# Hide the Tkinter window
root = Tk()
root.withdraw()

# Ask the user to select the Valve_Final_Inspection folder
BASE_DIR = filedialog.askdirectory(
    title="Select Valve_Final_Inspection Folder"
)

if not BASE_DIR:
    print("No folder selected.")
    exit(1)

# File paths
VALVE_CSV_FILE = os.path.join(BASE_DIR, "Valve_Details.csv")
MASTER_FILE = os.path.join(BASE_DIR, "trained_data", "valve_master.json")

# Create trained_data folder if it doesn't exist
os.makedirs(os.path.dirname(MASTER_FILE), exist_ok=True)

# Read CSV
try:
    valve_data = pd.read_csv(VALVE_CSV_FILE)
    print("CSV Loaded successfully!")
except FileNotFoundError:
    print(f"Error: CSV file not found at:\n{VALVE_CSV_FILE}")
    exit(1)
except Exception as e:
    print(f"Error reading CSV: {e}")
    exit(1)

# Preview
print("\nPreview of CSV data:")
print(valve_data.head())

# Convert CSV to JSON
master_data = {
    "valves": valve_data.to_dict(orient="records")
}

# Save JSON
try:
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(master_data, f, indent=4)

    print(f"\nMaster JSON saved successfully at:\n{MASTER_FILE}")

except Exception as e:
    print(f"Error saving JSON: {e}")
    exit(1)

# Verify JSON
try:
    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        loaded_data = json.load(f)

    print("\nJSON loaded successfully.")
    print("Number of valves:", len(loaded_data["valves"]))

except Exception as e:
    print(f"Error loading JSON: {e}")