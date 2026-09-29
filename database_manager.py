import os
import time
from datetime import datetime
from typing import Optional, Any, List, Dict, Tuple
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
import pyodbc

class DatabaseManager:
    def __init__(self):
        self.conn: Optional[pyodbc.Connection] = None
        self.conn_str = os.environ.get(
            "DATABASE_URL",
            (
                "DRIVER={SQL Server};"
                "SERVER=REVLGNDYSQL;"
                "DATABASE=inspection_db;"
                "UID=sa;"
                "PWD=Password@123;"
                "Encrypt=no;"
                "Trusted_Connection=no;"
                "TrustServerCertificate=yes;"
                "Connection Timeout=30;"
                "MARS_Connection=yes;"
            )
        )
        # Make sure the inspections table has every column insert_inspection()
        # writes to. Safe to run every startup — each ALTER is guarded by
        # COL_LENGTH so it's a no-op once the columns already exist.
        self.ensure_inspections_schema()

    def get_connection(self) -> Optional[pyodbc.Connection]:
        if self.conn:
            try:
                self.conn.cursor().execute("SELECT 1").fetchone()
                return self.conn
            except:
                self.conn = None

        try:
            self.conn = pyodbc.connect(self.conn_str, autocommit=False)
            print("[DB] Connected successfully.")
            return self.conn
        except Exception as e:
            print(f"[DB] Connection failed: {e}")
            time.sleep(1)
            return None

    def ensure_inspections_schema(self) -> None:
        """
        Adds any columns insert_inspection() relies on but that are missing
        from the live `inspections` table. Fixes the
        'Invalid column name Part_name/Location/Shifts/...' errors that
        occur when the table schema falls behind the application code.
        """
        required_columns = {
            "Inspection_id": "NVARCHAR(100) NULL",
            "Valve_type": "NVARCHAR(100) NULL",
            "Required_images": "INT NULL",
            "Captured_images": "INT NULL",
            "Status": "NVARCHAR(50) NULL",
            "Final_result": "NVARCHAR(50) NULL",
            "Part_name": "NVARCHAR(255) NULL",
            "Location": "NVARCHAR(100) NULL",
            "Shifts": "NVARCHAR(50) NULL",
            "Core_Hardness_stem": "FLOAT NULL",
            "Crown_Face_runout": "FLOAT NULL",
            "Datum_to_End": "FLOAT NULL",
            "End_Finish": "FLOAT NULL",
            "End_Radius": "FLOAT NULL",
            "Groove_Diameter": "FLOAT NULL",
            "Groove_Chamfer_Angle": "FLOAT NULL",
            "Head_Diameter": "FLOAT NULL",
            "Neck_Diameter": "FLOAT NULL",
            "Overall_Length": "FLOAT NULL",
            "Stem_Diameter": "FLOAT NULL",
            "Seat_Angle": "FLOAT NULL",
            "Surface_Hardness_Nitriding": "FLOAT NULL",
        }

        try:
            conn = pyodbc.connect(self.conn_str, autocommit=True)
        except Exception as e:
            print(f"[DB] ensure_inspections_schema: connection failed: {e}")
            return

        try:
            cursor = conn.cursor()
            for column, definition in required_columns.items():
                cursor.execute(
                    f"""
                    IF COL_LENGTH('inspections', ?) IS NULL
                        ALTER TABLE inspections ADD [{column}] {definition}
                    """,
                    (column,)
                )
            cursor.close()
            print("[DB] ensure_inspections_schema: OK (columns verified/added)")
        except Exception as e:
            print(f"[DB] ensure_inspections_schema ERROR: {e}")
        finally:
            conn.close()

    def check_connection(self) -> Tuple[bool, str]:
        conn = self.get_connection()
        if not conn:
            return False, "Connection Failed"
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT GETDATE()")
            row = cursor.fetchone()
            cursor.close()
            if row is None:
                return False, "No response from server"
            return True, f"Connected. Server Time: {row[0]}"
        except Exception as e:
            return False, f"Check failed: {e}"

    def get_part_name_from_details(self, part_number: str) -> Optional[str]:
        if not part_number:
            return None
        conn = self.get_connection()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            query = """
                SELECT [Part Name]
                FROM valve_details
                WHERE LTRIM(RTRIM([Part Number])) = ?
            """
            cursor.execute(query, (str(part_number).strip(),))
            row = cursor.fetchone()
            cursor.close()
            return row[0] if row is not None else None
        except Exception as e:
            print(f"[DB] get_part_name_from_details ERROR: {e}")
            return None

    def insert_inspection(self, data: Dict[str, Any]) -> Any:
        conn = self.get_connection()
        if not conn:
            print("[DB] No connection available")
            return False

        part_number = str(data.get("part_number", "")).strip()
        data["part_name"] = self.get_part_name_from_details(part_number) or "Unknown_Part"
        ts = data.get("timestamp")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", ""))
            except:
                try:
                    ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except:
                    ts = datetime.now()
        elif not isinstance(ts, datetime):
            ts = datetime.now()

        # force SQL-safe format
        ts = ts.strftime("%Y-%m-%d %H:%M:%S")

        numeric_columns = [
            "ssim_score", "Core_Hardness_stem", "Crown_Face_runout",
            "Datum_to_End", "End_Finish", "End_Radius", "Groove_Diameter",
            "Groove_Chamfer_Angle", "Head_Diameter", "Neck_Diameter",
            "Overall_Length", "Stem_Diameter", "Seat_Angle",
            "Surface_Hardness_Nitriding"
        ]
        for col in numeric_columns:
            val = data.get(col)
            if val is None or val == "":
                continue
            try:
                data[col] = float(val)
            except Exception:
                pass

        query = """
        INSERT INTO inspections (
            Part_number, Part_name, Image_name, ssim_score, Result,
            Best_match, Defect_type, Timestamp, Location, Shifts,
            Core_Hardness_stem, Crown_Face_runout, Datum_to_End,
            End_Finish, End_Radius, Groove_Diameter, Groove_Chamfer_Angle,
            Head_Diameter, Neck_Diameter, Overall_Length, Stem_Diameter,
            Seat_Angle, Surface_Hardness_Nitriding
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            data.get("part_number"),
            data.get("part_name"),
            data.get("image_name"),
            data.get("ssim_score"),
            data.get("result"),
            data.get("best_match"),
            data.get("defect_type"),
            ts,
            data.get("location"),
            data.get("shifts"),
            data.get("Core_Hardness_stem"),
            data.get("Crown_Face_runout"),
            data.get("Datum_to_End"),
            data.get("End_Finish"),
            data.get("End_Radius"),
            data.get("Groove_Diameter"),
            data.get("Groove_Chamfer_Angle"),
            data.get("Head_Diameter"),
            data.get("Neck_Diameter"),
            data.get("Overall_Length"),
            data.get("Stem_Diameter"),
            data.get("Seat_Angle"),
            data.get("Surface_Hardness_Nitriding"),
        )

        try:
            cursor = conn.cursor()
            print(f"[DB] ✓ Inserting inspection: part={data.get('part_number')}, result={data.get('result')}, ts={ts}")
            cursor.execute(query, params)
            conn.commit()
            cursor.execute("SELECT SCOPE_IDENTITY()")
            row = cursor.fetchone()
            cursor.close()
            inserted_id = row[0] if row is not None else True
            return inserted_id
        except Exception as e:
            print(f"[DB] insert_inspection ERROR: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return False

    def fetch_inspections(self, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None) -> pd.DataFrame:
        conn = self.get_connection()
        if not conn:
            return pd.DataFrame()

        query = "SELECT * FROM inspections WHERE 1=1"
        params = []
        if date_from:
            query += " AND [Timestamp] >= ?"
            params.append(date_from)
        if date_to:
            query += " AND [Timestamp] <= ?"
            params.append(date_to)
        query += " ORDER BY [Timestamp] DESC"

        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            cursor.close()
            return pd.DataFrame.from_records(rows, columns=columns)
        except Exception as e:
            print(f"[DB] fetch_inspections ERROR: {e}")
            return pd.DataFrame()

    def get_recent_inspections(self, limit: int = 10) -> List[Tuple[Any, ...]]:
        conn = self.get_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT TOP {limit} * FROM inspections ORDER BY [Timestamp] DESC")
            rows = cursor.fetchall()
            cursor.close()
            return [tuple(row) for row in rows]
        except Exception as e:
            print(f"[DB] get_recent_inspections ERROR: {e}")
            return []

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        if not conn:
            return None
        cur = conn.cursor()
        cur.execute("SELECT * FROM Users WHERE username=?", (username,))
        row = cur.fetchone()
        if not row:
            cur.close()
            return None
        cols = [c[0] for c in cur.description]
        cur.close()
        return dict(zip(cols, row))

    def create_user(self, username: str, password: str, role: str, location: str, ip: str) -> bool:
        conn = self.get_connection()
        if not conn:
            return False
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO Users (username,password_hash,role,location,allowed_ip) VALUES (?,?,?,?,?)",
            (username, generate_password_hash(password), role, location, ip)
        )
        conn.commit()
        cur.close()
        return True

    def approve_user(self, username: str) -> bool:
        conn = self.get_connection()
        if not conn:
            return False
        cur = conn.cursor()
        cur.execute("UPDATE Users SET is_active=1 WHERE username=?", (username,))
        conn.commit()
        cur.close()
        return True

    def get_pending_users(self) -> List[Tuple[Any, Any, Any]]:
        conn = self.get_connection()
        if not conn:
            return []
        cur = conn.cursor()
        cur.execute("SELECT username, location, role FROM Users WHERE is_active=0")
        rows = cur.fetchall()
        cur.close()
        return [tuple(row) for row in rows]

    def fetch_filtered_inspections(
        self,
        start_time: datetime,
        location: Optional[str] = None,
        shift: Optional[str] = None,
        part_number: Optional[str] = None
    ) -> pd.DataFrame:
        conn = self.get_connection()
        if not conn:
            return pd.DataFrame()

        cursor = conn.cursor()
        query = "SELECT * FROM inspections WHERE [timestamp] >= ?"
        params: List[Any] = [start_time]

        if location:
            query += " AND Location = ?"
            params.append(location)
        if shift:
            query += " AND Shifts = ?"
            params.append(shift)
        if part_number:
            query += " AND Part_number = ?"
            params.append(part_number)
        try:
            cursor=conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            cursor.close()
            return pd.DataFrame([dict(zip(columns, row)) for row in rows])
        except Exception as e:
            print(f"[DB] fetch_filtered_inspections ERROR: {e}")
            return pd.DataFrame()

    # 🔥 NEW FUNCTION (FOR REPORT)
    def get_inspection_by_id(self, id):
        conn = self.get_connection()
        if not conn:
            return None

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM inspections WHERE id = ?", (id,))
            row = cursor.fetchone()

            if not row:
                cursor.close()
                return None

            columns = [col[0] for col in cursor.description]
            data = dict(zip(columns, row))

            cursor.close()
            return data

        except Exception as e:
            print("[DB] get_inspection_by_id ERROR:", e)
            return None

    def get_dashboard_stats(self):
      empty = {
          "inspected": 0, "rejected": 0, "parts": 0, "pass_rate": 0,
          "inspected_total": 0, "rejected_total": 0, "parts_total": 0, "pass_rate_total": 0
      }
      try:
        conn = self.get_connection()

        if conn is None:
            return empty

        cursor = conn.cursor()

        # Today's stats
        cursor.execute("""
            SELECT
                COUNT(*) AS inspected,
                SUM(CASE
                        WHEN UPPER(ISNULL(Result,'')) IN ('PASS','OK','ACCEPT')
                        THEN 1 ELSE 0
                    END) AS passed,
                SUM(CASE
                        WHEN UPPER(ISNULL(Result,'')) IN ('FAIL','REJECT','REJECTED','NG')
                        THEN 1 ELSE 0
                    END) AS rejected,
                COUNT(DISTINCT Part_number) AS parts
            FROM inspections
            WHERE CAST([Timestamp] AS DATE)=CAST(GETDATE() AS DATE)
        """)
        row = cursor.fetchone()

        inspected = int(row[0] or 0) if row else 0
        passed = int(row[1] or 0) if row else 0
        rejected = int(row[2] or 0) if row else 0
        parts = int(row[3] or 0) if row else 0
        pass_rate = round((passed / inspected) * 100, 1) if inspected else 0

        # All-time stats
        cursor.execute("""
            SELECT
                COUNT(*) AS inspected,
                SUM(CASE
                        WHEN UPPER(ISNULL(Result,'')) IN ('PASS','OK','ACCEPT')
                        THEN 1 ELSE 0
                    END) AS passed,
                SUM(CASE
                        WHEN UPPER(ISNULL(Result,'')) IN ('FAIL','REJECT','REJECTED','NG')
                        THEN 1 ELSE 0
                    END) AS rejected,
                COUNT(DISTINCT Part_number) AS parts
            FROM inspections
        """)
        row_total = cursor.fetchone()
        cursor.close()

        inspected_total = int(row_total[0] or 0) if row_total else 0
        passed_total = int(row_total[1] or 0) if row_total else 0
        rejected_total = int(row_total[2] or 0) if row_total else 0
        parts_total = int(row_total[3] or 0) if row_total else 0
        pass_rate_total = round((passed_total / inspected_total) * 100, 1) if inspected_total else 0

        return {
            "inspected": inspected,
            "rejected": rejected,
            "parts": parts,
            "pass_rate": pass_rate,
            "inspected_total": inspected_total,
            "rejected_total": rejected_total,
            "parts_total": parts_total,
            "pass_rate_total": pass_rate_total
        }

      except Exception as e:
        print("Dashboard Stats Error:", e)
        return empty

db_manager = DatabaseManager()
connected, message = db_manager.check_connection()
print("[Connection Check]", message)