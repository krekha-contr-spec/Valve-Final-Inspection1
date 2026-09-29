import os 
import logging
import io
import threading
import time
import uuid
import camera_manager
import cv2
import numpy as np
import json
from PIL import Image
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from flask_cors import CORS
from flask import Flask, Response, render_template, flash, request, session, redirect, jsonify, url_for, send_file, abort
from flask import send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash
from database_manager import db_manager
from workflow_engine import run_workflow
from report_generated import generate_daily_report
from report_scheduler import start_scheduler
from report_pdf_download.pdf_generator import generate_inspection_pdf
from image_processing import process_image_web, detect_edges, pixels_to_mm
from utils import ensure_part_folder, normalize_part_number, create_inspection_folder, get_next_image_name
from functools import wraps
from flask_apscheduler import APScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from measurement_edge import detect_and_measure_edges, save_inspection
from camera_together import wait_for_all_cameras, capture_from_camera, run_inspection as run_multi_camera_inspection
from inspection_session import session_manager, InspectionState
from storage_manager import storage_manager
from contextlib import contextmanager
_db_lock = threading.Lock()


def get_shift_from_time(dt: Optional[datetime] = None) -> str:
    """
    Derive the correct shift from a datetime (defaults to now).
    Operator UI selections are intentionally IGNORED — shift is always
    calculated from the actual timestamp so DB records and reports are
    always correct even if an operator accidentally picks the wrong shift.

    Shift A : 06:30 – 14:30
    Shift B : 14:30 – 22:30
    Shift C : 22:30 – 06:30 (overnight)
    """
    t = (dt or datetime.now()).time()
    if datetime.strptime("06:30", "%H:%M").time() <= t < datetime.strptime("14:30", "%H:%M").time():
        return "Shift A"
    elif datetime.strptime("14:30", "%H:%M").time() <= t < datetime.strptime("22:30", "%H:%M").time():
        return "Shift B"
    else:
        return "Shift C"


@contextmanager
def db_cursor():
    with _db_lock:
        conn = db_manager.get_connection()
        if conn is None:
            yield None, None
            return
        cursor = conn.cursor()
        try:
            yield conn, cursor
        finally:
            try:
                cursor.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


# ============ INSPECTION MANAGER CLASS ============
class InspectionManager:
    """Manages inspection state and operations."""
    
    def __init__(self):
        self.inspection_thread = None
        self.inspection_callback = None
        self.running = False
        self.paused = False
        self.inspection_data = {
            "inspection_folder": None,
            "total_inspections": 0,
            "passed": 0,
            "failed": 0,
            "selected_part_number": None,
            "current_part": None,
        }
        self.lock = threading.Lock()
    
    def start_inspection(self, callback, folder_prefix=None):
        """Start an inspection with the given callback function."""
        with self.lock:
            if self.running:
                return False
            
            self.running = True
            self.paused = False
            self.inspection_callback = callback
            self.inspection_data["total_inspections"] = 0
            self.inspection_data["passed"] = 0
            self.inspection_data["failed"] = 0
            self.inspection_data["inspection_folder"] = create_inspection_folder(folder_prefix) if folder_prefix else None
            
            self.inspection_thread = threading.Thread(target=self._run_inspection, daemon=True)
            self.inspection_thread.start()
            return True
    
    def _run_inspection(self):
        """Internal method to run the inspection callback."""
        try:
            if self.inspection_callback:
                self.inspection_callback()
        finally:
            with self.lock:
                self.running = False
                self.paused = False
    
    def stop_inspection(self):
        """Stop the running inspection."""
        with self.lock:
            if not self.running:
                return False
            self.running = False
            self.paused = False
            return True
    
    def pause_inspection(self):
        """Pause the running inspection."""
        with self.lock:
            if not self.running or self.paused:
                return False
            self.paused = True
            return True
    
    def resume_inspection(self):
        """Resume a paused inspection."""
        with self.lock:
            if not self.running or not self.paused:
                return False
            self.paused = False
            return True
    
    def should_continue(self):
        """Check if inspection should continue."""
        with self.lock:
            return self.running and not self.paused
    
    def update_status(self, **kwargs):
        """Update inspection status with provided fields."""
        with self.lock:
            for key, value in kwargs.items():
                if key in self.inspection_data:
                    self.inspection_data[key] = value
    
    def get_status(self):
        """Get the current inspection status."""
        with self.lock:
            return {
                "running": self.running,
                "paused": self.paused,
                "total_inspections": self.inspection_data["total_inspections"],
                "passed": self.inspection_data["passed"],
                "failed": self.inspection_data["failed"],
                "selected_part_number": self.inspection_data["selected_part_number"],
                "current_part": self.inspection_data["current_part"],
                "inspection_folder": self.inspection_data["inspection_folder"],
            }


# Global inspection manager instance
inspection_manager = InspectionManager()


try:
    import camera_manager
    from camera_manager import (
        start_camera_service,
        stop_camera_service,
        get_latest_frame,
    
    )
    CAMERA_AVAILABLE = True

except ImportError:
    print("Camera module not available. Running without camera.")
    CAMERA_AVAILABLE = False

    def start_camera_service(*args, **kwargs) -> bool: return False
    def stop_camera_service(*args, **kwargs): pass
    def get_latest_frame(*args, **kwargs) -> Optional[np.ndarray]:
        return None
    def cam_set_exposure(*args, **kwargs): pass
    def cam_set_gain(*args, **kwargs): pass
    def cam_set_trigger(*args, **kwargs): pass
    def cam_software_trigger(*args, **kwargs): pass
    def camera_capture_frame(*args, **kwargs) -> Optional[np.ndarray]:
        return None

UPLOAD_FOLDER = os.path.join("static", "uploads")
TRAINED_IMAGES_FOLDER = os.path.join(
    "static",
    "Golden Libraries",
    "GoldenLibrary"
)
DEFECT_FOLDER = os.path.join(
    "static",
    "Golden Libraries",
    "DefectLibrary"
)
INSPECTION_PDF_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "inspection_pdf")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'jfif'}
SESSION_TIMEOUT = 2  

last_daily_notification = {"message": None, "timestamp": None}
last_live_result = {
    "component": None,
    "ssim_score": None,
    "status": None,
    "image_name": None,
    "timestamp": None,
} 
accepted_count = 0
rejected_count = 0
INSPECTIONS = []
inspection_running = False
 
def _get_or_create_object_folder(active_part_number: str) -> str:
    """
    Return the inspection folder path for the object currently open in
    this session. Reuses the existing folder as long as the same object
    (same part number, folder still present on disk) is still open.
    """
    current_folder_name = session.get("current_object_folder")
    current_part = session.get("current_object_part_number")

    if (
        current_folder_name
        and current_part == active_part_number
        and os.path.isdir(os.path.join(UPLOAD_FOLDER, current_folder_name))
    ):
        return os.path.join(UPLOAD_FOLDER, current_folder_name)

    # No open object folder for this part (new object, first capture,
    # or the part number changed) -> start a fresh folder.
    inspection_folder_path = create_inspection_folder(UPLOAD_FOLDER, prefix=active_part_number)
    session["current_object_folder"] = os.path.basename(inspection_folder_path)
    session["current_object_part_number"] = active_part_number
    return inspection_folder_path


def _close_current_object_folder() -> Optional[str]:
    """Close out the currently open object folder, if any, and return its name."""
    closed_folder = session.pop("current_object_folder", None)
    session.pop("current_object_part_number", None)
    return closed_folder


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr)

def is_ip_allowed(client_ip: Optional[str], allowed_ips: Optional[str]) -> bool:
    if not client_ip or not allowed_ips:
        return False
    allowed_list = [ip.strip() for ip in allowed_ips.split(",")]
    return client_ip in allowed_list

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash("Please log in to access this page", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def create_app():
    try:
        app = Flask(__name__, template_folder="templates", static_folder="static")
        app.secret_key = os.environ.get("SESSION_SECRET", "valve-inspection-secret-key")
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
        app.config['SESSION_COOKIE_SECURE'] = False
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        CORS(app)
        
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(TRAINED_IMAGES_FOLDER, exist_ok=True)
        os.makedirs(DEFECT_FOLDER, exist_ok=True)
        os.makedirs(INSPECTION_PDF_FOLDER, exist_ok=True)

        app.config["CAMERA_INITIALIZED"] = False
        app.config["CAMERA_STATUS"] = {"software_open": False, "running": False}

        scheduler = BackgroundScheduler()
        scheduler.start()
        start_scheduler(app)

        logging.basicConfig(level=logging.INFO)
        
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

        @app.after_request
        def add_no_cache_headers(response):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
        
        @app.before_request
        def session_management():
            session.permanent = True
            now = datetime.now()
            if 'user' in session:
                last_activity = session.get('last_activity')
                if last_activity:
                    last_time = datetime.strptime(last_activity, "%Y-%m-%d %H:%M:%S")
                    if now - last_time > timedelta(hours=SESSION_TIMEOUT):
                        session.pop('user', None)
                        session.pop('last_activity', None)
                        flash("You have been logged out due to inactivity.", "info")
                        return redirect(url_for('login'))
                session['last_activity'] = now.strftime("%Y-%m-%d %H:%M:%S")

        def get_requested_part_number():
            part_number = None
            if request.method in ("POST", "PUT", "PATCH"):
                try:
                    data = request.get_json(silent=True) or {}
                except Exception:
                    data = {}
                part_number = data.get("part_number") if isinstance(data, dict) else None
                if not part_number:
                    part_number = request.form.get("part_number")
            else:
                part_number = request.args.get("part_number")

            if not part_number:
                part_number = session.get("selected_part_number") or session.get("part_number")

            part_number = normalize_part_number(part_number)
            if part_number:
                session["selected_part_number"] = part_number
            return part_number

        def daily_notification():
            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        app.logger.warning("No DB connection for daily notification")
                        return

                    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    cursor.execute(
                        "SELECT COUNT(*) FROM inspections WHERE Result = 'Rejected' AND [timestamp] >= ?",
                        (today,)
                    )
                    row = cursor.fetchone()
                    rejection_count = row[0] if row else 0

                    global last_daily_notification
                    last_daily_notification = {
                        "message": f"Check Maximum Defects. Please review.",
                        "timestamp": datetime.now()
                    }
                    app.logger.info("Daily notification triggered")

            except Exception as e:
                app.logger.error(f"Daily notification failed: {str(e)}")

        scheduler.add_job(
            daily_notification,
            'interval',
            minutes=30,
            id="daily_job"
        )

        @app.route("/")
        def login_page():
            return render_template("login.html")

        @app.route('/favicon.ico')
        def favicon():
            return '', 204

        @app.route("/login", methods=["GET", "POST"])
        def login():
            if request.method == "POST":
                username = (request.form.get("username") or "").strip()
                password = (request.form.get("password") or "").strip()
                ip = get_client_ip()
                
                if not username or not password:
                    flash("Username and password required", "error")
                    return redirect("/login")
                
                if username == "admin" and password == "12345":
                    session.update({
                        "user": "admin",
                        "role": "ADMIN",
                        "location": "ALL",
                        "ip": ip
                    })
                    return redirect("/home")
                
                user = db_manager.get_user(username)
                if not user:
                    flash("Invalid username", "error")
                    return redirect("/login")

                if not user.get("is_active"):
                    flash("Waiting for admin approval", "warning")
                    return redirect("/login")

                if user.get("allowed_ip") and user["allowed_ip"] != ip:
                    flash("Login not allowed from this IP", "error")
                    return redirect("/login")

                if not check_password_hash(user["password_hash"], password):
                    flash("Invalid password", "error")
                    return redirect("/login")

                session.update({
                    "user": username,
                    "role": user["role"],
                    "location": user["location"],
                    "ip": ip
                })
                return redirect("/index")
                
            return render_template("login.html")

        @app.route("/logout")
        @login_required
        def logout():
            session.pop("user", None)
            flash("You have been logged out.", "success")
            return redirect(url_for('login'))

        @app.route("/profile")
        @login_required
        def profile():
            return render_template("profile.html", user=session.get("user"))

        @app.route("/home")
        def home():
            return render_template("home.html")

        @app.route("/index")
        @login_required
        def index():
            return render_template("index.html")

        @app.route("/dashboard")
        @login_required
        def dashboard():
            return render_template("dashboard.html")

        @app.route("/filter")
        @login_required
        def filter():
            return render_template("filter.html")

        @app.route("/training")
        def training_page():
            return render_template("training.html")

        @app.route("/valve-specs")
        @login_required
        def valve_specs_page():
            return render_template("valve_specs.html")

        @app.route("/flow-editor")
        def flow_editor():
            return render_template("flow_editor.html")

        @app.route("/control_panel")
        def control_panel():
            return render_template("control_panel.html")

        @app.route("/api/overview")
        def overview():
            return render_template("overview.html")
        
        @app.route("/dashboard_stats", methods=["GET"])
        def dashboard_stats():
            """
            Get inspection statistics for the home page dashboard
            Returns today's and all-time inspection statistics
            """
            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        app.logger.error("✗ Database connection not available for dashboard_stats")
                        return jsonify({
                            "inspected": 0,
                            "pass_rate": 0,
                            "rejected": 0,
                            "accepted": 0,
                            "parts": 0,
                            "inspected_total": 0,
                            "pass_rate_total": 0,
                            "rejected_total": 0,
                            "accepted_total": 0,
                            "parts_total": 0,
                        }), 200

                    # ===== TODAY'S STATISTICS =====
                    today_query = """
                        SELECT 
                            COUNT(*) as total_inspected,
                            SUM(CASE WHEN Result = 'Accepted' THEN 1 ELSE 0 END) as accepted,
                            SUM(CASE WHEN Result = 'Rejected' THEN 1 ELSE 0 END) as rejected,
                            COUNT(DISTINCT Part_number) as unique_parts
                        FROM inspections
                        WHERE CAST([timestamp] AS DATE) = CAST(GETDATE() AS DATE)
                    """

                    cursor.execute(today_query)
                    today_result = cursor.fetchone()

                    if today_result is None:
                        inspected_today = 0
                        accepted_today = 0
                        rejected_today = 0
                        parts_today = 0
                    else:
                        inspected_today = today_result[0] or 0
                        accepted_today = today_result[1] or 0
                        rejected_today = today_result[2] or 0
                        parts_today = today_result[3] or 0 

                    # Calculate today's pass rate
                    pass_rate_today = round((accepted_today / inspected_today) * 100) if inspected_today > 0 else 0

                    # ===== ALL-TIME STATISTICS =====
                    total_query = """
                        SELECT 
                            COUNT(*) as total_inspected,
                            SUM(CASE WHEN Result = 'Accepted' THEN 1 ELSE 0 END) as accepted,
                            SUM(CASE WHEN Result = 'Rejected' THEN 1 ELSE 0 END) as rejected,
                            COUNT(DISTINCT Part_number) as unique_parts
                        FROM inspections
                    """

                    cursor.execute(total_query)
                    total_result = cursor.fetchone()

                    if total_result is None:
                        inspected_total = 0
                        accepted_total = 0
                        rejected_total = 0
                        parts_total = 0
                    else:
                        inspected_total = total_result[0] or 0
                        accepted_total = total_result[1] or 0
                        rejected_total = total_result[2] or 0
                        parts_total = total_result[3] or 0
                    # Calculate all-time pass rate
                    pass_rate_total = round((accepted_total / inspected_total) * 100) if inspected_total > 0 else 0

                response_data = {
                    # Today's statistics
                    "inspected": inspected_today,
                    "pass_rate": pass_rate_today,
                    "rejected": rejected_today,
                    "accepted": accepted_today,
                    "parts": parts_today,
                    
                    # All-time statistics
                    "inspected_total": inspected_total,
                    "pass_rate_total": pass_rate_total,
                    "rejected_total": rejected_total,
                    "accepted_total": accepted_total,
                    "parts_total": parts_total,
                }

                app.logger.info(f"✓ Dashboard stats - Today: {inspected_today} inspected, {pass_rate_today}% pass rate | All-time: {inspected_total} inspected, {pass_rate_total}% pass rate")
                return jsonify(response_data), 200

            except Exception as e:
                app.logger.error(f"✗ Dashboard stats error: {str(e)}", exc_info=True)
                return jsonify({
                    "inspected": 0,
                    "pass_rate": 0,
                    "rejected": 0,
                    "accepted": 0,
                    "parts": 0,
                    "inspected_total": 0,
                    "pass_rate_total": 0,
                    "rejected_total": 0,
                    "accepted_total": 0,
                    "parts_total": 0,
                }), 200

        @app.route("/video_feed/<cam_id>")
        def video_feed(cam_id):
            active_part = get_requested_part_number()

            def generate():
                process_every_n = 15
                tick = 0
                last_result = None
                no_frame_count = 0
                max_no_frame = 100
                
                while True:
                    frame = get_latest_frame(cam_id)
                    if frame is None:
                        no_frame_count += 1
                        if no_frame_count > max_no_frame:
                           # app.logger.warning(f"No frames from {cam_id} for {max_no_frame} cycles")
                            # Create a blank frame to keep stream alive
                            frame = np.zeros((480, 640, 3), dtype=np.uint8)
                            cv2.putText(
                                frame,
                                f"Waiting for {cam_id}...",
                                (100, 240),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                1.5,
                                (0, 255, 255),
                                2
                            )
                            no_frame_count = 0
                        else:
                            time.sleep(0.05)
                            continue
                    else:
                        no_frame_count = 0

                    tick += 1
                    if tick % process_every_n == 0:
                        try:
                            result, *_ = process_image_web(
                                frame,
                                f"{cam_id}.jpg",
                                active_part_number=active_part
                            )
                            last_result = result
                        except Exception as e:
                            app.logger.warning(f"process_image_web failed for {cam_id}: {e}")

                    if last_result:
                        color = (0, 255, 0) if last_result == "Accepted" else (0, 0, 255)
                        cv2.putText(
                            frame,
                            f"Result: {last_result}",
                            (20, 50),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1,
                            color,
                            2
                        )

                    ret, buffer = cv2.imencode('.jpg', frame)
                    if not ret:
                        continue

                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

            return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

        @app.route("/start_camera", methods=["POST"])
        def start_camera():
            try:
                app.logger.info("→ Starting camera service...")
                
                # First, check if any cameras are available
                available_cameras = camera_manager.enumerate_available_cameras()
                if available_cameras == 0:
                    error_msg = "No cameras detected. Check: 1) USB connections 2) Hikvision SDK installation 3) Device permissions"
                    app.logger.error(error_msg)
                    return jsonify({
                        "status": "error",
                        "message": error_msg,
                        "failed": {"all": error_msg}
                    }), 500
                
                requested = [("cam1", 0), ("cam2", 1), ("cam3", 2)]
                started, failed = [], {}
                results_lock = threading.Lock()

                def _start_one(cam_id, idx):
                    if idx >= available_cameras:
                        err = (f"Camera device {idx} not available "
                               f"(only {available_cameras} camera(s) detected)")
                        app.logger.warning(f"  Skipping {cam_id}: {err}")
                        with results_lock:
                            failed[cam_id] = err
                        return
                    app.logger.info(f"  Launching {cam_id} (device index {idx})...")
                    ok = start_camera_service(cam_id, idx, timeout=15, retries=3)
                    with results_lock:
                        if ok:
                            started.append(cam_id)
                            app.logger.info(f"\u2713 {cam_id} started successfully")
                        else:
                            err = camera_manager.get_init_error(cam_id) or "initialization timeout"
                            failed[cam_id] = err
                            app.logger.warning(f"\u2717 {cam_id} failed: {err}")

                cam_threads = [
                    threading.Thread(target=_start_one, args=(cam_id, idx), daemon=True)
                    for cam_id, idx in requested
                ]
                for t in cam_threads:
                    t.start()
                for t in cam_threads:
                    t.join(timeout=60)

                if not started:
                    app.logger.error("No cameras initialized!")
                    return jsonify({
                        "status": "error",
                        "message": "Failed to initialize any cameras",
                        "failed": failed,
                        "diagnostics": {
                            "available_cameras": available_cameras,
                            "requested_cameras": len(requested)
                        }
                    }), 500

                if "cam1" in started:
                    try:
                       
                        status = camera_manager.get_camera_status("cam1")
                        app.logger.info(f"cam1 initialized - Status: {status}")
                    except Exception as e:
                        app.logger.warning(f"cam1 config check failed: {e}")

                app.logger.info(f"✓ Camera startup complete: {len(started)} cameras started, {len(failed)} failed")
                return jsonify({
                    "status": "started",
                    "cameras": started,
                    "failed": failed,
                    "diagnostics": {
                        "available_cameras": available_cameras,
                        "started_cameras": len(started),
                        "failed_cameras": len(failed)
                    }
                })
            except Exception as e:
                error_msg = str(e)
                app.logger.error(f"Failed to start camera: {error_msg}", exc_info=True)
                return jsonify({
                    "status": "error",
                    "message": error_msg
                }), 500

        @app.route("/check_cameras", methods=["GET"])
        def check_cameras():
            """Diagnostic endpoint to check available cameras"""
            try:
                available = camera_manager.enumerate_available_cameras()
                
                camera_status = {}
                for cam_id in ["cam1", "cam2", "cam3"]:
                    camera_status[cam_id] = camera_manager.get_camera_status(cam_id)
                
                return jsonify({
                    "available_cameras": available,
                    "status": {
                        "cam1": camera_status["cam1"],
                        "cam2": camera_status["cam2"],
                        "cam3": camera_status["cam3"]
                    },
                    "message": f"Found {available} USB/GigE cameras available"
                })
            except Exception as e:
                app.logger.error(f"Error checking cameras: {e}")
                return jsonify({
                    "error": str(e),
                    "message": "Failed to check camera status"
                }), 500

        @app.route("/stop_camera", methods=["POST"])
        def stop_camera():
            try:
                stop_camera_service("cam1")
                stop_camera_service("cam2")
                stop_camera_service("cam3")

                return jsonify({"status": "stopped"})
            except Exception as e:
                app.logger.error(f"Failed to stop camera: {str(e)}")
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/capture_frame", methods=["POST"])
        def capture_frame_route():
            try:
                payload = request.get_json(silent=True) or {}
                cams = payload.get("cams")
                if cams is None:
                    # default to cam1 and cam2
                    cams = ["cam1", "cam2", "cam3"]
                elif isinstance(cams, str) and cams.lower() in ("all", "*"):
                    cams = ["cam1", "cam2", "cam3"]

                results = []

                active_part_number = normalize_part_number(
                    payload.get("part_number") or session.get("selected_part_number") or session.get("part_number")
                )
                app.logger.debug(
                    "capture_frame() received part_number=%s session_part=%s normalized=%s",
                    payload.get("part_number"),
                    session.get("selected_part_number"),
                    active_part_number
                )
                if not active_part_number:
                    app.logger.error("capture_frame() missing active_part_number. Cannot proceed.")
                    return jsonify({"error": "Active part number is required for capture."}), 400

                session["selected_part_number"] = active_part_number
                reference_folder = os.path.join(TRAINED_IMAGES_FOLDER, active_part_number)
                app.logger.debug("capture_frame() will use reference folder: %s", reference_folder)
                if not os.path.isdir(reference_folder):
                    return jsonify({
                        "error": "Selected part reference folder does not exist.",
                        "part_number": active_part_number,
                        "expected_folder": reference_folder
                    }), 400

                inspection_folder_path = _get_or_create_object_folder(active_part_number)
                inspection_folder_name = os.path.basename(inspection_folder_path)

                for cam_id in cams:
                    try:
                        frame = get_latest_frame(cam_id)
                        if frame is None:
                            results.append({"cam": cam_id, "error": "no_frame"})
                            continue

                        temp_filename = f"{cam_id}_temp.jpg"
                        result_filename = get_next_image_name(inspection_folder_path, cam_id)
                        relative_result_filename = f"{inspection_folder_name}/{result_filename}"

                        result, best_score, result_img_path, best_match, defect_type, part_number, part_name = process_image_web(
                            frame,
                            relative_result_filename,
                            active_part_number=active_part_number
                        )

                        os.makedirs(inspection_folder_path, exist_ok=True)

                        # Determine final filename (keep part name, no timestamp)
                        final_filename = f"{cam_id}.jpg"
                        if result_img_path and os.path.exists(result_img_path):
                            chosen_name = None
                            if part_name and str(part_name).strip().lower() not in ("unknown", "none", ""):
                                chosen_name = str(part_name).strip()
                            elif part_number and str(part_number).strip().lower() not in ("unknown", "none", ""):
                                chosen_name = str(part_number).strip()

                            if chosen_name:
                                safe_base = secure_filename(chosen_name)
                                _, ext = os.path.splitext(result_img_path)
                                ext = ext if ext else ".jpg"
                                desired_basename = f"{safe_base}_{cam_id}{ext}"
                                desired_relname = f"{inspection_folder_name}/{desired_basename}"
                                desired_path = os.path.join(inspection_folder_path, desired_basename)

                                i = 1
                                base_only = os.path.splitext(desired_basename)[0]
                                while os.path.exists(desired_path):
                                    desired_basename = f"{base_only}_{i}{ext}"
                                    desired_relname = f"{inspection_folder_name}/{desired_basename}"
                                    desired_path = os.path.join(inspection_folder_path, desired_basename)
                                    i += 1

                                try:
                                    os.replace(result_img_path, desired_path)
                                    final_filename = desired_relname
                                    result_img_path = desired_path
                                except Exception:
                                    final_filename = os.path.relpath(result_img_path, UPLOAD_FOLDER)
                            else:
                                final_filename = os.path.relpath(result_img_path, UPLOAD_FOLDER)
                        else:
                            # Save raw frame for this camera inside the inspection folder
                            final_filename = result_filename
                            result_img_path = os.path.join(inspection_folder_path, final_filename)
                            cv2.imwrite(result_img_path, frame)
                            final_filename = f"{inspection_folder_name}/{final_filename}"

                        ssim_value = float(best_score) if best_score is not None else None

                        # update last_live_result for UI (last processed camera)
                        global last_live_result
                        last_live_result = {
                            "component": part_name or part_number,
                            "ssim_score": ssim_value,
                            "status": result,
                            "image_name": final_filename,
                            "timestamp": datetime.now().isoformat(),
                            "camera": cam_id,
                            "active_part_number": active_part_number,
                            "reference_folder": os.path.join(TRAINED_IMAGES_FOLDER, active_part_number) if active_part_number else None
                        }

                        # store to DB per camera if requested
                        stored_location = payload.get("location") or session.get("location") or "Unknown"
                        # Always compute shift from the actual record timestamp —
                        # operator UI selection is intentionally ignored so the DB
                        # always reflects the real shift for that moment in time.
                        stored_shifts = get_shift_from_time(datetime.now())
                        try:
                            inserted_id = db_manager.insert_inspection({
                                "part_number": part_number,
                                "part_name": part_name,
                                "image_name": final_filename,
                                "ssim_score": ssim_value,
                                "result": result,
                                "best_match": best_match,
                                "defect_type": defect_type,
                                "timestamp": datetime.now(),
                                "location": stored_location,
                                "shifts": stored_shifts,
                            })
                        except Exception as db_err:
                            app.logger.error(f"DB insert failed for {cam_id}: {db_err}")

                        results.append({
                            "cam": cam_id,
                            "result": result,
                            "ssim": ssim_value,
                            "img": url_for("serve_upload", filename=final_filename),
                            "image_name": final_filename,
                            "best_match": best_match,
                            "defect_type": defect_type,
                            "part_number": part_number,
                            "part_name": part_name,
                            "active_part_number": active_part_number,
                            "reference_folder": os.path.join(TRAINED_IMAGES_FOLDER, active_part_number) if active_part_number else None
                        })
                    except Exception as cam_e:
                        app.logger.error(f"Capture failed for {cam_id}: {cam_e}")
                        results.append({"cam": cam_id, "error": str(cam_e)})

                return jsonify({"results": results})
            except Exception as e:
                app.logger.exception("Auto capture failed")
                return jsonify({"error": str(e)}), 500
            
        @app.route("/api/toggle_software", methods=["POST"])
        def toggle_software():
            status = app.config.get('CAMERA_STATUS', {})
            status['software_open'] = not status.get('software_open', False)
            return jsonify(status)

        @app.route("/api/trigger_camera", methods=["POST"])
        def trigger_camera():
            data = request.get_json() or {}
            object_type = data.get('object_type')
            status = app.config.get('CAMERA_STATUS', {})
            
            if object_type == 'engine_valve':
                if status.get('software_open'):
                    status['running'] = True
                    return jsonify({"message": "Camera Triggered", "status": status, "camera_running": True})
                else:
                    return jsonify({"message": "Software Closed", "status": status, "camera_running": False})
            
            return jsonify({"message": "Ignored", "status": status, "camera_running": False})

        @app.route("/set_exposure", methods=["POST"])
        def set_exposure():
            try:
                data = request.json or {}
                value = data.get("value")
                cam_id = data.get("cam_id", "cam1")
                if value is None:
                    return {"status": "error", "message": "Missing value parameter"}, 400
                value = float(value)
                success = camera_manager.set_camera_exposure(cam_id, value)
                return {"status": "ok" if success else "failed", "value": value, "cam_id": cam_id}
            except Exception as e:
                return {"status": "error", "message": str(e)}, 500

        @app.route("/set_gain", methods=["POST"])
        def set_gain():
            try:
                data = request.json or {}
                value = data.get("value")
                cam_id = data.get("cam_id", "cam1")
                if value is None:
                    return {"status": "error", "message": "Missing value parameter"}, 400
                value = float(value)
                success = camera_manager.set_camera_gain(cam_id, value)
                return {"status": "ok" if success else "failed", "value": value, "cam_id": cam_id}
            except Exception as e:
                return {"status": "error", "message": str(e)}, 500

        @app.route("/set_trigger", methods=["POST"])
        def set_trigger():
            try:
                data = request.json or {}
                value = data.get("value")
                cam_id = data.get("cam_id", "cam1")
                if value is None:
                    return {"status": "error", "message": "Missing value parameter"}, 400
                mode = 1 if bool(value) else 0
                success = camera_manager.set_camera_trigger(cam_id, mode)
                return {"status": "ok" if success else "failed", "mode": mode, "cam_id": cam_id}
            except Exception as e:
                return {"status": "error", "message": str(e)}, 500

        @app.route("/software_trigger", methods=["POST"])
        def software_trigger():
            try:
                # Software trigger handled by camera_manager internally
                return {"status": "ok", "note": "Handled by camera service"}
            except Exception as e:
                return {"status": "error", "message": str(e)}, 500
            
        @app.route("/camera/config", methods=["POST"])
        def camera_config():
            try:
                data = request.get_json()
                cam_id = data.get("cam_id", "cam1")
                # Camera configuration endpoint - returns current status
                status = camera_manager.get_camera_status(cam_id)
                return jsonify({"status": "ok", "cam_id": cam_id, "camera_status": status})

            except Exception as e:
                return jsonify({"error": str(e)}), 500
            
        @app.route("/upload", methods=["POST"])
        def upload():
            try:
                if "image" not in request.files:
                    return jsonify({"error": "No image uploaded"}), 400

                file = request.files["image"]
                if not file or not file.filename:
                    return jsonify({"error": "No filename"}), 400

                original_name: str = secure_filename(file.filename)
                base_name, _ = os.path.splitext(original_name)
                timestamp_str = datetime.now().strftime("_%S")
                filename = f"{timestamp_str}_{base_name}.jpg"
                filepath = os.path.join(UPLOAD_FOLDER, filename)

                img = Image.open(file.stream).convert("RGB")
                img.save(filepath, "JPEG", quality=90)

                active_part_number = normalize_part_number(
                    request.form.get("part_number") or session.get("selected_part_number") or session.get("part_number")
                )
                if active_part_number:
                    ensure_part_folder(TRAINED_IMAGES_FOLDER, active_part_number)

                frame = cv2.imread(filepath)
                if frame is None:
                    return jsonify({"error": "Failed to read saved image"}), 500

                result, best_score, result_img_path, best_match, defect_type, part_number, part_name = process_image_web(
                    frame,
                    filename,
                    active_part_number=active_part_number
                )

                ssim_value = float(best_score) if best_score is not None else None

                location = request.form.get("location") or session.get("location") or "Unknown"
                # Shift is always derived from the actual inspection timestamp —
                # any value sent by the frontend is intentionally ignored.
                shift = get_shift_from_time(datetime.now())

                # ── Update the live-inspection panel (same global the camera path uses) ──
                global last_live_result
                last_live_result = {
                    "component": part_name or part_number,
                    "ssim_score": ssim_value,
                    "status": result,
                    "image_name": filename,
                    "timestamp": datetime.now().isoformat(),
                    "camera": "upload",
                    "active_part_number": active_part_number,
                    "reference_folder": os.path.join(TRAINED_IMAGES_FOLDER, active_part_number) if active_part_number else None
                }

                # ── Persist the inspection result to the database ──
                inserted_id = None
                try:
                    inserted_id = db_manager.insert_inspection({
                        "part_number": part_number,
                        "part_name": part_name,
                        "image_name": filename,
                        "ssim_score": ssim_value,
                        "result": result,
                        "best_match": best_match,
                        "defect_type": defect_type,
                        "timestamp": datetime.now(),
                        "location": location,
                        "shifts": shift,
                        # insert_inspection's INSERT always writes these columns; if they're
                        # NOT NULL in the DB, omitting them causes a silent failed insert.
                        "Core_Hardness_stem": 0,
                        "Crown_Face_runout": 0,
                        "Datum_to_End": 0,
                        "End_Finish": 0,
                        "End_Radius": 0,
                        "Groove_Diameter": 0,
                        "Groove_Chamfer_Angle": 0,
                        "Head_Diameter": 0,
                        "Neck_Diameter": 0,
                        "Overall_Length": 0,
                        "Stem_Diameter": 0,
                        "Seat_Angle": 0,
                        "Surface_Hardness_Nitriding": 0,
                    })
                    if inserted_id is False:
                        app.logger.error(
                            f"DB insert_inspection returned False for uploaded image {filename} "
                            f"(see server console for the underlying pyodbc error)"
                        )
                except Exception as db_err:
                    app.logger.error(f"DB insert failed for uploaded image {filename}: {db_err}")
                    inserted_id = None

                payload = {
                    "result": result,
                    "ssim": ssim_value,
                    "img": url_for("serve_upload", filename=filename),
                    "image_name": filename,
                    "best_match": best_match,
                    "defect_type": defect_type,
                    "part_number": part_number,
                    "part_name": part_name,
                    "active_part_number": active_part_number,
                    "reference_folder": os.path.join(TRAINED_IMAGES_FOLDER, active_part_number) if active_part_number else None,
                    "inspection_id": inserted_id
                }

                return jsonify(payload)

            except Exception as e:
                app.logger.exception("Upload processing failed")
                return jsonify({"error": str(e)}), 500

        @app.route("/save_inspection", methods=["POST"])
        def save_inspection_route():
            try:
                data = request.get_json()
                if not data: 
                    return jsonify({"error": "JSON body required"}), 400

                location = data.get("location") or "Unknown"
                # Compute shift from the record's own timestamp so it is always
                # correct regardless of what the operator selected in the UI.
                _ts_raw = data.get("timestamp")
                _ts_dt  = (
                    datetime.fromisoformat(str(_ts_raw))
                    if _ts_raw else datetime.now()
                )
                shifts = get_shift_from_time(_ts_dt)
                image_name = data.get("image_name")
                if image_name and image_name.startswith("/"):
                    image_name = os.path.basename(image_name)
                def safe_float(val):
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        return 0.0
                    
                def safe_str(val, default="Unknown"):
                    if val is None or str(val).strip() == "":
                        return default
                    return str(val).strip()
                
                db_payload = {
                    "part_number": data.get("part_number"),
                    "part_name": data.get("part_name"),
                    "image_name": image_name,
                    "ssim_score": data.get("ssim_score"),
                    "result": data.get("result"),
                    "best_match": data.get("best_match"),
                    "defect_type": data.get("defect_type"),
                    "timestamp": data.get("timestamp") or datetime.now(),
                    "location": location,
                    "shifts": shifts,
                    "Core_Hardness_stem": float(data.get("Core_Hardness_stem") or 0),
                    "Crown_Face_runout": float(data.get("Crown_Face_runout") or 0),
                    "Datum_to_End": float(data.get("Datum_to_End") or 0),
                    "End_Finish": float(data.get("End_Finish") or 0),
                    "End_Radius": float(data.get("End_Radius") or 0),
                    "Groove_Diameter": float(data.get("Groove_Diameter") or 0),
                    "Groove_Chamfer_Angle": float(data.get("Groove_Chamfer_Angle") or 0),
                    "Head_Diameter": float(data.get("Head_Diameter") or 0),
                    "Neck_Diameter": float(data.get("Neck_Diameter") or 0),
                    "Overall_Length": float(data.get("Overall_Length") or 0),
                    "Stem_Diameter": float(data.get("Stem_Diameter") or 0),
                    "Seat_Angle": float(data.get("Seat_Angle") or 0),
                    "Surface_Hardness_Nitriding": float(data.get("Surface_Hardness_Nitriding") or 0),
                }
                
                inserted_id = db_manager.insert_inspection(db_payload)
                return jsonify({"status": "success", "id": inserted_id})

            except ValueError as ve:
                app.logger.error("Validation error saving inspection: %s", ve)
                return jsonify({"error": str(ve)}), 400

            except Exception as e:
                app.logger.exception("Failed to save inspection")
                return jsonify({"error": str(e)}), 500

        @app.route("/inspect", methods=["POST"])
        def inspect():
            data = request.get_json(silent=True) or {}
            active_part_number = normalize_part_number(
                data.get("part_number") or session.get("selected_part_number") or session.get("part_number")
            )
            if not active_part_number:
                return jsonify({"success": False, "error": "Active part number is required."}), 400

            reference_folder = os.path.join(TRAINED_IMAGES_FOLDER, active_part_number)
            if not os.path.isdir(reference_folder):
                return jsonify({
                    "success": False,
                    "error": "Selected part reference folder does not exist.",
                    "part_number": active_part_number,
                    "expected_folder": reference_folder
                }), 400

            inspection_folder_path = _get_or_create_object_folder(active_part_number)
            object_id = os.path.basename(inspection_folder_path)
            result = run_multi_camera_inspection(object_id)
            return jsonify({
                "success": True,
                "object_id": object_id,
                "result": result,
                "folder": f"{UPLOAD_FOLDER}/{object_id}"
            })

        @app.route("/api/inspection/next_object", methods=["POST"])
        def next_object():
            """
            Explicitly close out the current object's inspection folder.
            Call this when the operator/system has finished capturing all
            images for the current valve/object (whether it took 5, 6, 7,
            8, 9, or 10 images) and is about to start the next one.
            The next call to /capture_frame or /inspect will then create
            a brand new folder for the new object.
            """
            closed_folder = _close_current_object_folder()
            return jsonify({
                "status": "ok",
                "closed_folder": closed_folder,
                "message": (
                    f"Closed object folder '{closed_folder}'. Next capture will start a new folder."
                    if closed_folder else
                    "No object folder was open. Next capture will start a new folder."
                )
            })

        # Background Inspection API Endpoints
        @app.route("/api/inspection/start", methods=["POST"])
        def start_bg_inspection():
            """Start inspection in background thread."""
            try:
                data = request.get_json() or {}
                active_part = normalize_part_number(data.get("part_number") or "")
                if not active_part:
                    return jsonify({
                        "status": "error",
                        "message": "Active part number is required for inspection.",
                        "field": "part_number"
                    }), 400
                session["selected_part_number"] = active_part
                auto_continuous = data.get("continuous", False)
                reference_folder = os.path.join(TRAINED_IMAGES_FOLDER, active_part)
                app.logger.debug("start_bg_inspection() active_part=%s reference_folder=%s", active_part, reference_folder)
                if not os.path.isdir(reference_folder):
                    return jsonify({
                        "status": "error",
                        "message": f"Selected part reference folder does not exist: {reference_folder}",
                        "part_number": active_part
                    }), 400

                def continuous_inspection():
                    """Run continuous inspection until stopped."""
                    inspection_folder = inspection_manager.inspection_data.get("inspection_folder")
                    inspection_folder_name = os.path.basename(inspection_folder) if inspection_folder else None

                    while inspection_manager.should_continue():
                        try:
                            frame = get_latest_frame("cam1")
                            if frame is not None and inspection_folder:
                                result_filename = get_next_image_name(inspection_folder, "cam1")
                                result_path = f"{inspection_folder_name}/{result_filename}" if inspection_folder_name else result_filename
                                result, best_score, _, best_match, defect_type, detected_part, part_name = process_image_web(
                                    frame,
                                    result_path,
                                    active_part_number=active_part
                                )
                                
                                inspection_manager.update_status(
                                    selected_part_number=active_part,
                                    current_part=detected_part or active_part,
                                    total_inspections=inspection_manager.inspection_data["total_inspections"] + 1
                                )
                                
                                if result == "Accepted":
                                    inspection_manager.update_status(
                                        passed=inspection_manager.inspection_data["passed"] + 1
                                    )
                                else:
                                    inspection_manager.update_status(
                                        failed=inspection_manager.inspection_data["failed"] + 1
                                    )
                            
                            time.sleep(0.5)
                        except Exception as e:
                            app.logger.warning(f"Inspection iteration error: {e}")
                            time.sleep(1)
                
                if inspection_manager.start_inspection(continuous_inspection, folder_prefix=active_part):
                    return jsonify({
                        "status": "success",
                        "message": "Inspection started in background",
                        "continuous": auto_continuous,
                        "part_number": active_part
                    }), 200
                else:
                    return jsonify({
                        "status": "error",
                        "message": "Inspection already running"
                    }), 409
            except Exception as e:
                app.logger.exception("Failed to start background inspection")
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/inspection/stop", methods=["POST"])
        def stop_bg_inspection():
            """Stop the running inspection."""
            try:
                if inspection_manager.stop_inspection():
                    return jsonify({
                        "status": "success",
                        "message": "Inspection stopped"
                    }), 200
                else:
                    return jsonify({
                        "status": "error",
                        "message": "No inspection running"
                    }), 404
            except Exception as e:
                app.logger.exception("Failed to stop inspection")
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/inspection/pause", methods=["POST"])
        def pause_bg_inspection():
            """Pause the running inspection."""
            try:
                if inspection_manager.pause_inspection():
                    return jsonify({
                        "status": "success",
                        "message": "Inspection paused"
                    }), 200
                else:
                    return jsonify({
                        "status": "error",
                        "message": "No inspection running"
                    }), 404
            except Exception as e:
                app.logger.exception("Failed to pause inspection")
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/inspection/resume", methods=["POST"])
        def resume_bg_inspection():
            """Resume a paused inspection."""
            try:
                if inspection_manager.resume_inspection():
                    return jsonify({
                        "status": "success",
                        "message": "Inspection resumed"
                    }), 200
                else:
                    return jsonify({
                        "status": "error",
                        "message": "No paused inspection"
                    }), 404
            except Exception as e:
                app.logger.exception("Failed to resume inspection")
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/inspection/status", methods=["GET"])
        def get_inspection_status():
            """Get current inspection status."""
            try:
                status = inspection_manager.get_status()
                session_status = session_manager.get_current_status()
                status["session"] = session_status
                return jsonify(status), 200
            except Exception as e:
                app.logger.exception("Failed to get inspection status")
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/valve_types", methods=["GET"])
        def get_valve_types():
            """Return available valve types, required image counts, and position lists."""
            try:
                cfg = session_manager.config
                return jsonify({
                    "status": "success",
                    "valve_types": cfg.get("valve_types", {})
                }), 200
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/inspection/start_session", methods=["POST"])
        def start_inspection_session():
            """Start a new inspection session for a specific valve type."""
            try:
                data = request.get_json() or {}
                valve_type = data.get("valve_type", "Gate Valve")
                operator = data.get("operator", session.get("username", "Operator"))
                sess = session_manager.start_new_session(valve_type=valve_type, operator=operator)
                return jsonify({
                    "status": "success",
                    "session": sess
                }), 200
            except Exception as e:
                app.logger.exception("Failed to start inspection session")
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/inspection/capture_view", methods=["POST"])
        def capture_inspection_view():
            """Capture a position view image for the active inspection session."""
            try:
                data = request.get_json() or {}
                inspection_id = data.get("inspection_id")
                camera_id = data.get("camera_id", "cam1")
                position = data.get("position")

                curr = session_manager.get_current_status()
                if not curr.get("active"):
                    return jsonify({"status": "error", "message": "No active inspection session"}), 400

                if not inspection_id:
                    inspection_id = curr.get("inspection_id")

                if not isinstance(inspection_id, str):
                    return jsonify({"status": "error", "message": "Missing or invalid inspection_id"}), 400

                if not position:
                    position = curr.get("next_required_position") or "Front"

                frame = get_latest_frame(camera_id)
                if frame is None:
                    # Synthetic fallback frame if camera unavailable
                    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                    cv2.putText(frame, f"INSPECTION {inspection_id}", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 2)
                    cv2.putText(frame, f"VIEW: {position}", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)

                success, msg, img_meta = session_manager.record_captured_image(
                    inspection_id=inspection_id,
                    camera_id=camera_id,
                    position=position,
                    frame=frame
                )

                if not success:
                    return jsonify({"status": "error", "message": msg}), 400

                comp_status, comp_msg = session_manager.is_inspection_complete(inspection_id)
                return jsonify({
                    "status": "success",
                    "message": msg,
                    "image_meta": img_meta,
                    "inspection_complete": comp_status,
                    "completion_detail": comp_msg,
                    "current_session": session_manager.get_current_status()
                }), 200

            except Exception as e:
                app.logger.exception("Failed to capture inspection view")
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/inspection/current_status", methods=["GET"])
        def get_current_session_status():
            """Return active session state, progress %, and next required view."""
            try:
                status = session_manager.get_current_status()
                return jsonify({
                    "status": "success",
                    "session": status
                }), 200
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/inspection/complete", methods=["POST"])
        def complete_inspection_session():
            """Finalize defect analysis and ACCEPTED/REJECTED decision for the current inspection."""
            try:
                data = request.get_json() or {}
                inspection_id = data.get("inspection_id")
                curr = session_manager.get_current_status()
                if not inspection_id and curr.get("active"):
                    inspection_id = curr.get("inspection_id")

                if not inspection_id:
                    return jsonify({"status": "error", "message": "Missing inspection_id"}), 400

                complete, comp_msg = session_manager.is_inspection_complete(inspection_id)
                if not complete:
                    return jsonify({
                        "status": "error",
                        "message": f"Inspection incomplete: {comp_msg}"
                    }), 400

                # Analyze captured images for defects
                defects = []
                for img in curr.get("captured_images", []):
                    rel_path = img.get("file_path", "")
                    abs_path = img.get("abs_path", os.path.join(os.getcwd(), rel_path))
                    if os.path.exists(abs_path):
                        img_cv = cv2.imread(abs_path)
                        if img_cv is not None:
                            # Use project's defect analysis logic
                            defect_res = process_image_web(img_cv, rel_path, active_part_number=curr.get("valve_type", "Gate Valve"))
                            res_text, _, _, _, defect_type, _, _ = defect_res
                            defects.append({
                                "image_id": img.get("image_id"),
                                "camera_id": img.get("camera_id"),
                                "position": img.get("image_position"),
                                "defect_type": defect_type or "None",
                                "result": res_text
                            })

                finalized = session_manager.finalize_inspection(defects)

                # Store in SQL Database
                try:
                    db_manager.insert_inspection({
                        "inspection_id": finalized.get("inspection_id"),
                        "part_number": finalized.get("valve_type"),
                        "valve_type": finalized.get("valve_type"),
                        "required_images": finalized.get("required_images"),
                        "captured_images": len(finalized.get("captured_images", [])),
                        "image_name": finalized.get("captured_images", [{}])[0].get("file_path", "inspection.jpg"),
                        "result": finalized.get("final_result"),
                        "status": finalized.get("state"),
                        "final_result": finalized.get("final_result"),
                        "defect_type": "Defects Found" if finalized.get("final_result") == "REJECTED" else "None",
                        "timestamp": datetime.now()
                    })
                except Exception as db_err:
                    app.logger.warning(f"Database logging warning: {db_err}")

                return jsonify({
                    "status": "success",
                    "message": "Inspection completed and saved",
                    "finalized_session": finalized
                }), 200

            except Exception as e:
                app.logger.exception("Failed to complete inspection session")
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/api/inspection/recover", methods=["POST"])
        def recover_inspection_session():
            """Resume or discard an incomplete session detected after app restart."""
            try:
                data = request.get_json() or {}
                action = data.get("action", "resume") # 'resume' or 'discard'
                if action == "discard":
                    session_manager.reset_or_recover("discard")
                    return jsonify({"status": "success", "message": "Incomplete session discarded"}), 200
                else:
                    curr = session_manager.get_current_status()
                    return jsonify({"status": "success", "session": curr}), 200
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500

        @app.route("/inspection/<part_number>")
        def inspection_details(part_number):
            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        return jsonify({"error": "Database connection not available"}), 500

                    cursor.execute("""
                        SELECT TOP 1 Part_number, Image_name, Result, ssim_score, Defect_type, Best_match, timestamp
                        FROM inspections
                        WHERE Part_number = ?
                        ORDER BY timestamp DESC
                    """, (part_number,))
                    row = cursor.fetchone()

                    if not row:
                        return render_template("inspection_details.html", error="No inspections found")

                    base_name = row[1]
                    uploads_folder = os.path.join("static", "uploads")
                    candidate = os.path.join(uploads_folder, base_name)
                    if not os.path.exists(candidate) and not os.path.splitext(base_name)[1]:
                        for ext in [".jpg", ".jpeg", ".png"]:
                            candidate = os.path.join(uploads_folder, base_name + ext)
                            if os.path.exists(candidate):
                                base_name = base_name + ext
                                break

                    inspection = {
                        "part_number": row[0],
                        "image_name": row[1],
                        "result": row[2],
                        "ssim_score": round(row[3], 4) if row[3] else None,
                        "defect_type": row[4],
                        "trained_image": row[5],
                        "timestamp": row[6]
                    }

                return render_template("inspection_details.html", inspection=inspection)

            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/inspection/query")
        def inspection_query():
            part_number = request.args.get("part_number")
            if not part_number:
                return "Part number not provided", 400
            return redirect(url_for("inspection_details", part_number=part_number))

        @app.route("/inspection/")
        def inspection_index():
            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        return "Database connection not available", 500

                    cursor.execute("""
                        SELECT TOP 1 Part_number, Image_name, Result, ssim_score, Defect_type, Best_match, timestamp
                        FROM inspections
                        ORDER BY timestamp DESC
                    """)
                    row = cursor.fetchone()

                    if row:
                        inspection = {
                            "part_number": row[0],
                            "image_name": row[1],
                            "result": row[2],
                            "ssim_score": round(row[3], 4) if row[3] else None,
                            "defect_type": row[4],
                            "trained_image": row[5],
                            "timestamp": row[6]
                        }
                        return render_template("inspection_details.html", inspection=inspection)

                    return "No inspections found"
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/defect-dashboard")
        def defect_dashboard_data():
            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        return jsonify({"accepted": 0, "rejected": 0, "total": 0}), 200

                    try:
                        cursor.execute("SELECT COUNT(*) FROM inspections WHERE Result = 'Accepted'")
                        row = cursor.fetchone()
                        accepted = row[0] if row else 0
                    except:
                        accepted = 0

                    try:
                        cursor.execute("SELECT COUNT(*) FROM inspections WHERE Result = 'Rejected'")
                        row = cursor.fetchone()
                        rejected = row[0] if row else 0
                    except:
                        rejected = 0

                total = accepted + rejected
                return jsonify({"accepted": accepted, "rejected": rejected, "total": total})
                
            except Exception as e:
                app.logger.warning(f"Dashboard fetch warning: {str(e)}")
                return jsonify({"accepted": 0, "rejected": 0, "total": 0}), 200

        @app.route("/api/daily-notification")
        def get_daily_notification():
            global last_daily_notification
            if last_daily_notification["message"]:
                return jsonify(last_daily_notification)
            return jsonify({"message": None, "timestamp": None})

        @app.route("/api/latest-live")
        def latest_live():
            return jsonify(last_live_result)

        @app.route("/api/shift-stats")
        def shift_stats():
            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        return jsonify({"data": []})

                    today = datetime.now().replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )

                    # Shift is derived from the [timestamp] column directly in SQL
                    # so even old rows that were stored with a wrong operator-selected
                    # shift are bucketed correctly in the chart.
                    # Shift A : 06:30 – 14:30
                    # Shift B : 14:30 – 22:30
                    # Shift C : 22:30 – 06:30 (overnight)
                    cursor.execute("""
                        SELECT
                            CASE
                                WHEN CAST([timestamp] AS TIME) >= '06:30'
                                 AND CAST([timestamp] AS TIME) <  '14:30'
                                THEN 'Shift A'
                                WHEN CAST([timestamp] AS TIME) >= '14:30'
                                 AND CAST([timestamp] AS TIME) <  '22:30'
                                THEN 'Shift B'
                                ELSE 'Shift C'
                            END AS shift,
                            SUM(CASE WHEN Result = 'Accepted' THEN 1 ELSE 0 END) AS accepted,
                            SUM(CASE WHEN Result = 'Rejected' THEN 1 ELSE 0 END) AS rejected
                        FROM inspections
                        WHERE [timestamp] >= ?
                        GROUP BY
                            CASE
                                WHEN CAST([timestamp] AS TIME) >= '06:30'
                                 AND CAST([timestamp] AS TIME) <  '14:30'
                                THEN 'Shift A'
                                WHEN CAST([timestamp] AS TIME) >= '14:30'
                                 AND CAST([timestamp] AS TIME) <  '22:30'
                                THEN 'Shift B'
                                ELSE 'Shift C'
                            END
                        ORDER BY shift
                    """, (today,))

                    rows = cursor.fetchall()
                    data = [
                        {"shift": r[0], "accepted": int(r[1] or 0), "rejected": int(r[2] or 0)}
                        for r in rows
                    ]
                return jsonify({"data": data})

            except Exception as e:
                app.logger.error(f"shift-stats failed: {e}")
                return jsonify({"data": [], "error": str(e)})

        @app.route("/api/rejected-data/<filter_type>")
        def get_rejected_data(filter_type):
            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        return jsonify({"error": "Database connection not available"}), 500

                    now = datetime.utcnow()

                    if filter_type == "daily":
                        start_date = datetime(now.year, now.month, now.day)
                    elif filter_type == "weekly":
                        start_date = now - timedelta(days=7)
                    elif filter_type == "monthly":
                        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    elif filter_type == "3months":
                        start_date = datetime(now.year, now.month, 1) - timedelta(days=90)
                    elif filter_type == "6months":
                        start_date = datetime(now.year, now.month, 1) - timedelta(days=180)
                    elif filter_type == "yearly":
                        start_date = datetime(now.year - 1, now.month, now.day)
                    else:
                        return jsonify({"error": "Invalid filter type"}), 400

                    cursor.execute("""
                        SELECT Part_number, Result, Defect_type, [timestamp]
                        FROM inspections
                        WHERE Result = 'Rejected' AND [timestamp] >= ?
                    """, (start_date,))
                    rows = cursor.fetchall()
                    columns = [col[0] for col in cursor.description]
                    data = [{col: row[i] for i, col in enumerate(columns)} for row in rows]

                return jsonify(data)
                
            except Exception as e:
                return jsonify({"error": f"Failed to fetch rejected data: {str(e)}"}), 500

        # ── NEW: accepted data endpoint (mirrors rejected-data) ──────────────
        @app.route("/api/accepted-data/<filter_type>")
        def get_accepted_data(filter_type):
            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        return jsonify({"error": "Database connection not available"}), 500

                    now = datetime.utcnow()

                    if filter_type == "daily":
                        start_date = datetime(now.year, now.month, now.day)
                    elif filter_type == "weekly":
                        start_date = now - timedelta(days=7)
                    elif filter_type == "monthly":
                        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    elif filter_type == "3months":
                        start_date = datetime(now.year, now.month, 1) - timedelta(days=90)
                    elif filter_type == "6months":
                        start_date = datetime(now.year, now.month, 1) - timedelta(days=180)
                    elif filter_type == "yearly":
                        start_date = datetime(now.year - 1, now.month, now.day)
                    else:
                        return jsonify({"error": "Invalid filter type"}), 400

                    cursor.execute("""
                        SELECT Part_number, Result, Defect_type, [timestamp]
                        FROM inspections
                        WHERE Result = 'Accepted' AND [timestamp] >= ?
                        ORDER BY [timestamp] DESC
                    """, (start_date,))
                    rows = cursor.fetchall()
                    columns = [col[0] for col in cursor.description]
                    data = [{col: row[i] for i, col in enumerate(columns)} for row in rows]

                return jsonify(data)

            except Exception as e:
                return jsonify({"error": f"Failed to fetch accepted data: {str(e)}"}), 500

        # ── NEW: filter-page Excel report download ───────────────────────────
        @app.route("/api/reports/filter-export", methods=["GET"])
        @login_required
        def filter_export():
            try:
                filter_type = request.args.get("filter", "daily").lower()
                result_type = request.args.get("result", "rejected").lower()

                if result_type not in ("accepted", "rejected"):
                    return jsonify({"error": "result must be 'accepted' or 'rejected'"}), 400

                now = datetime.utcnow()
                if filter_type == "daily":
                    start_date = datetime(now.year, now.month, now.day)
                elif filter_type == "weekly":
                    start_date = now - timedelta(days=7)
                elif filter_type == "monthly":
                    start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                elif filter_type == "3months":
                    start_date = datetime(now.year, now.month, 1) - timedelta(days=90)
                elif filter_type == "6months":
                    start_date = datetime(now.year, now.month, 1) - timedelta(days=180)
                elif filter_type == "yearly":
                    start_date = datetime(now.year - 1, now.month, now.day)
                else:
                    return jsonify({"error": "Invalid filter type"}), 400

                result_value = "Accepted" if result_type == "accepted" else "Rejected"

                with db_cursor() as (conn, cursor):


                    if not conn or not cursor:
                        return jsonify({"error": "Database connection not available"}), 500

                    cursor.execute("""
                        SELECT Part_number, Result, Defect_type, [timestamp]
                        FROM inspections
                        WHERE Result = ? AND [timestamp] >= ?
                        ORDER BY [timestamp] DESC
                    """, (result_value, start_date))
                    rows = cursor.fetchall()
                    columns = [col[0] for col in cursor.description]

                if not rows:
                    return jsonify({"error": f"No {result_value} data found for selected period"}), 404

                import pandas as pd
                from openpyxl.styles import PatternFill, Font, Alignment
                df = pd.DataFrame([{col: row[i] for i, col in enumerate(columns)} for row in rows])
                df.columns = ["Part Number", "Result", "Defect Type", "Timestamp"]

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name=result_value)
                    wb = writer.book
                    ws = writer.sheets[result_value]
                    header_fill = PatternFill(start_color="13273F", end_color="13273F", fill_type="solid")
                    header_font = Font(bold=True, color="FFFFFF")
                    for cell in ws[1]:
                        cell.fill = header_fill
                        cell.font = header_font
                        cell.alignment = Alignment(horizontal="center")
                    for col in ws.columns:
                        max_len = max((len(str(c.value)) for c in col if c.value), default=10)
                        ws.column_dimensions[col[0].column_letter].width = max_len + 4
                output.seek(0)

                filename = f"{result_value}_Report_{filter_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                return send_file(
                    output,
                    as_attachment=True,
                    download_name=filename,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            except Exception as e:
                app.logger.exception("Filter export error")
                return jsonify({"error": str(e)}), 500

        # ── Filter page: fetch all rows for a time window ────────────────────
        @app.route("/api/filter-inspection-data/<filter_type>")
        @login_required
        def filter_inspection_data(filter_type):
            """
            Return every inspection row for the requested time window.
            The frontend splits the result into Accepted / Rejected tabs.

            report_id is a 0-based row index into the full table ordered by
            [timestamp] DESC — matching exactly how /api/report/data?id=...
            resolves rows, so "View Report" links open the right record.

            filter_type: daily | weekly | monthly | 3months | 6months | yearly
            """
            try:
                now = datetime.now()

                if filter_type == "daily":
                    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                elif filter_type == "weekly":
                    start_date = now - timedelta(days=7)
                elif filter_type == "monthly":
                    start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                elif filter_type == "3months":
                    start_date = (now.replace(day=1) - timedelta(days=90)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                elif filter_type == "6months":
                    start_date = (now.replace(day=1) - timedelta(days=180)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                elif filter_type == "yearly":
                    start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                else:
                    return jsonify({"error": f"Invalid filter type: {filter_type}"}), 400

                with db_cursor() as (conn, cursor):


                    if not conn or not cursor:
                        return jsonify({"error": "Database connection not available"}), 500

                    # ROW_NUMBER() over the FULL table (no WHERE) ordered by
                    # [timestamp] DESC gives each row its global 0-based index —
                    # the same number /api/report/data?id=N uses to look up a row.
                    cursor.execute("""
                        SELECT
                            rn.global_index  AS report_id,
                            rn.Part_number,
                            rn.Result,
                            rn.Defect_type,
                            rn.[timestamp]
                        FROM (
                            SELECT
                                ROW_NUMBER() OVER (ORDER BY [timestamp] DESC) - 1
                                    AS global_index,
                                Part_number,
                                Result,
                                Defect_type,
                                [timestamp]
                            FROM inspections
                        ) AS rn
                        WHERE rn.[timestamp] >= ?
                        ORDER BY rn.[timestamp] DESC
                    """, (start_date,))

                    columns = [col[0] for col in cursor.description]
                    rows    = cursor.fetchall()

                data = []
                for row in rows:
                    record = {}
                    for i, col in enumerate(columns):
                        val = row[i]
                        if hasattr(val, "strftime"):
                            val = val.strftime("%Y-%m-%d %H:%M:%S")
                        record[col] = val
                    data.append(record)

                app.logger.info(
                    "✓ filter-inspection-data [%s] → %d rows (from %s)",
                    filter_type, len(data), start_date
                )
                return jsonify(data)

            except Exception as e:
                app.logger.exception("filter-inspection-data failed")
                return jsonify({"error": str(e)}), 500

        @app.route("/api/chart-data")
        def chart_data():
            try:
                location = (request.args.get("location") or "").lower()
                part_number = (request.args.get("part_number") or "").lower()
                shift = (request.args.get("shift") or "").lower()
                time_filter = (request.args.get("time_filter") or request.args.get("time") or "").lower()
                
                if location.lower().replace(" ", "") in ["allplants", "all"]:
                    location = ""
                if shift.lower().replace(" ", "") in ["allshifts", "all"]:
                    shift = ""
                if time_filter in ["", "?", None]:
                    time_filter = "daily"
                if part_number.lower() in ["none", "null"]:
                    part_number = ""

                with db_cursor() as (conn, cursor):


                    if not conn or not cursor:
                        return jsonify({"error": "Database connection not available"}), 500

                    now = datetime.now()

                    if time_filter == "daily":
                        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    elif time_filter == "weekly":
                        start_time = now - timedelta(days=7)
                    elif time_filter == "monthly":
                        start_time = now - timedelta(days=30)
                    elif time_filter == "yearly":
                        start_time = now - timedelta(days=365)
                    else:
                        start_time = now - timedelta(days=1)

                    query = """
                        SELECT 
                            SUM(CASE WHEN Result='Accepted' THEN 1 ELSE 0 END) AS accepted,
                            SUM(CASE WHEN Result='Rejected' THEN 1 ELSE 0 END) AS rejected,
                            COUNT(*) AS total
                        FROM inspections
                        WHERE [Timestamp] >= ?
                    """
                    params: List[Any] = [start_time]

                    if location and location != "":
                        query += " AND Location = ?"
                        params.append(location)
                    if shift and shift != "":
                        query += " AND Shifts = ?"
                        params.append(shift)
                    if part_number and part_number != "" and part_number.lower() != "none":
                        query += " AND Part_number = ?"
                        params.append(part_number)

                    cursor.execute(query, params)
                    row = cursor.fetchone()

                    if row is None:
                        accepted = rejected = total = 0
                    else:
                        accepted = row[0] or 0
                        rejected = row[1] or 0
                        total = row[2] or 0

                return jsonify({
                    "accepted": accepted,
                    "rejected": rejected,
                    "total": total
                })
                
            except Exception as e:
                return jsonify({"error": f"Failed to fetch chart data: {str(e)}"}), 500

        @app.route("/api/inspection-details")
        def api_inspection_details():
            """
            Live drill-down for the dashboard's Accepted / Rejected count boxes.
            Mirrors the exact filter logic of /api/chart-data so the rows
            returned here always match the numbers shown on the cards —
            queried fresh from the DB on every call (no caching, no demo data).
            """
            try:
                status = (request.args.get("status") or "").strip().lower()  # accepted / rejected
                location = (request.args.get("location") or "").strip().lower()
                part_number = (request.args.get("part_number") or "").strip().lower()
                shift = (request.args.get("shift") or "").strip().lower()
                time_filter = (request.args.get("time_filter") or request.args.get("time") or "").strip().lower()

                if location.replace(" ", "") in ["allplants", "all"]:
                    location = ""
                if shift.replace(" ", "") in ["allshifts", "all"]:
                    shift = ""
                if time_filter in ["", "?", "none"]:
                    time_filter = "daily"
                if part_number in ["none", "null"]:
                    part_number = ""

                if status not in ("accepted", "rejected"):
                    return jsonify({"error": "status must be 'accepted' or 'rejected'"}), 400

                with db_cursor() as (conn, cursor):


                    if not conn or not cursor:
                        return jsonify({"error": "Database connection not available"}), 500

                    now = datetime.now()

                    if time_filter == "daily":
                        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    elif time_filter == "weekly":
                        start_time = now - timedelta(days=7)
                    elif time_filter == "monthly":
                        start_time = now - timedelta(days=30)
                    elif time_filter == "yearly":
                        start_time = now - timedelta(days=365)
                    else:
                        start_time = now - timedelta(days=1)

                    result_value = "Accepted" if status == "accepted" else "Rejected"

                    query = """
                        SELECT
                            Part_number,
                            Image_name,
                            Result,
                            ssim_score,
                            Defect_type,
                            Best_match,
                            Location,
                            Shifts,
                            [Timestamp]
                        FROM inspections
                        WHERE Result = ? AND [Timestamp] >= ?
                    """
                    params: List[Any] = [result_value, start_time]

                    if location:
                        query += " AND Location = ?"
                        params.append(location)
                    if shift:
                        query += " AND Shifts = ?"
                        params.append(shift)
                    if part_number:
                        query += " AND Part_number = ?"
                        params.append(part_number)

                    query += " ORDER BY [Timestamp] DESC"

                    cursor.execute(query, params)
                    rows = cursor.fetchall()

                data = [
                    {
                        "Part Number": r[0],
                        "Image": r[1],
                        "Result": r[2],
                        "SSIM Score": round(r[3], 4) if r[3] is not None else None,
                        "Defect Type": r[4],
                        "Matched Reference": r[5],
                        "Location": r[6],
                        "Shift": r[7],
                        "Timestamp": r[8].strftime("%Y-%m-%d %H:%M:%S") if r[8] else None,
                    }
                    for r in rows
                ]

                return jsonify(data)

            except Exception as e:
                app.logger.exception("inspection-details fetch failed")
                return jsonify({"error": f"Failed to fetch inspection details: {str(e)}"}), 500

        @app.route("/api/filter-data")
        def filter_data():
            location = request.args.get("location", "All")
            shift = request.args.get("shift", "Auto")

            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        return jsonify({"error": "Database connection error"}), 500

                    query = """
                        SELECT *
                        FROM inspections
                        WHERE 1=1
                    """

                    params = []

                    # NOTE: pyodbc/SQL Server uses "?" placeholders, not "%s"
                    if location != "All":
                        query += " AND location = ?"
                        params.append(location)

                    if shift != "Auto":
                        query += " AND shift = ?"
                        params.append(shift)

                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    columns = [col[0] for col in cursor.description]
                    data = [{col: row[i] for i, col in enumerate(columns)} for row in rows]

                return jsonify(data)
            except Exception as e:
                app.logger.error(f"filter-data failed: {e}")
                return jsonify({"error": str(e)}), 500

        @app.route("/api/valve-specs", methods=["GET"])
        def valve_specs():
            part_number = request.args.get("part_number")
            if not part_number:
                return "Part number is required", 400

            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        return jsonify({"error": "Database connection not available"}), 500

                    cursor.execute("""
                        SELECT *
                        FROM Valve_Details
                        WHERE [Part Number] = ?
                    """, (part_number,))
                    row = cursor.fetchone()

                    if not row:
                        return f"No data found for Part Number {part_number}", 404

                    columns = [col[0] for col in cursor.description]
                    specs = {col: row[i] for i, col in enumerate(columns)}

                return jsonify(specs)

            except Exception as e:
                app.logger.error(f"Failed to fetch valve specs: {str(e)}")
                return f"Error fetching valve specs: {str(e)}", 500

        @app.route("/api/reports/daily", methods=["GET"])
        def download_daily_report():
            try:
                date_str = request.args.get("date")
                out_format = request.args.get("format", "xlsx").lower()
                
                if date_str:
                    date_from = datetime.strptime(date_str, "%Y-%m-%d")
                else:
                    today = datetime.now()
                    date_from = datetime(today.year, today.month, today.day)
                    
                date_from = datetime.combine(date_from.date(), datetime.min.time())
                date_to = date_from + timedelta(days=1)
                
                df = db_manager.fetch_inspections(date_from=date_from, date_to=date_to)
                
                if df.empty:
                    return jsonify({"error": "No inspection data found for selected date"}), 404
                    
                out_path, _summary = generate_daily_report(df, date_from, date_from + timedelta(days=1), out_format)
                return send_file(
                    out_path,
                    as_attachment=True,
                    download_name=os.path.basename(out_path),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            except Exception as e:
                app.logger.exception("[Daily Report Error]")
                return jsonify({"error": str(e)}), 500

        @app.route("/api/reports/range", methods=["GET"])
        def download_range_report():
            try:
                df_str = request.args.get("date_from")
                dt_str = request.args.get("date_to")
                out_format = request.args.get("format", "xlsx").lower()
                
                if not df_str or not dt_str:
                    return jsonify({"error": "Please provide date_from and date_to (YYYY-MM-DD)"}), 400
                    
                dfrom = datetime.strptime(df_str, "%Y-%m-%d")
                dto = datetime.strptime(dt_str, "%Y-%m-%d") + timedelta(days=1)
                df = db_manager.fetch_inspections(dfrom, dto)

                if df.empty:
                    return jsonify({"error": "No inspection data found for selected date range"}), 404
                    
                out_path, summary = generate_daily_report(df, date_from=dfrom, date_to=dto, out_format=out_format)
                return send_file(
                    out_path,
                    as_attachment=True,
                    download_name=os.path.basename(out_path),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            except Exception as e:
                app.logger.exception("[Range Report Error]")
                return jsonify({"error": str(e)}), 500

        @app.route("/api/reports/dashboard-download", methods=["GET"])
        @login_required
        def download_dashboard_report():
            try:
                location = (request.args.get("location") or "").strip()
                shift = (request.args.get("shift") or "").strip()
                part_number = (request.args.get("part_number") or "").strip()
                time_filter = (request.args.get("time_filter") or "daily").lower()

                user_role = session.get("role", "PLANT_HEAD")
                user_location = session.get("location", "")

                if user_role != "ADMIN" and user_location:
                    location = user_location

                now = datetime.now()
                if time_filter == "daily":
                    start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
                elif time_filter == "weekly":
                    start_time = now - timedelta(days=7)
                elif time_filter == "monthly":
                    start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                elif time_filter == "yearly":
                    start_time = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                else:
                    start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)

                df = db_manager.fetch_filtered_inspections(
                    start_time=start_time,
                    location=location,
                    shift=shift,
                    part_number=part_number
                )

                if df.empty:
                    return jsonify({"error": "No data found for selected filters"}), 404
                    
                output = io.BytesIO()
                df.to_excel(output, index=False)
                output.seek(0)
                filename = f"dashboard_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                
                return send_file(
                    output,
                    as_attachment=True,
                    download_name=filename,
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            except Exception as e:
                app.logger.exception("Dashboard report download failed")
                return jsonify({"error": str(e)}), 500

        @app.route("/download_excel")
        def download_excel():
            df = db_manager.fetch_inspections(date_from=None, date_to=None)
            output = io.BytesIO()
            df.to_excel(output, index=False)
            output.seek(0)
            return send_file(
                output,
                as_attachment=True,
                download_name="inspections.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        
        @app.route("/api/train-edges", methods=["POST"])
        def train_edges():
            try:
                from image_processing import train_reference_edges, get_edge_visualization

                part_number = request.form.get("part_number")
                if not isinstance(part_number, str) or not part_number.strip():
                    return jsonify({"error": "Invalid or missing part_number"}), 400
                    
                if "image" not in request.files:
                    return jsonify({"error": "No image uploaded"}), 400

                file = request.files["image"]
                if not file or not file.filename:
                    return jsonify({"error": "No image selected"}), 400

                original_name: str = secure_filename(file.filename)
                if not original_name:
                    return jsonify({"error": "Invalid filename"}), 400
                    
                part_folder = os.path.join(TRAINED_IMAGES_FOLDER, part_number)
                os.makedirs(part_folder, exist_ok=True)

                filepath = os.path.join(part_folder, original_name)

                img = Image.open(file.stream).convert("RGB")
                img.save(filepath, "JPEG")

                result_img, features = train_reference_edges(part_number, filepath)

                if result_img is None or not isinstance(result_img, np.ndarray):
                    return jsonify({"error": "Failed to extract edges from image"}), 500

                if not isinstance(features, dict):
                    return jsonify({"error": "Invalid features returned"}), 500

                viz_path: str = os.path.join(
                    "static",
                    "uploads",
                    f"trained_{part_number}_{original_name}"
                )
                cv2.imwrite(viz_path, result_img)

                return jsonify({
                    "success": True,
                    "message": f"Trained edges for part {part_number}",
                    "visualization": url_for("static", filename=f"uploads/trained_{part_number}_{original_name}"),
                    "features": {
                        "area": float(features.get("area", 0.0)),
                        "perimeter": float(features.get("perimeter", 0.0)),
                        "aspect_ratio": float(features.get("aspect_ratio", 0.0)),
                        "solidity": float(features.get("solidity", 0.0))
                    }
                })

            except Exception as e:
                app.logger.error(f"Edge training error: {str(e)}")
                return jsonify({"error": str(e)}), 500

        @app.route("/api/view-edges/<part_number>")
        def view_edges(part_number):
            try:
                from image_processing import get_edge_visualization

                part_folder = os.path.join(TRAINED_IMAGES_FOLDER, part_number)
                if not os.path.exists(part_folder):
                    return jsonify({"error": f"Part {part_number} not found"}), 404

                images = []
                for img_file in os.listdir(part_folder):
                    if img_file.lower().endswith(('.png', '.jpg', '.jpeg', '.jfif', '.bmp')):
                        img_path = os.path.join(part_folder, img_file)
                        viz = get_edge_visualization(img_path)
                        if viz is not None:
                            viz_filename = f"edges_{part_number}_{img_file}"
                            viz_path = os.path.join("static/uploads", viz_filename)
                            cv2.imwrite(viz_path, viz)
                            images.append({
                                "original":url_for("static",filename=f"Golden Libraries/GoldenLibrary/{part_number}/{img_file}"),
                                "edges": url_for("static", filename=f"uploads/{viz_filename}")
                            })

                return jsonify({
                    "part_number": part_number,
                    "images": images
                })

            except Exception as e:
                app.logger.error(f"View edges error: {str(e)}")
                return jsonify({"error": str(e)}), 500

        @app.route("/api/trained-parts")
        def list_trained_parts():
            try:
                parts = []
                if os.path.exists(TRAINED_IMAGES_FOLDER):
                    for part_folder in os.listdir(TRAINED_IMAGES_FOLDER):
                        part_path = os.path.join(TRAINED_IMAGES_FOLDER, part_folder)
                        if os.path.isdir(part_path):
                            image_count = len([f for f in os.listdir(part_path)
                                             if f.lower().endswith(('.png', '.jpg', '.jpeg', '.jfif', '.bmp'))])
                            parts.append({
                                "part_number": part_folder,
                                "image_count": image_count
                            })

                return jsonify({"parts": parts})

            except Exception as e:
                app.logger.error(f"List trained parts error: {str(e)}")
                return jsonify({"error": str(e)}), 500

        @app.route("/api/workflow/run", methods=["POST"])
        def run():
            data = request.get_json(silent=True)
            if data is None:
                return jsonify({"error": "Invalid or missing JSON body"}), 400

            nodes: List[Dict[str, Any]] = data.get("nodes", [])
            edges: List[Dict[str, Any]] = data.get("edges", [])
            start = time.time()
            results = run_workflow(nodes, edges)
            end = time.time()

            return jsonify({
                "node_results": results,
                "execution_time_ms": int((end - start) * 1000)
            })

        @app.route("/report")
        def report_default_page():
            # No specific record ID given - show the live inspection view
            # instead of guessing a record. The report.html JS detects the
            # missing ID and polls /api/report/live.
            return render_template("report.html")

        @app.route("/report/<int:report_id>")
        def report_page(report_id: int):
            return render_template("report.html")

        @app.route("/report/live")
        def report_live_page():
            return render_template("report.html")

        REJECTED_VALUES = {"REJECTED", "NG", "FAIL", "NOT OK", "NO"}
        ERROR_VALUES = {"ERROR", "NO EDGES", "NO EDGE", "ERR"}

        def _is_rejected(result_value) -> bool:
            return str(result_value or "").strip().upper() in REJECTED_VALUES

        def _is_error(result_value) -> bool:
            # Pipeline/detection failures (e.g. camera couldn't find edges) are
            # neither a pass nor a genuine reject - they need their own bucket
            # so they don't silently inflate the Accepted count.
            return str(result_value or "").strip().upper() in ERROR_VALUES

        def _row_image_folder(image_name) -> Optional[str]:
            """Every capture from one inspection run is saved into the same
            folder (see create_inspection_folder / get_next_image_name), so the
            folder name is a natural 'report id' that groups every defect image
            belonging to the same inspection - whether that run produced 1 image
            or many."""
            if not image_name:
                return None
            normalized = str(image_name).replace("\\", "/")
            return normalized.split("/")[0] if "/" in normalized else normalized

        def _build_report_group(df, folder: str) -> Optional[Dict[str, Any]]:
            if "Image_name" not in df.columns:
                return None
            group_df = df[df["Image_name"].apply(_row_image_folder) == folder]
            if group_df.empty:
                return None
            if "Timestamp" in group_df.columns:
                group_df = group_df.sort_values("Timestamp")

            first = group_df.iloc[0]
            defects = []
            rejected_count = 0
            error_count = 0
            images = []
            for _, r in group_df.iterrows():
                result_value = r.get("Result")
                is_error = _is_error(result_value)
                is_rejected = (not is_error) and _is_rejected(result_value)
                error_count += 1 if is_error else 0
                rejected_count += 1 if is_rejected else 0

                image_name = r.get("Image_name")
                image_url = url_for("serve_upload", filename=image_name) if image_name else None
                if image_url:
                    images.append(image_url)
                defects.append({
                    "type": r.get("Defect_type"),
                    "location": r.get("Location"),
                    "camera": r.get("Best_match"),
                    "status": result_value,
                    "image": image_url,
                    "isError": is_error,
                })

            total = len(group_df)
            accepted_count = total - rejected_count - error_count

            if rejected_count > 0:
                final_decision = "Rejected"
            elif error_count > 0 and accepted_count == 0:
                final_decision = "Error"
            else:
                final_decision = "Accepted"

            return {
                "reportId": folder,
                "customer": "Auto.customer",
                "partNo": first.get("Part_number"),
                "partName": first.get("Part_name"),
                "batch": folder,
                "date": str(first.get("Timestamp")),
                "inspector": "System",
                "componentType": "Metal",
                "material": "Steel",
                "qtyInspected": total,
                "qtyRejected": rejected_count,
                "qtyAccepted": accepted_count,
                "qtyErrors": error_count,
                "defects": defects,
                "images": images,
                "imageCount": len(images),
                "originalImage": images[0] if images else None,
                "defectImage": images[-1] if len(images) > 1 else None,
                "finalDecision": final_decision,
            }

        @app.route("/api/report/data", methods=["GET"])
        def get_report_data():
            try:
                index = request.args.get("id", type=int)
                df = db_manager.fetch_inspections()
                if df.empty:
                    return jsonify({"error": "No inspection data available"}), 404
                if index is None:
                    return jsonify({"error": "Index missing"}), 400
                if "Image_name" not in df.columns:
                    return jsonify({"error": "No inspection data available"}), 404

                # The dashboard/list page enumerates individual inspection rows
                # (one row per camera capture), most recent first, and that same
                # 0-based row position is what it sends back as "id". So we must
                # index into the *full* row list here too - not a deduplicated
                # list of folders - otherwise valid ids from the frontend land
                # out of range as soon as any folder has more than one image.
                ordered = df.sort_values("Timestamp", ascending=False) if "Timestamp" in df.columns else df
                ordered = ordered.reset_index(drop=True)

                if index < 0 or index >= len(ordered):
                    return jsonify({"error": "Invalid index"}), 400

                row = ordered.iloc[index]
                folder = _row_image_folder(row.get("Image_name"))
                if not folder:
                    return jsonify({"error": "No inspection data available"}), 404

                # Once we know which folder/run that row belongs to, build the
                # full grouped report (all images/defects for that run), so the
                # report page always shows the complete inspection regardless
                # of which row within it was clicked.
                data = _build_report_group(df, folder)
                if data is None:
                    return jsonify({"error": "No inspection data available"}), 404
                return jsonify(data)
            except Exception as e:
                app.logger.error(f"Get report data error: {str(e)}")
                return jsonify({"error": str(e)}), 500

        @app.route("/api/report/download", methods=["GET"])
        def download_inspection_report_pdf():
            """Generate and download the PDF for the exact report record shown in the UI.

            The report id is the same row index used by /api/report/data?id=...
            so the PDF always matches the report currently displayed.
            """
            try:
                index = request.args.get("id", type=int)
                if index is None:
                    return jsonify({"error": "Report ID is required."}), 400
                if index < 0:
                    return jsonify({"error": "Invalid report ID."}), 400

                df = db_manager.fetch_inspections()
                if df is None or df.empty:
                    return jsonify({"error": "No inspection data available."}), 404

                if "Image_name" not in df.columns:
                    return jsonify({"error": "Inspection image information is unavailable."}), 404

                ordered = df.sort_values("Timestamp", ascending=False) if "Timestamp" in df.columns else df
                ordered = ordered.reset_index(drop=True)

                if index >= len(ordered):
                    return jsonify({"error": f"Invalid report ID: {index}"}), 404

                row = ordered.iloc[index]
                folder = _row_image_folder(row.get("Image_name"))
                if not folder:
                    return jsonify({"error": "Inspection folder could not be determined."}), 404

                report_data = _build_report_group(df, folder)
                if not report_data:
                    return jsonify({"error": "Inspection report data could not be built."}), 404

                part_number = str(report_data.get("partNo") or "unknown").strip()
                safe_part = secure_filename(part_number) or "unknown"
                safe_id = secure_filename(str(index)) or "0"

                os.makedirs(INSPECTION_PDF_FOLDER, exist_ok=True)
                filename = f"Inspection_Report_{safe_id}_{safe_part}.pdf"
                output_path = os.path.join(INSPECTION_PDF_FOLDER, filename)

                generate_inspection_pdf(
                    report_data=report_data,
                    output_path=output_path,
                    app_root=app.root_path,
                )

                if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
                    return jsonify({"error": "PDF was not created."}), 500

                return send_file(
                    output_path,
                    as_attachment=True,
                    download_name=filename,
                    mimetype="application/pdf",
                    max_age=0,
                )

            except Exception as e:
                app.logger.exception("Inspection PDF download failed")
                return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500

        @app.route("/api/report/live", methods=["GET"])
        def get_report_live():
            """Aggregated report for whichever inspection run is currently in
            progress (or most recently finished), so the report page can poll
            this endpoint and watch totals/defect images update as each new
            capture lands - regardless of whether a run produces one image or
            many."""
            try:
                folder = _row_image_folder(last_live_result.get("image_name")) if last_live_result else None
                if not folder:
                    return jsonify({"error": "No live inspection in progress"}), 404

                df = db_manager.fetch_inspections()
                if df.empty:
                    return jsonify({"error": "No inspection data available"}), 404

                data = _build_report_group(df, folder)
                if data is None:
                    return jsonify({"error": "No inspection data available"}), 404

                try:
                    data["isLive"] = bool(inspection_manager.get_status().get("running"))
                except Exception:
                    data["isLive"] = None
                data["lastUpdated"] = last_live_result.get("timestamp")
                return jsonify(data)
            except Exception as e:
                app.logger.error(f"Get live report error: {str(e)}")
                return jsonify({"error": str(e)}), 500
            
        @app.route("/api/diagnostics", methods=["GET"])
        def diagnostics():
            """System diagnostics endpoint for troubleshooting"""
            try:
                diagnostics_info = {
                    "timestamp": datetime.now().isoformat(),
                    "database": {},
                    "cameras": {},
                    "system": {}
                }
                
                # Database diagnostics
                connected, db_msg = db_manager.check_connection()
                diagnostics_info["database"]["connected"] = connected
                diagnostics_info["database"]["message"] = db_msg
                
                # Camera diagnostics
                for cam_id in ["cam1", "cam2", "cam3"]:
                    diagnostics_info["cameras"][cam_id] = camera_manager.get_camera_status(cam_id)
                
                # System diagnostics
                diagnostics_info["system"]["upload_folder_exists"] = os.path.exists(UPLOAD_FOLDER)
                if os.path.exists(UPLOAD_FOLDER):
                    uploads_count = len([f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(('.jpg', '.jpeg', '.png'))])
                    diagnostics_info["system"]["uploads_count"] = uploads_count
                else:
                    diagnostics_info["system"]["uploads_count"] = 0
                diagnostics_info["system"]["last_live_result"] = last_live_result
                
                app.logger.info(f"✓ Diagnostics: DB={diagnostics_info['database']['connected']}, CAM1={diagnostics_info['cameras']['cam1']}")
                return jsonify(diagnostics_info)
            except Exception as e:
                app.logger.error(f"✗ Diagnostics error: {str(e)}", exc_info=True)
                return jsonify({"error": str(e), "timestamp": datetime.now().isoformat()}), 500
            

            
        @app.route("/admin/pending-users")
        @login_required
        def pending_users():
            if session.get("role") != "ADMIN":
                abort(403)
            return jsonify(db_manager.get_pending_users())

        @app.route("/admin/approve/<username>", methods=["POST"])
        @login_required
        def approve(username):
            if session.get("role") != "ADMIN":
                abort(403)
            db_manager.approve_user(username)
            return jsonify({"status": "approved"})

        @app.route('/api/inspection/active-part', methods=['GET', 'POST'])
        def active_part():
            try:
                if request.method == 'POST':
                    data = request.get_json(silent=True) or {}
                    part_number = normalize_part_number(
                        data.get('part_number') or request.form.get('part_number')
                    )
                    if not part_number:
                        return jsonify({
                            'success': False,
                            'message': 'Part number is required.'
                        }), 400

                    session['selected_part_number'] = part_number
                    app.logger.info('Selected Part Number from UI: %s', part_number)
                    return jsonify({
                        'success': True,
                        'active_part_number': part_number
                    })

                part_number = normalize_part_number(session.get('selected_part_number'))
                app.logger.debug('active_part GET returning %s', part_number)
                return jsonify({
                    'success': True,
                    'active_part_number': part_number
                })
            except Exception as e:
                app.logger.exception('active_part endpoint failed')
                return jsonify({
                    'success': False,
                    'message': str(e)
                }), 500

        @app.route('/uploads/<path:filename>')
        def serve_upload(filename):
            return send_from_directory(UPLOAD_FOLDER, filename)
        
        @app.route('/golden_library/<part_number>/<filename>')
        def serve_trained_image(part_number, filename):
            folder = os.path.join(TRAINED_IMAGES_FOLDER, part_number)
            return send_from_directory(folder, filename)
        
        @app.route("/api/test", methods=["GET"])
        def api_test():
            return {"message": "Backend connected"}

        @app.route("/api/reset-stats", methods=["POST"])
        @login_required
        def reset_stats():
            try:
                with db_cursor() as (conn, cursor):

                    if not conn or not cursor:
                        return jsonify({"error": "Database connection not available"}), 500

                    cursor.execute("DELETE FROM inspections WHERE [timestamp] >= CONVERT(date, GETDATE())")
                    conn.commit()

                app.logger.info("✓ Today's statistics reset")
                return jsonify({"status": "success", "message": "Statistics reset successfully"})
            except Exception as e:
                app.logger.error(f"Reset stats error: {str(e)}")
                return jsonify({"error": str(e)}), 500

        # ============ DEFECT DASHBOARD ROUTE ============

        @app.route('/defect_dashboard')
        @login_required
        def defect_dashboard():
            """Render the defect dashboard page"""
            return render_template('defect_dashboard.html')


        # ============ DEFECT DASHBOARD API ENDPOINT ============

        @app.route('/api/defect-dashboard/types', methods=['GET'])
        @login_required
        def get_defect_types():
            """
            Get defect types data for the dashboard
            Query Parameters:
                - part_number: Filter by part number (optional)
                - time_filter: daily, weekly, monthly, yearly (optional)
            """
            try:
                part_number = request.args.get('part_number', '').strip()
                time_filter = request.args.get('time_filter', 'daily').strip()

                with db_cursor() as (conn, cursor):


                    if not conn or not cursor:
                        return jsonify({
                            'error': 'Database connection not available',
                            'chart_labels': [],
                            'chart_values': [],
                            'data': []
                        }), 500

                    # Build query for defect types
                    query = """
                        SELECT 
                            Defect_type as label,
                            COUNT(*) as count
                        FROM inspections
                        WHERE Result = 'Rejected'
                    """

                    params = []

                    # Add part number filter if provided
                    if part_number:
                        query += " AND Part_number = ?"
                        params.append(part_number)

                    # Add time filter
                    if time_filter == 'daily':
                        query += " AND CAST([timestamp] AS DATE) = CAST(GETDATE() AS DATE)"
                    elif time_filter == 'weekly':
                        query += " AND DATEPART(week, [timestamp]) = DATEPART(week, GETDATE()) AND YEAR([timestamp]) = YEAR(GETDATE())"
                    elif time_filter == 'monthly':
                        query += " AND MONTH([timestamp]) = MONTH(GETDATE()) AND YEAR([timestamp]) = YEAR(GETDATE())"
                    elif time_filter == 'yearly':
                        query += " AND YEAR([timestamp]) = YEAR(GETDATE())"

                    query += " GROUP BY Defect_type ORDER BY count DESC"

                    # Execute query
                    cursor.execute(query, params)
                    results = cursor.fetchall()

                # Format response
                chart_labels = []
                chart_values = []
                data = []

                if results:
                    for row in results:
                        if row[0]:  # Check if label is not None
                            chart_labels.append(row[0])
                            chart_values.append(row[1])
                            data.append({
                                'label': row[0],
                                'count': row[1]
                            })

                app.logger.info(f"✓ Defect dashboard data fetched - {len(data)} defect types")

                return jsonify({
                    'success': True,
                    'chart_labels': chart_labels,
                    'chart_values': chart_values,
                    'data': data
                })

            except Exception as e:
                app.logger.error(f"✗ Defect dashboard error: {str(e)}", exc_info=True)
                return jsonify({
                    'error': str(e),
                    'chart_labels': [],
                    'chart_values': [],
                    'data': []
                }), 500


        return app

    except Exception as e:
        print("ERROR inside create_app():", str(e))
        import traceback
        traceback.print_exc()
        return None