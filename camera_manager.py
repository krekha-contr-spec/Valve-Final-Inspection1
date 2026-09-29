import cv2
import threading
import numpy as np
import time
import logging
import ctypes
from typing import Dict, Optional

from hik_cam.MvCameraControl_class import (
    MvCamera,
    MV_CC_DEVICE_INFO_LIST,
    MV_CC_DEVICE_INFO,
    MV_GIGE_DEVICE,
    MV_USB_DEVICE,
    MV_ACCESS_Exclusive,
    MV_FRAME_OUT,
    MV_EXPOSURE_AUTO_MODE_OFF,
    MV_GAIN_MODE_OFF,
    MV_TRIGGER_MODE_OFF,
)

try:
    from hik_cam.MvCameraControl_class import SortMethod_SerialNumber
except ImportError:
    SortMethod_SerialNumber = 0  # fallback if not exported

# ---------------- LOGGING ----------------
logger = logging.getLogger("camera_manager")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# ---------------- SDK INIT (must happen once at module load) ----------------
# MV_CC_Initialize is required before ANY other SDK call.
# Calling it more than once is safe — the SDK ignores duplicate calls.
try:
    MvCamera.MV_CC_Initialize()
    logger.info("Hikvision SDK initialized")
except Exception as _sdk_init_err:
    logger.warning(f"SDK Initialize skipped / already done: {_sdk_init_err}")

# ---------------- GLOBAL STATE ----------------
_cameras: Dict[str, 'HikrobotCamera'] = {}
_frames:  Dict[str, Optional[np.ndarray]] = {}
_running: Dict[str, bool] = {}
_locks:   Dict[str, threading.Lock] = {}
_init_errors:  Dict[str, str] = {}
_init_events:  Dict[str, threading.Event] = {}
_camera_ready: Dict[str, bool] = {}

# One lock guards the SDK CreateHandle/OpenDevice calls.
# These are NOT thread-safe on all SDK versions, so we serialize them.
_camera_init_lock = threading.Lock()

# -----------------------------------------------------------------------
# Shared device list — enumerated ONCE when start_camera_service is first
# called, then reused by every HikrobotCamera so device order is stable.
# -----------------------------------------------------------------------
_shared_device_list: Optional[MV_CC_DEVICE_INFO_LIST] = None
_enum_lock = threading.Lock()


def _enum_devices_once() -> MV_CC_DEVICE_INFO_LIST:
    """
    Enumerate cameras exactly once and cache the result.
    Uses MV_CC_EnumDevicesEx2 (sorted by serial number) so the device
    index is deterministic across calls — cam3 is always device index 2.
    Falls back to the basic MV_CC_EnumDevices if Ex2 is unavailable.
    """
    global _shared_device_list
    with _enum_lock:
        if _shared_device_list is not None:
            return _shared_device_list

        device_list = MV_CC_DEVICE_INFO_LIST()
        ctypes.memset(ctypes.byref(device_list), 0, ctypes.sizeof(device_list))

        layer = MV_GIGE_DEVICE | MV_USB_DEVICE

        # Try the Ex2 variant first (sorts by serial → stable index order)
        try:
            ret = MvCamera.MV_CC_EnumDevicesEx2(
                layer, device_list, '', SortMethod_SerialNumber
            )
            if ret == 0:
                logger.info(
                    f"[enum] MV_CC_EnumDevicesEx2 found {device_list.nDeviceNum} camera(s)"
                )
                _shared_device_list = device_list
                return _shared_device_list
            logger.warning(f"[enum] EnumDevicesEx2 returned 0x{ret:X}, falling back")
        except Exception as ex:
            logger.warning(f"[enum] EnumDevicesEx2 not available: {ex}")

        # Fallback: basic enumeration
        ctypes.memset(ctypes.byref(device_list), 0, ctypes.sizeof(device_list))
        ret = MvCamera.MV_CC_EnumDevices(layer, device_list)
        if ret != 0:
            raise RuntimeError(f"EnumDevices failed: 0x{ret:X}")
        logger.info(f"[enum] MV_CC_EnumDevices found {device_list.nDeviceNum} camera(s)")
        _shared_device_list = device_list
        return _shared_device_list


def _reset_enum_cache():
    """Force a fresh enumeration on the next call (used after stop_all)."""
    global _shared_device_list
    with _enum_lock:
        _shared_device_list = None


# ================= CAMERA CLASS =================
class HikrobotCamera:
    def __init__(self, device_index: int = 0):
        self.cam = MvCamera()

        # Use the shared, stable device list
        device_list = _enum_devices_once()

        logger.info(f"[HikrobotCamera] Detected = {device_list.nDeviceNum}, requesting index {device_index}")

        if device_list.nDeviceNum == 0:
            raise RuntimeError("No cameras found. Check USB/GigE connections and Hikvision SDK installation.")

        if device_index >= device_list.nDeviceNum:
            raise RuntimeError(
                f"Camera index {device_index} not found. "
                f"Only {device_list.nDeviceNum} camera(s) detected."
            )

        # ---------------- SELECT DEVICE ----------------
        dev = ctypes.cast(
            device_list.pDeviceInfo[device_index],
            ctypes.POINTER(MV_CC_DEVICE_INFO)
        ).contents

        # Log identity
        if dev.nTLayerType == MV_GIGE_DEVICE:
            info   = dev.SpecialInfo.stGigEInfo
            serial = bytes(info.chSerialNumber).split(b'\0', 1)[0].decode(errors='replace')
            model  = bytes(info.chModelName).split(b'\0', 1)[0].decode(errors='replace')
            logger.info(f"[HikrobotCamera] GigE  idx={device_index}  {model}  SN={serial}")
        elif dev.nTLayerType == MV_USB_DEVICE:
            info   = dev.SpecialInfo.stUsb3VInfo
            serial = bytes(info.chSerialNumber).split(b'\0', 1)[0].decode(errors='replace')
            model  = bytes(info.chModelName).split(b'\0', 1)[0].decode(errors='replace')
            logger.info(f"[HikrobotCamera] USB3  idx={device_index}  {model}  SN={serial}")

        # ---------------- CREATE HANDLE ----------------
        ret = self.cam.MV_CC_CreateHandle(dev)
        if ret != 0:
            raise RuntimeError(f"CreateHandle failed: 0x{ret:X}")

        # ---------------- OPEN DEVICE ----------------
        ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            self.cam.MV_CC_DestroyHandle()
            raise RuntimeError(f"OpenDevice failed: 0x{ret:X}")

        # ---------------- CAMERA CONFIG ----------------
        self.cam.MV_CC_SetEnumValue("ExposureAuto", MV_EXPOSURE_AUTO_MODE_OFF)
        self.cam.MV_CC_SetEnumValue("GainAuto",     MV_GAIN_MODE_OFF)
        self.cam.MV_CC_SetEnumValue("TriggerMode",  MV_TRIGGER_MODE_OFF)

        # Set continuous acquisition mode (value=2)
        try:
            self.cam.MV_CC_SetEnumValue("AcquisitionMode", 2)
        except Exception:
            logger.warning(f"[HikrobotCamera idx={device_index}] AcquisitionMode not supported")

        self.cam.MV_CC_StartGrabbing()
        logger.info(f"[HikrobotCamera idx={device_index}] Grabbing started")

    # ================= READ FRAME =================
    def read(self):
        frame_out = MV_FRAME_OUT()
        ctypes.memset(ctypes.byref(frame_out), 0, ctypes.sizeof(frame_out))

        ret = self.cam.MV_CC_GetImageBuffer(frame_out, 1000)
        if ret != 0:
            return False, None

        try:
            width       = frame_out.stFrameInfo.nWidth
            height      = frame_out.stFrameInfo.nHeight
            buffer_size = frame_out.stFrameInfo.nFrameLen

            if not frame_out.pBufAddr or width <= 0 or height <= 0:
                return False, None

            data = ctypes.string_at(frame_out.pBufAddr, buffer_size)
            img  = np.frombuffer(data, dtype=np.uint8)

            expected = width * height
            if img.size < expected:
                return False, None

            img   = img[:expected].reshape((height, width))
            frame = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            return True, frame

        except Exception as e:
            logger.error(f"Frame error: {e}")
            return False, None

        finally:
            self.cam.MV_CC_FreeImageBuffer(frame_out)

    def set_exposure(self, value: float) -> bool:
        try:
            ret = self.cam.MV_CC_SetFloatValue("ExposureTime", float(value))
            return ret == 0
        except Exception as e:
            logger.error(f"Set exposure error: {e}")
            return False

    def set_gain(self, value: float) -> bool:
        try:
            ret = self.cam.MV_CC_SetFloatValue("Gain", float(value))
            return ret == 0
        except Exception as e:
            logger.error(f"Set gain error: {e}")
            return False

    def set_trigger_mode(self, mode: int) -> bool:
        try:
            ret = self.cam.MV_CC_SetEnumValue("TriggerMode", int(mode))
            return ret == 0
        except Exception as e:
            logger.error(f"Set trigger mode error: {e}")
            return False

    def release(self):
        try:
            self.cam.MV_CC_StopGrabbing()
            time.sleep(0.1)
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
            logger.info("Camera released")
        except Exception as e:
            logger.error(f"Release error: {e}")


# ================= CAMERA THREAD =================
def _camera_loop(cam_id: str, device_index: int):
    try:
        # Serialise SDK CreateHandle / OpenDevice — not thread-safe on all SDK versions
        with _camera_init_lock:
            if cam_id not in _cameras:
                _cameras[cam_id] = HikrobotCamera(device_index)

        _camera_ready[cam_id] = True
        _init_errors.pop(cam_id, None)
        logger.info(f"[{cam_id}] initialized successfully (device index {device_index})")

    except Exception as e:
        _init_errors[cam_id] = str(e)
        _running[cam_id]     = False
        _init_events[cam_id].set()
        logger.error(f"[{cam_id}] init failed: {e}")
        return

    _init_events[cam_id].set()   # unblock start_camera_service

    while _running.get(cam_id, False):
        try:
            cam = _cameras.get(cam_id)
            if not cam:
                break

            ret, frame = cam.read()
            if ret and frame is not None:
                with _locks[cam_id]:
                    _frames[cam_id] = frame

        except Exception as e:
            logger.error(f"[{cam_id}] loop error: {e}")

        time.sleep(0.01)

    # Cleanup
    try:
        if cam_id in _cameras:
            _cameras[cam_id].release()
            del _cameras[cam_id]
    except Exception:
        pass


# ================= PUBLIC API =================

def start_camera_service(cam_id: str = "cam1", device_index: int = 0,
                         timeout: float = 15, retries: int = 3) -> bool:
    """
    Start a camera capture thread with automatic retry.

    Key fixes vs. the original:
      • SDK is initialized at module import (MV_CC_Initialize).
      • Device list is enumerated once with EnumDevicesEx2 (sorted by serial)
        so device indices are stable — cam3 is always index 2.
      • Timeout raised to 15 s; init lock is released before the event fires
        so cam3 does not have to wait for cam1+cam2 serialisation.
      • Up to 3 retries with 2 s gap before giving up.
    """
    if _running.get(cam_id) and _camera_ready.get(cam_id):
        return True  # already running and healthy

    for attempt in range(1, retries + 1):
        logger.info(f"[{cam_id}] start attempt {attempt}/{retries} (device index {device_index})")

        # Reset state for this attempt
        _running[cam_id]      = True
        _locks[cam_id]        = threading.Lock()
        _frames[cam_id]       = None
        _init_events[cam_id]  = threading.Event()
        _camera_ready[cam_id] = False
        _init_errors.pop(cam_id, None)

        threading.Thread(
            target=_camera_loop,
            args=(cam_id, device_index),
            daemon=True,
            name=f"cam-{cam_id}-{attempt}"
        ).start()

        _init_events[cam_id].wait(timeout)

        if _camera_ready.get(cam_id, False):
            logger.info(f"[{cam_id}] ✓ connected on attempt {attempt}")
            return True

        error = _init_errors.get(cam_id, "initialization timeout")
        logger.warning(f"[{cam_id}] attempt {attempt} failed: {error}")

        # Clean up before retry
        _running[cam_id] = False
        time.sleep(2.0)

    logger.error(f"[{cam_id}] ✗ all {retries} attempts failed")
    return False


def stop_camera_service(cam_id: str = "cam1"):
    _running[cam_id] = False
    time.sleep(0.5)

    if cam_id in _cameras:
        try:
            _cameras[cam_id].release()
        except Exception:
            pass
        _cameras.pop(cam_id, None)

    _frames.pop(cam_id, None)
    _locks.pop(cam_id, None)
    _init_events.pop(cam_id, None)
    _init_errors.pop(cam_id, None)
    _camera_ready.pop(cam_id, None)


def stop_all_cameras():
    """Stop all cameras and reset the device-list cache so it re-enumerates cleanly."""
    for cam_id in list(_running.keys()):
        stop_camera_service(cam_id)
    _reset_enum_cache()


def get_latest_frame(cam_id: str = "cam1") -> Optional[np.ndarray]:
    lock = _locks.get(cam_id)
    if not lock:
        return None
    with lock:
        frame = _frames.get(cam_id)
        return frame.copy() if frame is not None else None


def get_init_error(cam_id: str) -> Optional[str]:
    return _init_errors.get(cam_id)


def get_camera_status(cam_id: str) -> dict:
    return {
        "running":     _running.get(cam_id, False),
        "initialized": _camera_ready.get(cam_id, False),
        "has_frame":   _frames.get(cam_id) is not None,
        "error":       _init_errors.get(cam_id),
    }


def enumerate_available_cameras() -> int:
    """Return how many cameras the SDK can see right now."""
    try:
        # Force a fresh enum so we see newly plugged-in cameras
        _reset_enum_cache()
        dl = _enum_devices_once()
        return dl.nDeviceNum
    except Exception as e:
        logger.error(f"enumerate_available_cameras error: {e}")
        return 0


# ================= COMPATIBILITY ALIASES =================
def capture_frame(cam_id: str = "cam1") -> Optional[np.ndarray]:
    """Alias for get_latest_frame (backward compat)."""
    return get_latest_frame(cam_id)


def set_camera_exposure(cam_id: str, value: float) -> bool:
    cam = _cameras.get(cam_id)
    if cam:
        return cam.set_exposure(value)
    return False


def set_camera_gain(cam_id: str, value: float) -> bool:
    cam = _cameras.get(cam_id)
    if cam:
        return cam.set_gain(value)
    return False


def set_camera_trigger(cam_id: str, mode: int) -> bool:
    cam = _cameras.get(cam_id)
    if cam:
        return cam.set_trigger_mode(mode)
    return False