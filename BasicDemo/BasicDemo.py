# -*- coding: utf-8 -*-
import sys
from PyQt5.QtWidgets import *
from CamOperation_class import CameraOperation
from MvCameraControl_class import *
from MvErrorDefine_const import *
from CameraParams_header import *
from PyUICBasicDemo import Ui_MainWindow
import ctypes


# Get selected device index by parsing the string between [ ]
def TxtWrapBy(start_str, end, all):
    start = all.find(start_str)
    if start >= 0:
        start += len(start_str)
        end = all.find(end, start)
        if end >= 0:
            return all[start:end].strip()


# Convert returned error code to hexadecimal string
def ToHexStr(num):
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


if __name__ == "__main__":

    # Initialize SDK
    MvCamera.MV_CC_Initialize()

    global deviceList
    deviceList = MV_CC_DEVICE_INFO_LIST()
    global cam
    cam = MvCamera()
    global nSelCamIndex
    nSelCamIndex = 0
    global obj_cam_operation
    obj_cam_operation = 0
    global isOpen
    isOpen = False
    global isGrabbing
    isGrabbing = False
    global isCalibMode   # Calibration mode (get raw image)
    isCalibMode = True

    # Bind dropdown selection to device index
    def xFunc(event):
        global nSelCamIndex
        nSelCamIndex = TxtWrapBy("[", "]", ui.ComboDevices.get())

    # Decode characters safely from ctypes char array
    def decoding_char(ctypes_char_array):
        """
        Safely decode string from ctypes char array.
        Works with Python 2.x / 3.x and 32/64-bit systems.
        """
        byte_str = memoryview(ctypes_char_array).tobytes()

        # Truncate at first null character
        null_index = byte_str.find(b'\x00')
        if null_index != -1:
            byte_str = byte_str[:null_index]

        # Try multiple encodings
        for encoding in ['gbk', 'utf-8', 'latin-1']:
            try:
                return byte_str.decode(encoding)
            except UnicodeDecodeError:
                continue

        # Fallback decoding
        return byte_str.decode('latin-1', errors='replace')

    # Enumerate connected cameras
    def enum_devices():
        global deviceList
        global obj_cam_operation

        deviceList = MV_CC_DEVICE_INFO_LIST()
        n_layer_type = (MV_GIGE_DEVICE | MV_USB_DEVICE | MV_GENTL_CAMERALINK_DEVICE
                        | MV_GENTL_CXP_DEVICE | MV_GENTL_XOF_DEVICE)

        ret = MvCamera.MV_CC_EnumDevices(n_layer_type, deviceList)
        if ret != 0:
            QMessageBox.warning(mainWindow, "Error",
                                "Enum devices failed! ret = " + ToHexStr(ret),
                                QMessageBox.Ok)
            return ret

        if deviceList.nDeviceNum == 0:
            QMessageBox.warning(mainWindow, "Info", "No devices found", QMessageBox.Ok)
            return ret

        print("Found %d devices!" % deviceList.nDeviceNum)

        devList = []

        for i in range(deviceList.nDeviceNum):
            mvcc_dev_info = cast(deviceList.pDeviceInfo[i],
                                 POINTER(MV_CC_DEVICE_INFO)).contents

            # GigE camera
            if mvcc_dev_info.nTLayerType in (MV_GIGE_DEVICE, MV_GENTL_GIGE_DEVICE):
                user_defined_name = decoding_char(
                    mvcc_dev_info.SpecialInfo.stGigEInfo.chUserDefinedName)
                model_name = decoding_char(
                    mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName)

                ip = mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp
                ip_str = "%d.%d.%d.%d" % (
                    (ip >> 24) & 0xff,
                    (ip >> 16) & 0xff,
                    (ip >> 8) & 0xff,
                    ip & 0xff)

                devList.append(
                    f"[{i}]GigE: {user_defined_name} {model_name} ({ip_str})"
                )

            # USB camera
            elif mvcc_dev_info.nTLayerType == MV_USB_DEVICE:
                user_defined_name = decoding_char(
                    mvcc_dev_info.SpecialInfo.stUsb3VInfo.chUserDefinedName)
                model_name = decoding_char(
                    mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName)

                serial = ""
                for per in mvcc_dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber:
                    if per == 0:
                        break
                    serial += chr(per)

                devList.append(
                    f"[{i}]USB: {user_defined_name} {model_name} ({serial})"
                )

        ui.ComboDevices.clear()
        ui.ComboDevices.addItems(devList)
        ui.ComboDevices.setCurrentIndex(0)

    # Open selected camera
    def open_device():
        global isOpen, obj_cam_operation, nSelCamIndex

        if isOpen:
            QMessageBox.warning(mainWindow, "Error", "Camera already running!", QMessageBox.Ok)
            return MV_E_CALLORDER

        nSelCamIndex = ui.ComboDevices.currentIndex()
        if nSelCamIndex < 0:
            QMessageBox.warning(mainWindow, "Error", "Please select a camera!", QMessageBox.Ok)
            return MV_E_CALLORDER

        obj_cam_operation = CameraOperation(cam, deviceList, nSelCamIndex)
        ret = obj_cam_operation.Open_device()

        if ret != 0:
            QMessageBox.warning(mainWindow, "Error",
                                "Open device failed ret: " + ToHexStr(ret),
                                QMessageBox.Ok)
            isOpen = False
        else:
            set_continue_mode()
            get_param()
            isOpen = True
            enable_controls()

    # Start image grabbing
    def start_grabbing():
        global isGrabbing
        ret = obj_cam_operation.Start_grabbing(ui.widgetDisplay.winId())
        if ret != 0:
            QMessageBox.warning(mainWindow, "Error",
                                "Start grabbing failed ret: " + ToHexStr(ret),
                                QMessageBox.Ok)
        else:
            isGrabbing = True
            enable_controls()

    # Stop image grabbing
    def stop_grabbing():
        global isGrabbing
        ret = obj_cam_operation.Stop_grabbing()
        if ret != 0:
            QMessageBox.warning(mainWindow, "Error",
                                "Stop grabbing failed ret: " + ToHexStr(ret),
                                QMessageBox.Ok)
        else:
            isGrabbing = False
            enable_controls()

    # Close camera device
    def close_device():
        global isOpen, isGrabbing
        if isOpen:
            obj_cam_operation.Close_device()
            isOpen = False
        isGrabbing = False
        enable_controls()

    # Set continuous acquisition mode
    def set_continue_mode():
        ret = obj_cam_operation.Set_trigger_mode(False)
        if ret != 0:
            QMessageBox.warning(mainWindow, "Error",
                                "Set continuous mode failed ret: " + ToHexStr(ret),
                                QMessageBox.Ok)
        else:
            ui.radioContinueMode.setChecked(True)
            ui.radioTriggerMode.setChecked(False)
            ui.bnSoftwareTrigger.setEnabled(False)

    # Set software trigger mode
    def set_software_trigger_mode():
        ret = obj_cam_operation.Set_trigger_mode(True)
        if ret != 0:
            QMessageBox.warning(mainWindow, "Error",
                                "Set trigger mode failed ret: " + ToHexStr(ret),
                                QMessageBox.Ok)
        else:
            ui.radioContinueMode.setChecked(False)
            ui.radioTriggerMode.setChecked(True)
            ui.bnSoftwareTrigger.setEnabled(isGrabbing)

    # Execute one software trigger
    def trigger_once():
        ret = obj_cam_operation.Trigger_once()
        if ret != 0:
            QMessageBox.warning(mainWindow, "Error",
                                "Trigger failed ret: " + ToHexStr(ret),
                                QMessageBox.Ok)

    # Save image as BMP
    def save_bmp():
        ret = obj_cam_operation.Save_Bmp()
        if ret != MV_OK:
            QMessageBox.warning(mainWindow, "Error",
                                "Save BMP failed ret: " + ToHexStr(ret),
                                QMessageBox.Ok)
        else:
            print("Image saved successfully")

    # Check if string is float
    def is_float(value):
        try:
            float(value)
            return True
        except ValueError:
            return False

    # Get camera parameters
    def get_param():
        ret = obj_cam_operation.Get_parameter()
        if ret != MV_OK:
            QMessageBox.warning(mainWindow, "Error",
                                "Get parameter failed ret: " + ToHexStr(ret),
                                QMessageBox.Ok)
        else:
            ui.edtExposureTime.setText(f"{obj_cam_operation.exposure_time:.2f}")
            ui.edtGain.setText(f"{obj_cam_operation.gain:.2f}")
            ui.edtFrameRate.setText(f"{obj_cam_operation.frame_rate:.2f}")

    # Set camera parameters
    def set_param():
        frame_rate = ui.edtFrameRate.text()
        exposure = ui.edtExposureTime.text()
        gain = ui.edtGain.text()

        if not (is_float(frame_rate) and is_float(exposure) and is_float(gain)):
            QMessageBox.warning(mainWindow, "Error",
                                "Invalid parameter value",
                                QMessageBox.Ok)
            return MV_E_PARAMETER

        ret = obj_cam_operation.Set_parameter(frame_rate, exposure, gain)
        if ret != MV_OK:
            QMessageBox.warning(mainWindow, "Error",
                                "Set parameter failed ret: " + ToHexStr(ret),
                                QMessageBox.Ok)

        return MV_OK

    # Enable/disable UI controls based on state
    def enable_controls():
        ui.groupGrab.setEnabled(isOpen)
        ui.groupParam.setEnabled(isOpen)

        ui.bnOpen.setEnabled(not isOpen)
        ui.bnClose.setEnabled(isOpen)
        ui.bnStart.setEnabled(isOpen and not isGrabbing)
        ui.bnStop.setEnabled(isOpen and isGrabbing)
        ui.bnSoftwareTrigger.setEnabled(isGrabbing and ui.radioTriggerMode.isChecked())
        ui.bnSaveImage.setEnabled(isOpen and isGrabbing)

    # Initialize application and bind UI events
    app = QApplication(sys.argv)
    mainWindow = QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(mainWindow)

    ui.bnEnum.clicked.connect(enum_devices)
    ui.bnOpen.clicked.connect(open_device)
    ui.bnClose.clicked.connect(close_device)
    ui.bnStart.clicked.connect(start_grabbing)
    ui.bnStop.clicked.connect(stop_grabbing)
    ui.bnSoftwareTrigger.clicked.connect(trigger_once)
    ui.radioTriggerMode.clicked.connect(set_software_trigger_mode)
    ui.radioContinueMode.clicked.connect(set_continue_mode)
    ui.bnGetParam.clicked.connect(get_param)
    ui.bnSetParam.clicked.connect(set_param)
    ui.bnSaveImage.clicked.connect(save_bmp)

    mainWindow.show()
    app.exec_()

    close_device()

    # Finalize SDK
    MvCamera.MV_CC_Finalize()
    sys.exit()
