import pyodbc
import os

SERVER = "REVLGNDYSQL"
DATABASE = "inspection_db"
UID = "sa"
PWD = "Password@123"
DRIVER = "ODBC Driver 18 for SQL Server"

# Step 1: Connect to master and create the database if it doesn't exist
conn = pyodbc.connect(
    f"DRIVER={{{DRIVER}}};"
    f"SERVER={SERVER};"
    f"DATABASE=master;"
    f"UID={UID};"
    f"PWD={PWD};"
    "Encrypt=no;"
    "TrustServerCertificate=yes;",
    autocommit=True
)

cursor = conn.cursor()
cursor.execute("""
IF DB_ID('inspection_db') IS NULL
    CREATE DATABASE inspection_db
""")
conn.close()
print("✅ Database ready.")

# Step 2: Execute SQL scripts
scripts = [
    "sql/users_table.sql",
    "sql/inspections_table.sql",
    "sql/defects_details.sql",
    "sql/primarykey & foreignkey.sql",
    "sql/filter_database.sql",
    "sql/csv_file_adding.sql",
    "sql/total_rejected_countlast_3months.sql",
]

conn = pyodbc.connect(
    f"DRIVER={{{DRIVER}}};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    f"UID={UID};"
    f"PWD={PWD};"
    "Encrypt=no;"
    "TrustServerCertificate=yes;",
    autocommit=True
)

cursor = conn.cursor()

for path in scripts:
    if not os.path.exists(path):
        print(f"⚠️ SKIPPED (not found): {path}")
        continue

    print(f"▶ Running {path}...")

    with open(path, "r", encoding="utf-8-sig") as f:
        sql_text = f.read()

    # Split batches by GO
    batches = sql_text.replace("\r\n", "\n").split("\nGO\n")

    for batch in batches:
        batch = batch.strip()
        if not batch:
            continue

        try:
            cursor.execute(batch)
        except Exception as e:
            print(f"❌ ERROR in {path}")
            print(e)

    print(f"✅ Done: {path}")

conn.close()
print("🎉 All SQL scripts executed successfully.")