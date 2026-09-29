import os
import sys
import ctypes
import cv2
import numpy as np
import time
SDK_DLL_PATH = r"C:\Program Files (x86)\MVS\Development\Bin\win64"
if not os.path.exists(SDK_DLL_PATH):
    raise RuntimeError("Hikrobot SDK DLL path not found")
os.add_dll_directory(SDK_DLL_PATH)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from MvCameraControl_class import MvCamera
from CameraParams_const import *
from CameraParams_header import *
from PixelType_header import *

class HikCamera:
    def __init__(self):
        self.cam = MvCamera()
        self.device = None
        self.is_open = False

    def open(self):
        device_list = MV_CC_DEVICE_INFO_LIST()
        ctypes.memset(ctypes.byref(device_list), 0, ctypes.sizeof(device_list))

        ret = self.cam.MV_CC_EnumDevices(
            MV_GIGE_DEVICE | MV_USB_DEVICE,
            device_list
        )
        if ret != 0 or device_list.nDeviceNum == 0:
            raise RuntimeError("No Hikrobot camera detected")

        self.device = ctypes.cast(
            device_list.pDeviceInfo[0],
            ctypes.POINTER(MV_CC_DEVICE_INFO)
        ).contents

        self.cam.MV_CC_CreateHandle(self.device)
        self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        self.cam.MV_CC_SetEnumValue("TriggerMode", 0)
        self.cam.MV_CC_StartGrabbing()
        self.is_open = True
        print("Hikrobot camera opened")

    def read(self, timeout=1000, retries=5):
        if not self.is_open:
            raise RuntimeError("Camera not opened")

        frame_out = MV_FRAME_OUT()
        ctypes.memset(ctypes.byref(frame_out), 0, ctypes.sizeof(frame_out))

        for _ in range(retries):
            ret = self.cam.MV_CC_GetImageBuffer(frame_out, timeout)
            if ret == 0:
                break
            time.sleep(0.05) 
        else:
            return False, None

        try:
            w = frame_out.stFrameInfo.nWidth
            h = frame_out.stFrameInfo.nHeight
            pixel_type = frame_out.stFrameInfo.enPixelType
            buf_len = frame_out.stFrameInfo.nFrameLen

            buffer = ctypes.string_at(frame_out.pBufAddr, buf_len)
            img = np.frombuffer(buffer, dtype=np.uint8)
            if pixel_type == PixelType_Gvsp_Mono8:
                img = img.reshape(h, w)
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            elif pixel_type in (
                PixelType_Gvsp_BayerBG8,
                PixelType_Gvsp_BayerRG8,
                PixelType_Gvsp_BayerGB8,
                PixelType_Gvsp_BayerGR8,
            ):
                img = img.reshape(h, w)
                img = cv2.cvtColor(img, cv2.COLOR_BAYER_BG2BGR)

            elif pixel_type == PixelType_Gvsp_RGB8_Packed:
                img = img.reshape(h, w, 3)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            else:
                print("Unsupported pixel type:", pixel_type)
                return False, None

            return True, img

        finally:
            self.cam.MV_CC_FreeImageBuffer(frame_out)

    def close(self):
        if self.is_open:
            self.cam.MV_CC_StopGrabbing()
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
            self.is_open = False
            print("Hikrobot camera closed")
if __name__ == "__main__":
    cam = HikCamera()
    try:
        cam.open()
        print("Press ESC to exit")

        while True:
            ret, frame = cam.read()
            if not ret:
                continue  

            cv2.imshow("Hikrobot Live", frame)
            if cv2.waitKey(1) & 0xFF == 27:  
                break

    except Exception as e:
        print("Error:", e)

    finally:
        cam.close()
        cv2.destroyAllWindows()
