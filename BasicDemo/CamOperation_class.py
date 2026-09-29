# -- coding: utf-8 --
import threading
import time
import sys
import inspect
import ctypes
import random
import os
import platform
from ctypes import *

# Detect operating system
currentsystem = platform.system()
if currentsystem == 'Windows':
    sys.path.append(os.path.join(os.getenv('MVCAM_COMMON_RUNENV'),
                                 "Samples", "Python", "MvImport"))
else:
    sys.path.append(os.path.join("..", "..", "MvImport"))

from CameraParams_header import *
from MvCameraControl_class import *


# Forcefully terminate a thread
def Async_raise(tid, exctype):
    tid = ctypes.c_long(tid)
    if not inspect.isclass(exctype):
        exctype = type(exctype)
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        tid, ctypes.py_object(exctype))
    if res == 0:
        raise ValueError("Invalid thread id")
    elif res != 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
        raise SystemError("PyThreadState_SetAsyncExc failed")


# Stop a running thread
def Stop_thread(thread):
    Async_raise(thread.ident, SystemExit)


# Convert number to hexadecimal string
def To_hex_str(num):
    chaDic = {10: 'a', 11: 'b', 12: 'c', 13: 'd', 14: 'e', 15: 'f'}
    hexStr = ""
    if num < 0:
        num = num + 2 ** 32
    while num >= 16:
        digit = num % 16
        hexStr = chaDic.get(digit, str(digit)) + hexStr
        num //= 16
    hexStr = chaDic.get(num, str(num)) + hexStr
    return hexStr


# Check if the image is mono (grayscale)
def Is_mono_data(enGvspPixelType):
    if (PixelType_Gvsp_Mono8 == enGvspPixelType or
        PixelType_Gvsp_Mono10 == enGvspPixelType or
        PixelType_Gvsp_Mono10_Packed == enGvspPixelType or
        PixelType_Gvsp_Mono12 == enGvspPixelType or
        PixelType_Gvsp_Mono12_Packed == enGvspPixelType):
        return True
    else:
        return False


# Check if the image is color
def Is_color_data(enGvspPixelType):
    if (PixelType_Gvsp_BayerGR8 == enGvspPixelType or
        PixelType_Gvsp_BayerRG8 == enGvspPixelType or
        PixelType_Gvsp_BayerGB8 == enGvspPixelType or
        PixelType_Gvsp_BayerBG8 == enGvspPixelType or
        PixelType_Gvsp_BayerGR10 == enGvspPixelType or
        PixelType_Gvsp_BayerRG10 == enGvspPixelType or
        PixelType_Gvsp_BayerGB10 == enGvspPixelType or
        PixelType_Gvsp_BayerBG10 == enGvspPixelType or
        PixelType_Gvsp_BayerGR12 == enGvspPixelType or
        PixelType_Gvsp_BayerRG12 == enGvspPixelType or
        PixelType_Gvsp_BayerGB12 == enGvspPixelType or
        PixelType_Gvsp_BayerBG12 == enGvspPixelType or
        PixelType_Gvsp_BayerGR10_Packed == enGvspPixelType or
        PixelType_Gvsp_BayerRG10_Packed == enGvspPixelType or
        PixelType_Gvsp_BayerGB10_Packed == enGvspPixelType or
        PixelType_Gvsp_BayerBG10_Packed == enGvspPixelType or
        PixelType_Gvsp_BayerGR12_Packed == enGvspPixelType or
        PixelType_Gvsp_BayerRG12_Packed == enGvspPixelType or
        PixelType_Gvsp_BayerGB12_Packed == enGvspPixelType or
        PixelType_Gvsp_BayerBG12_Packed == enGvspPixelType or
        PixelType_Gvsp_BayerRBGG8 == enGvspPixelType or
        PixelType_Gvsp_BayerGR16 == enGvspPixelType or
        PixelType_Gvsp_BayerRG16 == enGvspPixelType or
        PixelType_Gvsp_BayerGB16 == enGvspPixelType or
        PixelType_Gvsp_BayerBG16 == enGvspPixelType or
        PixelType_Gvsp_YUV422_Packed == enGvspPixelType or
        PixelType_Gvsp_YUV422_YUYV_Packed == enGvspPixelType):
        return True
    else:
        return False


# Camera operation class
class CameraOperation:

    def __init__(self, obj_cam, st_device_list, n_connect_num=0,
                 b_open_device=False, b_start_grabbing=False,
                 h_thread_handle=None, b_thread_closed=False,
                 st_frame_info=None, b_exit=False,
                 b_save_bmp=False, b_save_jpg=False,
                 buf_save_image=None, n_save_image_size=0,
                 n_win_gui_id=0, frame_rate=0,
                 exposure_time=0, gain=0):

        self.obj_cam = obj_cam
        self.st_device_list = st_device_list
        self.n_connect_num = n_connect_num
        self.b_open_device = b_open_device
        self.b_start_grabbing = b_start_grabbing
        self.b_thread_closed = b_thread_closed
        self.st_frame_info = MV_FRAME_OUT_INFO_EX()
        self.b_exit = b_exit
        self.b_save_bmp = b_save_bmp
        self.b_save_jpg = b_save_jpg
        self.buf_save_image = buf_save_image
        self.buf_save_image_len = 0
        self.n_save_image_size = n_save_image_size
        self.h_thread_handle = h_thread_handle
        self.frame_rate = frame_rate
        self.exposure_time = exposure_time
        self.gain = gain
        self.buf_lock = threading.Lock()  # Buffer lock for grabbing and saving images

    # Open camera device
    def Open_device(self):
        if not self.b_open_device:
            if self.n_connect_num < 0:
                return MV_E_CALLORDER

            # Select device and create handle
            nConnectionNum = int(self.n_connect_num)
            stDeviceList = cast(
                self.st_device_list.pDeviceInfo[nConnectionNum],
                POINTER(MV_CC_DEVICE_INFO)).contents

            self.obj_cam = MvCamera()
            ret = self.obj_cam.MV_CC_CreateHandle(stDeviceList)
            if ret != 0:
                self.obj_cam.MV_CC_DestroyHandle()
                return ret

            ret = self.obj_cam.MV_CC_OpenDevice()
            if ret != 0:
                return ret

            print("Open device successfully!")
            self.b_open_device = True
            self.b_thread_closed = False

            # Detect optimal packet size (GigE camera only)
            if (stDeviceList.nTLayerType == MV_GIGE_DEVICE or
                stDeviceList.nTLayerType == MV_GENTL_GIGE_DEVICE):
                nPacketSize = self.obj_cam.MV_CC_GetOptimalPacketSize()
                if int(nPacketSize) > 0:
                    ret = self.obj_cam.MV_CC_SetIntValue(
                        "GevSCPSPacketSize", nPacketSize)
                    if ret != 0:
                        print("Warning: set packet size failed! ret[0x%x]" % ret)
                else:
                    print("Warning: get packet size failed! ret[0x%x]" % nPacketSize)

            stBool = c_bool(False)
            ret = self.obj_cam.MV_CC_GetBoolValue(
                "AcquisitionFrameRateEnable", stBool)
            if ret != 0:
                print("Get frame rate enable failed! ret[0x%x]" % ret)

            # Set trigger mode OFF
            ret = self.obj_cam.MV_CC_SetEnumValue(
                "TriggerMode", MV_TRIGGER_MODE_OFF)
            if ret != 0:
                print("Set trigger mode failed! ret[0x%x]" % ret)

            return MV_OK

    # Start grabbing images
    def Start_grabbing(self, winHandle):
        if not self.b_start_grabbing and self.b_open_device:
            self.b_exit = False
            ret = self.obj_cam.MV_CC_StartGrabbing()
            if ret != 0:
                return ret

            self.b_start_grabbing = True
            print("Start grabbing successfully!")

            self.h_thread_handle = threading.Thread(
                target=CameraOperation.Work_thread,
                args=(self, winHandle))
            self.h_thread_handle.start()
            self.b_thread_closed = True
            return MV_OK

        return MV_E_CALLORDER

    # Stop grabbing images
    def Stop_grabbing(self):
        if self.b_start_grabbing and self.b_open_device:
            if self.b_thread_closed:
                Stop_thread(self.h_thread_handle)
                self.b_thread_closed = False

            ret = self.obj_cam.MV_CC_StopGrabbing()
            if ret != 0:
                return ret

            print("Stop grabbing successfully!")
            self.b_start_grabbing = False
            self.b_exit = True
            return MV_OK
        else:
            return MV_E_CALLORDER

    # Close camera device
    def Close_device(self):
        if self.b_open_device:
            if self.b_thread_closed:
                Stop_thread(self.h_thread_handle)
                self.b_thread_closed = False

            ret = self.obj_cam.MV_CC_CloseDevice()
            if ret != 0:
                return ret

        # Destroy handle
        self.obj_cam.MV_CC_DestroyHandle()
        self.b_open_device = False
        self.b_start_grabbing = False
        self.b_exit = True
        print("Close device successfully!")

        return MV_OK

    # Set trigger mode
    def Set_trigger_mode(self, is_trigger_mode):
        if not self.b_open_device:
            return MV_E_CALLORDER

        if not is_trigger_mode:
            return self.obj_cam.MV_CC_SetEnumValue("TriggerMode", 0)
        else:
            ret = self.obj_cam.MV_CC_SetEnumValue("TriggerMode", 1)
            if ret != 0:
                return ret
            return self.obj_cam.MV_CC_SetEnumValue("TriggerSource", 7)

    # Execute one software trigger
    def Trigger_once(self):
        if self.b_open_device:
            return self.obj_cam.MV_CC_SetCommandValue("TriggerSoftware")

    # Get camera parameters
    def Get_parameter(self):
        if self.b_open_device:
            stFrameRate = MVCC_FLOATVALUE()
            stExposure = MVCC_FLOATVALUE()
            stGain = MVCC_FLOATVALUE()

            self.obj_cam.MV_CC_GetFloatValue(
                "AcquisitionFrameRate", stFrameRate)
            self.obj_cam.MV_CC_GetFloatValue(
                "ExposureTime", stExposure)
            self.obj_cam.MV_CC_GetFloatValue(
                "Gain", stGain)

            self.frame_rate = stFrameRate.fCurValue
            self.exposure_time = stExposure.fCurValue
            self.gain = stGain.fCurValue
            return MV_OK

    # Set camera parameters
    def Set_parameter(self, frameRate, exposureTime, gain):
        if self.b_open_device:
            self.obj_cam.MV_CC_SetEnumValue("ExposureAuto", 0)
            time.sleep(0.2)

            self.obj_cam.MV_CC_SetFloatValue(
                "ExposureTime", float(exposureTime))
            self.obj_cam.MV_CC_SetFloatValue(
                "Gain", float(gain))
            self.obj_cam.MV_CC_SetFloatValue(
                "AcquisitionFrameRate", float(frameRate))

            print("Set parameters successfully!")
            return MV_OK

    # Image grabbing thread
    def Work_thread(self, winHandle):
        stOutFrame = MV_FRAME_OUT()
        memset(byref(stOutFrame), 0, sizeof(stOutFrame))

        while True:
            ret = self.obj_cam.MV_CC_GetImageBuffer(stOutFrame, 1000)
            if ret == 0:
                self.buf_lock.acquire()

                if self.buf_save_image_len < stOutFrame.stFrameInfo.nFrameLen:
                    self.buf_save_image = (
                        c_ubyte * stOutFrame.stFrameInfo.nFrameLen)()
                    self.buf_save_image_len = stOutFrame.stFrameInfo.nFrameLen

                memmove(byref(self.st_frame_info),
                        byref(stOutFrame.stFrameInfo),
                        sizeof(MV_FRAME_OUT_INFO_EX))
                memmove(byref(self.buf_save_image),
                        stOutFrame.pBufAddr,
                        self.st_frame_info.nFrameLen)
                self.buf_lock.release()

                print("Get one frame: Width[%d], Height[%d], FrameNum[%d]"
                      % (self.st_frame_info.nWidth,
                         self.st_frame_info.nHeight,
                         self.st_frame_info.nFrameNum))

                self.obj_cam.MV_CC_FreeImageBuffer(stOutFrame)
            else:
                print("No data, ret = " + To_hex_str(ret))
                continue

            # Display image
            stDisplayParam = MV_DISPLAY_FRAME_INFO()
            memset(byref(stDisplayParam), 0, sizeof(stDisplayParam))
            stDisplayParam.hWnd = int(winHandle)
            stDisplayParam.nWidth = self.st_frame_info.nWidth
            stDisplayParam.nHeight = self.st_frame_info.nHeight
            stDisplayParam.enPixelType = self.st_frame_info.enPixelType
            stDisplayParam.pData = self.buf_save_image
            stDisplayParam.nDataLen = self.st_frame_info.nFrameLen
            self.obj_cam.MV_CC_DisplayOneFrame(stDisplayParam)

            if self.b_exit:
                break

    # Save image as JPG
    def Save_jpg(self):
        if self.buf_save_image is None:
            return

        self.buf_lock.acquire()
        file_path = str(self.st_frame_info.nFrameNum) + ".jpg"
        stSaveParam = MV_SAVE_IMAGE_TO_FILE_PARAM_EX()
        stSaveParam.enPixelType = self.st_frame_info.enPixelType
        stSaveParam.nWidth = self.st_frame_info.nWidth
        stSaveParam.nHeight = self.st_frame_info.nHeight
        stSaveParam.nDataLen = self.st_frame_info.nFrameLen
        stSaveParam.pData = cast(self.buf_save_image, POINTER(c_ubyte))
        stSaveParam.enImageType = MV_Image_Jpeg
        stSaveParam.nQuality = 80
        stSaveParam.pcImagePath = ctypes.create_string_buffer(
            file_path.encode('ascii'))
        stSaveParam.iMethodValue = 1
        ret = self.obj_cam.MV_CC_SaveImageToFileEx(stSaveParam)
        self.buf_lock.release()
        return ret

    # Save image as BMP
    def Save_Bmp(self):
        if self.buf_save_image is None:
            return

        self.buf_lock.acquire()
        file_path = str(self.st_frame_info.nFrameNum) + ".bmp"
        stSaveParam = MV_SAVE_IMAGE_TO_FILE_PARAM_EX()
        stSaveParam.enPixelType = self.st_frame_info.enPixelType
        stSaveParam.nWidth = self.st_frame_info.nWidth
        stSaveParam.nHeight = self.st_frame_info.nHeight
        stSaveParam.nDataLen = self.st_frame_info.nFrameLen
        stSaveParam.pData = cast(self.buf_save_image, POINTER(c_ubyte))
        stSaveParam.enImageType = MV_Image_Bmp
        stSaveParam.pcImagePath = ctypes.create_string_buffer(
            file_path.encode('ascii'))
        stSaveParam.iMethodValue = 1
        ret = self.obj_cam.MV_CC_SaveImageToFileEx(stSaveParam)
        self.buf_lock.release()
        return ret
