import os
import cv2
from PIL import Image
import logging


def normalize_part_number(part_number):
    if part_number is None:
        return None
    cleaned = str(part_number).strip()
    if not cleaned:
        return None
    # Prevent path traversal while preserving the actual part number name.
    return os.path.basename(cleaned)


def ensure_part_folder(trained_folder, part_number):
    part_number = normalize_part_number(part_number)
    if not part_number:
        return None
    part_folder = os.path.join(trained_folder, part_number)
    os.makedirs(part_folder, exist_ok=True)
    logging.info(f"Created or verified part folder: {part_folder}")
    return part_folder


def get_all_images_from_subfolders(trained_folder):
    """Get ALL reference images from ALL part subfolders (used for listing/training only)."""
    file_paths = []
    if not os.path.exists(trained_folder):
        logging.warning(f"Training folder {trained_folder} does not exist")
        return file_paths
    
    for root, dirs, files in os.walk(trained_folder):
        for file in files:
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.jfif', '.tiff', '.tif', '.bmp')):
                file_paths.append(os.path.join(root, file))
    
    logging.info(f"Found {len(file_paths)} reference images in {trained_folder}")
    return file_paths


def get_images_for_part(trained_folder, part_number):
    """
    Get reference images ONLY from the folder matching the given part_number.
    This enforces strict part-number isolation during inspection.
    Returns (image_paths, part_folder_path).
    """
    if not part_number or str(part_number).strip().lower() in ("unknown", "none", "auto", ""):
        logging.warning("No valid part_number provided – cannot restrict reference images.")
        return [], None

    part_number = normalize_part_number(part_number)
    if not part_number:
        logging.warning("No valid part_number provided – cannot restrict reference images.")
        return [], None

    part_folder = os.path.join(trained_folder, part_number)

    if not os.path.exists(part_folder):
        logging.error(f"Reference folder missing for Part {part_number}: {part_folder}")
        return [], part_folder

    file_paths = []
    for file in os.listdir(part_folder):
        if file.lower().endswith(('.png', '.jpg', '.jpeg', '.jfif', '.tiff', '.tif', '.bmp')):
            file_paths.append(os.path.join(part_folder, file))

    logging.info(
        f"[Part {part_number}] Found {len(file_paths)} reference images in {part_folder}"
    )
    return file_paths, part_folder


def get_available_part_numbers(trained_folder):
    """List all part numbers (subfolder names) in the trained images folder."""
    if not os.path.exists(trained_folder):
        return []
    return [
        d for d in os.listdir(trained_folder)
        if os.path.isdir(os.path.join(trained_folder, d))
    ]


def mat_to_image(mat):
    return Image.fromarray(cv2.cvtColor(mat, cv2.COLOR_BGR2RGB))


def ensure_dir_exists(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)
        logging.info(f"Created directory: {directory}")


def get_file_size_mb(filepath):
    return os.path.getsize(filepath) / (1024 * 1024)


def is_valid_image(filepath):
    try:
        img = cv2.imread(filepath)
        return img is not None
    except Exception:
        return False


def create_inspection_folder(base_dir="static/uploads", prefix="inspection"):
    """
    Create a sequentially numbered inspection folder under the upload root.
    Folder names are built using the supplied prefix, e.g. 48290_1, 48290_2.
    Returns the full path to the new inspection folder.
    """
    prefix = normalize_part_number(prefix) or "inspection"
    from pathlib import Path
    import uuid

    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    existing_numbers = []
    for entry in base_path.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith(prefix + "_"):
            suffix = name.split("_", 1)[1]
            if suffix.isdigit():
                existing_numbers.append(int(suffix))

    next_number = max(existing_numbers, default=0) + 1
    folder_name = f"{prefix}_{next_number}"
    folder_path = base_path / folder_name

    counter = 1
    while folder_path.exists():
        folder_path = base_path / f"{prefix}_{next_number}_{counter}"
        counter += 1
        if counter > 1000:
            folder_path = base_path / f"{prefix}_{next_number}_{uuid.uuid4().hex}"
            break

    folder_path.mkdir(parents=True, exist_ok=False)
    logging.info(f"Created inspection folder: {folder_path}")
    return str(folder_path)


def get_next_image_name(inspection_folder, cam_id):
    """
    Return the next sequential image filename for a camera inside the current inspection folder.
    """
    if not os.path.isdir(inspection_folder):
        raise ValueError(f"Inspection folder does not exist: {inspection_folder}")

    existing_indexes = []
    prefix = f"{cam_id}_"
    for filename in os.listdir(inspection_folder):
        if not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif')):
            continue
        if not filename.startswith(prefix):
            continue

        index_part = os.path.splitext(filename[len(prefix):])[0]
        if index_part.isdigit():
            existing_indexes.append(int(index_part))

    next_index = max(existing_indexes, default=0) + 1
    return f"{cam_id}_{next_index}.jpg"


def cleanup_uploads(upload_folder, max_images=10):
    if not os.path.exists(upload_folder):
        return

    import shutil

    # Get all entries in the upload folder
    entries = []
    try:
        for entry in os.scandir(upload_folder):
            # We only care about directories, or files that are images
            if entry.is_dir():
                entries.append((entry.path, True, os.path.getmtime(entry.path)))
            elif entry.is_file() and entry.name.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif')):
                entries.append((entry.path, False, os.path.getmtime(entry.path)))
    except Exception as e:
        logging.error(f"Error scanning upload folder for cleanup: {e}")
        return

    # Sort entries by modification time (oldest first)
    entries.sort(key=lambda x: x[2])

    # Let's count total images currently in the uploads folder
    def count_total_images():
        total = 0
        image_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif')
        try:
            for entry in os.scandir(upload_folder):
                if entry.is_dir():
                    for root, dirs, files in os.walk(entry.path):
                        total += sum(1 for f in files if f.lower().endswith(image_extensions))
                elif entry.is_file() and entry.name.lower().endswith(image_extensions):
                    total += 1
        except Exception:
            pass
        return total

    # Keep deleting oldest entries (files or directories) until total images < max_images
    while count_total_images() >= max_images and entries:
        oldest_path, is_dir, _ = entries.pop(0)
        try:
            if is_dir:
                shutil.rmtree(oldest_path)
                logging.info(f"[Cleanup] Cleaned up old inspection folder: {oldest_path}")
            else:
                os.remove(oldest_path)
                logging.info(f"[Cleanup] Cleaned up old image file: {oldest_path}")
        except Exception as e:
            logging.error(f"[Cleanup] Failed to delete {oldest_path}: {e}")


