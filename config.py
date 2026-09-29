import os

SSIM_THRESHOLD = float(os.environ.get('SSIM_THRESHOLD', '0.90'))
default_model = os.path.join(os.getcwd(), "yolo26n-cls.pt")
if not os.path.exists(default_model):
    default_model = os.path.join(os.getcwd(), "yolov8n.pt")

YOLO_MODEL_PATH = os.environ.get('YOLO_MODEL_PATH', default_model)
TRAINED_IMAGES_FOLDER = os.path.join(
    os.getcwd(),
    "static",
    "Golden Libraries",
    "GoldenLibrary"
)

DEFECT_FOLDER = os.path.join(
    os.getcwd(),
    "static",
    "Golden Libraries",
    "DefectLibrary"
)
REF_THUMB_SIZE = (100, 100)
PREVIEW_SIZE = (150, 150)
KNOWN_WIDTH_CM = 5.0
FOCAL_LENGTH = 500
MIN_DISTANCE_CM = 10
MAX_DISTANCE_CM = 30
MAX_FILE_SIZE_MB = 16
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'jfif'
}
