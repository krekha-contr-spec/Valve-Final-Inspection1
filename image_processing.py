import cv2
import numpy as np
import os
import logging
from typing import Dict, List, Optional, Tuple, Any

from config import TRAINED_IMAGES_FOLDER
from utils import (
    get_all_images_from_subfolders,
    get_images_for_part,
    get_available_part_numbers,
)


# ================================================================
# CONFIGURATION
# ================================================================

IMAGE_SIZE = (512, 512)

CANNY_LOW = 30
CANNY_HIGH = 100

EDGE_MATCH_THRESHOLD = float(
    os.environ.get("EDGE_THRESHOLD", "0.75")
)

WRONG_PART_MIN_SCORE = 0.30

# Defect matching threshold.
DEFECT_MATCH_THRESHOLD = float(
    os.environ.get("DEFECT_MATCH_THRESHOLD", "0.38")
)

# Minimum defect region area.
MIN_DEFECT_AREA = int(
    os.environ.get("MIN_DEFECT_AREA", "80")
)

# ================================================================
# STANDARD DEFECT CLASSES
# ================================================================

DEFECT_CLASSES = [
    "Bend_Damage",
    "Crack_Damage",
    "Discoloration_Damage",
    "End_Chamfer",
    "Face_Damage",
    "Groove_Damage",
    "Head_Damage",
    "Neck_Damage",
    "Radius_Damage",
    "Scratch",
    "Seat_Damage",
    "Stem_Damage",
    "Tip_Damage",
]


IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".jfif",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
)


# ================================================================
# LOGGING
# ================================================================

logger = logging.getLogger(__name__)


# ================================================================
# DIRECTORY HELPERS
# ================================================================

def ensure_dir_exists(path: str) -> None:
    """
    Create directory if it does not exist.
    """

    if not path:
        return

    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def _normalise_name(name: str) -> str:
    """
    Normalize folder names so small naming differences are accepted.

    Example:
        Bent_Valve      -> bentvalve
        Bend_Damage     -> benddamage
        bend-damage     -> benddamage
    """

    return "".join(
        ch.lower()
        for ch in str(name)
        if ch.isalnum()
    )


def _canonical_defect_name(name: str) -> Optional[str]:
    """
    Convert different possible names to the project's
    standard defect names.
    """

    normalized = _normalise_name(name)

    aliases = {
        "benddamage": "Bend_Damage",
        "bentvalve": "Bend_Damage",
        "bent": "Bend_Damage",

        "crackdamage": "Crack_Damage",
        "crack": "Crack_Damage",

        "discolorationdamage": "Discoloration_Damage",
        "discoloration": "Discoloration_Damage",

        "endchamfer": "End_Chamfer",
        "endchamferdamage": "End_Chamfer",

        "facedamage": "Face_Damage",
        "face": "Face_Damage",

        "groovedamage": "Groove_Damage",
        "groove": "Groove_Damage",

        "headdamage": "Head_Damage",
        "head": "Head_Damage",

        "neckdamage": "Neck_Damage",
        "neck": "Neck_Damage",

        "radiusdamage": "Radius_Damage",
        "radius": "Radius_Damage",

        "scratch": "Scratch",
        "scratchdamage": "Scratch",

        "seatdamage": "Seat_Damage",
        "seat": "Seat_Damage",

        "stemdamage": "Stem_Damage",
        "stem": "Stem_Damage",

        "tipdamage": "Tip_Damage",
        "tip": "Tip_Damage",
        "tipend": "Tip_Damage",
    }

    return aliases.get(normalized)


# ================================================================
# FIND DEFECT LIBRARY
# ================================================================

def _contains_defect_folders(path: str) -> bool:
    """
    Check whether a directory contains one or more
    standard defect folders.
    """

    if not path:
        return False

    if not os.path.isdir(path):
        return False

    try:
        names = os.listdir(path)
    except Exception:
        return False

    found = 0

    for name in names:

        if not os.path.isdir(
            os.path.join(path, name)
        ):
            continue

        if _canonical_defect_name(name):
            found += 1

    return found >= 1


def find_defect_library_roots() -> List[str]:
    """
    Search common project locations for the defect library.

    This supports structures such as:

        dataset/
            Bend_Damage/
            Crack_Damage/
            ...

        GoldenLibrary/
            Bend_Damage/
            ...

        defect_library/
            Bend_Damage/
            ...
    """

    roots: List[str] = []

    project_root = os.path.abspath(
        os.path.dirname(__file__)
    )

    current_dir = os.getcwd()

    candidates = [
        project_root,
        current_dir,

        os.path.join(
            project_root,
            "dataset"
        ),

        os.path.join(
            project_root,
            "Dataset"
        ),

        os.path.join(
            project_root,
            "GoldenLibrary"
        ),

        os.path.join(
            project_root,
            "Golden_Library"
        ),

        os.path.join(
            project_root,
            "DefectLibrary"
        ),

        os.path.join(
            project_root,
            "defect_library"
        ),

        os.path.join(
            project_root,
            "dataset",
            "defects"
        ),

        os.path.join(
            project_root,
            "dataset",
            "defect_library"
        ),

        os.path.dirname(
            os.path.abspath(
                TRAINED_IMAGES_FOLDER
            )
        ),

        TRAINED_IMAGES_FOLDER,
    ]

    for path in candidates:

        path = os.path.abspath(path)

        if path in roots:
            continue

        if _contains_defect_folders(path):
            roots.append(path)

    # Also check one directory deeper.
    search_parents = list(roots)

    for parent in search_parents:

        try:
            for name in os.listdir(parent):

                child = os.path.join(
                    parent,
                    name
                )

                if not os.path.isdir(child):
                    continue

                if child in roots:
                    continue

                if _contains_defect_folders(child):
                    roots.append(child)

        except Exception:
            pass

    return roots


def find_defect_library() -> Optional[str]:
    """
    Return the first valid defect library root.
    """

    roots = find_defect_library_roots()

    if not roots:

        logger.warning(
            "No defect library found. "
            "Expected folders: %s",
            ", ".join(DEFECT_CLASSES)
        )

        return None

    logger.info(
        "Defect library found: %s",
        roots[0]
    )

    return roots[0]


# ================================================================
# DEFECT LIBRARY IMAGES
# ================================================================

def get_defect_library_images(
    library_root: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Build:

        {
            "Bend_Damage": [...],
            "Crack_Damage": [...],
            ...
        }
    """

    if library_root is None:
        library_root = find_defect_library()

    result: Dict[str, List[str]] = {
        defect: []
        for defect in DEFECT_CLASSES
    }

    if not library_root:
        return result

    try:

        for folder_name in os.listdir(
            library_root
        ):

            folder_path = os.path.join(
                library_root,
                folder_name
            )

            if not os.path.isdir(folder_path):
                continue

            defect_name = _canonical_defect_name(
                folder_name
            )

            if not defect_name:
                continue

            for root, _, files in os.walk(
                folder_path
            ):

                for filename in files:

                    if not filename.lower().endswith(
                        IMAGE_EXTENSIONS
                    ):
                        continue

                    full_path = os.path.join(
                        root,
                        filename
                    )

                    result[
                        defect_name
                    ].append(full_path)

    except Exception as e:

        logger.exception(
            "Failed to read defect library: %s",
            e
        )

    for defect_name, images in result.items():

        logger.info(
            "Defect library: %s = %d images",
            defect_name,
            len(images)
        )

    return result


# ================================================================
# EDGE DETECTION
# ================================================================

def detect_edges(image: np.ndarray) -> np.ndarray:

    if image is None:
        raise ValueError(
            "detect_edges received None image"
        )

    if len(image.shape) == 3:
        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY
        )
    else:
        gray = image.copy()

    gray = cv2.resize(
        gray,
        IMAGE_SIZE
    )

    # Apply CLAHE to equalize histogram and enhance edge clarity under varying lighting
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    blurred = cv2.GaussianBlur(
        gray,
        (5, 5),
        0
    )

    edges = cv2.Canny(
        blurred,
        CANNY_LOW,
        CANNY_HIGH
    )

    kernel = np.ones(
        (3, 3),
        np.uint8
    )

    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    return edges


# ================================================================
# FEATURE EXTRACTION
# ================================================================

def extract_edge_features(
    edges: np.ndarray,
) -> Optional[Dict[str, Any]]:

    contours, _ = cv2.findContours(
        edges.copy(),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return None

    largest_contour = max(
        contours,
        key=cv2.contourArea
    )

    area = cv2.contourArea(
        largest_contour
    )

    perimeter = cv2.arcLength(
        largest_contour,
        True
    )

    hull = cv2.convexHull(
        largest_contour
    )

    hull_area = cv2.contourArea(
        hull
    )

    solidity = (
        area / hull_area
        if hull_area > 0
        else 0
    )

    x, y, w, h = cv2.boundingRect(
        largest_contour
    )

    aspect_ratio = (
        float(w) / h
        if h > 0
        else 0
    )

    extent = (
        area / (w * h)
        if w * h > 0
        else 0
    )

    moments = cv2.moments(
        largest_contour
    )

    hu_moments = cv2.HuMoments(
        moments
    ).flatten()

    return {
        "area": area,
        "perimeter": perimeter,
        "solidity": solidity,
        "aspect_ratio": aspect_ratio,
        "extent": extent,
        "hu_moments": hu_moments.tolist(),
    }


# ================================================================
# FEATURE COMPARISON
# ================================================================

def compare_edge_features(
    test_features: Optional[Dict[str, Any]],
    ref_features: Optional[Dict[str, Any]],
    debug_label: Optional[str] = None,
) -> float:

    if not test_features or not ref_features:
        return 0.0

    test_area = max(
        float(test_features["area"]),
        1e-6
    )

    ref_area = max(
        float(ref_features["area"]),
        1e-6
    )

    area_ratio = (
        min(test_area, ref_area)
        /
        max(test_area, ref_area)
    )

    test_perimeter = max(
        float(test_features["perimeter"]),
        1e-6
    )

    ref_perimeter = max(
        float(ref_features["perimeter"]),
        1e-6
    )

    perimeter_ratio = (
        min(
            test_perimeter,
            ref_perimeter
        )
        /
        max(
            test_perimeter,
            ref_perimeter
        )
    )

    solidity_diff = max(
        0.0,
        1.0 -
        abs(
            test_features["solidity"]
            -
            ref_features["solidity"]
        )
    )

    aspect_diff = max(
        0.0,
        1.0 -
        min(
            abs(
                test_features["aspect_ratio"]
                -
                ref_features["aspect_ratio"]
            ),
            1.0
        )
    )

    extent_diff = max(
        0.0,
        1.0 -
        abs(
            test_features["extent"]
            -
            ref_features["extent"]
        )
    )

    test_hu = np.array(
        test_features["hu_moments"],
        dtype=np.float64
    )

    ref_hu = np.array(
        ref_features["hu_moments"],
        dtype=np.float64
    )

    test_hu_log = (
        np.sign(test_hu)
        *
        np.log10(
            np.abs(test_hu) + 1e-10
        )
    )

    ref_hu_log = (
        np.sign(ref_hu)
        *
        np.log10(
            np.abs(ref_hu) + 1e-10
        )
    )

    hu_distance = np.sum(
        np.abs(
            test_hu_log -
            ref_hu_log
        )
    )

    hu_score = max(
        0.0,
        1.0 -
        hu_distance / 10.0
    )

    score = (
        0.20 * area_ratio
        +
        0.15 * perimeter_ratio
        +
        0.15 * solidity_diff
        +
        0.15 * aspect_diff
        +
        0.10 * extent_diff
        +
        0.25 * hu_score
    )

    if debug_label:

        logger.info(
            "[Score: %s] "
            "area=%.3f perimeter=%.3f "
            "solidity=%.3f aspect=%.3f "
            "extent=%.3f hu=%.3f "
            "total=%.4f",
            debug_label,
            area_ratio,
            perimeter_ratio,
            solidity_diff,
            aspect_diff,
            extent_diff,
            hu_score,
            score,
        )

    return float(score)


# ================================================================
# IMAGE NORMALIZATION
# ================================================================

def _prepare_image(
    image: np.ndarray,
    size: Tuple[int, int] = (256, 256),
) -> Optional[np.ndarray]:

    if image is None:
        return None

    try:

        image = cv2.resize(
            image,
            size,
            interpolation=cv2.INTER_AREA
        )

        return image

    except Exception:
        return None


def _gray_image(
    image: np.ndarray,
    size: Tuple[int, int] = (256, 256),
) -> Optional[np.ndarray]:

    prepared = _prepare_image(
        image,
        size
    )

    if prepared is None:
        return None

    if len(prepared.shape) == 3:

        return cv2.cvtColor(
            prepared,
            cv2.COLOR_BGR2GRAY
        )

    return prepared


# ================================================================
# HISTOGRAM FEATURE
# ================================================================

def _color_histogram(
    image: np.ndarray,
) -> Optional[np.ndarray]:

    prepared = _prepare_image(
        image
    )

    if prepared is None:
        return None

    hsv = cv2.cvtColor(
        prepared,
        cv2.COLOR_BGR2HSV
    )

    hist = cv2.calcHist(
        [hsv],
        [0, 1],
        None,
        [30, 32],
        [0, 180, 0, 256],
    )

    cv2.normalize(
        hist,
        hist
    )

    return hist.flatten()


def _histogram_similarity(
    image_a: np.ndarray,
    image_b: np.ndarray,
) -> float:

    hist_a = _color_histogram(
        image_a
    )

    hist_b = _color_histogram(
        image_b
    )

    if hist_a is None or hist_b is None:
        return 0.0

    score = cv2.compareHist(
        hist_a.astype(np.float32),
        hist_b.astype(np.float32),
        cv2.HISTCMP_CORREL,
    )

    return float(
        max(
            0.0,
            min(
                1.0,
                (score + 1.0) / 2.0
            )
        )
    )


# ================================================================
# EDGE HISTOGRAM
# ================================================================

def _edge_similarity(
    image_a: np.ndarray,
    image_b: np.ndarray,
) -> float:

    edges_a = detect_edges(
        image_a
    )

    edges_b = detect_edges(
        image_b
    )

    score = cv2.matchTemplate(
        edges_a,
        edges_b,
        cv2.TM_CCOEFF_NORMED
    )

    if score.size == 0:
        return 0.0

    value = float(
        np.max(score)
    )

    return max(
        0.0,
        min(
            1.0,
            (value + 1.0) / 2.0
        )
    )


# ================================================================
# GRAYSCALE STRUCTURE SIMILARITY
# ================================================================

def _structure_similarity(
    image_a: np.ndarray,
    image_b: np.ndarray,
) -> float:

    gray_a = _gray_image(
        image_a
    )

    gray_b = _gray_image(
        image_b
    )

    if gray_a is None or gray_b is None:
        return 0.0

    gray_a = cv2.GaussianBlur(
        gray_a,
        (5, 5),
        0
    )

    gray_b = cv2.GaussianBlur(
        gray_b,
        (5, 5),
        0
    )

    diff = cv2.absdiff(
        gray_a,
        gray_b
    )

    mse = float(
        np.mean(
            diff.astype(np.float32) ** 2
        )
    )

    similarity = 1.0 - (
        mse / (255.0 ** 2)
    )

    return float(
        max(
            0.0,
            min(
                1.0,
                similarity
            )
        )
    )


# ================================================================
# ORB FEATURE SIMILARITY
# ================================================================

def _orb_similarity(
    image_a: np.ndarray,
    image_b: np.ndarray,
) -> float:

    gray_a = _gray_image(
        image_a
    )

    gray_b = _gray_image(
        image_b
    )

    if gray_a is None or gray_b is None:
        return 0.0

    try:

        orb = cv2.ORB_create(  # type: ignore[attr-defined]
            nfeatures=500
        )

        kp_a, des_a = orb.detectAndCompute(
            gray_a,
            None
        )

        kp_b, des_b = orb.detectAndCompute(
            gray_b,
            None
        )

        if (
            des_a is None
            or
            des_b is None
            or
            len(des_a) < 2
            or
            len(des_b) < 2
        ):
            return 0.0

        matcher = cv2.BFMatcher(
            cv2.NORM_HAMMING,
            crossCheck=False
        )

        matches = matcher.knnMatch(
            des_a,
            des_b,
            k=2
        )

        good_matches = []

        for pair in matches:

            if len(pair) < 2:
                continue

            m, n = pair

            if m.distance < 0.75 * n.distance:
                good_matches.append(m)

        denominator = max(
            1,
            min(
                len(kp_a),
                len(kp_b)
            )
        )

        score = (
            len(good_matches)
            /
            denominator
        )

        return float(
            max(
                0.0,
                min(
                    1.0,
                    score * 4.0
                )
            )
        )

    except Exception:

        return 0.0


# ================================================================
# GENERAL IMAGE SIMILARITY
# ================================================================

def compare_defect_images(
    test_image: np.ndarray,
    reference_image: np.ndarray,
) -> float:
    """
    Compare a defect image against one reference image.

    Uses multiple visual characteristics:

        25% structure
        25% edges
        20% color/texture histogram
        30% ORB visual features
    """

    structure_score = _structure_similarity(
        test_image,
        reference_image
    )

    edge_score = _edge_similarity(
        test_image,
        reference_image
    )

    color_score = _histogram_similarity(
        test_image,
        reference_image
    )

    orb_score = _orb_similarity(
        test_image,
        reference_image
    )

    score = (
        0.25 * structure_score
        +
        0.25 * edge_score
        +
        0.20 * color_score
        +
        0.30 * orb_score
    )

    return float(
        max(
            0.0,
            min(
                1.0,
                score
            )
        )
    )


# ================================================================
# DEFECT REGION DETECTION
# ================================================================

def find_defect_regions(
    test_img: np.ndarray,
    ref_img: np.ndarray,
    min_area: int = MIN_DEFECT_AREA,
) -> List[np.ndarray]:

    test_edges = detect_edges(
        test_img
    )

    ref_edges = detect_edges(
        ref_img
    )

    diff = cv2.absdiff(
        test_edges,
        ref_edges
    )

    _, thresh = cv2.threshold(
        diff,
        40,
        255,
        cv2.THRESH_BINARY
    )

    kernel = np.ones(
        (5, 5),
        np.uint8
    )

    thresh = cv2.morphologyEx(
        thresh,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2
    )

    thresh = cv2.dilate(
        thresh,
        kernel,
        iterations=1
    )

    contours, _ = cv2.findContours(
        thresh,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    regions = [
        contour
        for contour in contours
        if cv2.contourArea(contour) > min_area
    ]

    regions.sort(
        key=cv2.contourArea,
        reverse=True
    )

    return regions


# ================================================================
# DRAW DEFECT REGIONS
# ================================================================

def draw_defect_regions(
    test_img: np.ndarray,
    regions: List[np.ndarray],
) -> np.ndarray:

    marked_img = cv2.resize(
        test_img.copy(),
        IMAGE_SIZE
    )

    for index, cnt in enumerate(
        regions,
        start=1
    ):

        x, y, w, h = cv2.boundingRect(
            cnt
        )

        cv2.rectangle(
            marked_img,
            (x, y),
            (x + w, y + h),
            (0, 0, 255),
            2
        )

        cv2.putText(
            marked_img,
            f"Defect {index}",
            (x, max(20, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )

    return marked_img


def mark_defect_area(
    test_img: np.ndarray,
    ref_img: np.ndarray,
) -> np.ndarray:

    regions = find_defect_regions(
        test_img,
        ref_img
    )

    return draw_defect_regions(
        test_img,
        regions
    )


# ================================================================
# CROP DEFECT REGION
# ================================================================

def _crop_region(
    image: np.ndarray,
    contour: np.ndarray,
    padding: int = 15,
) -> Optional[np.ndarray]:

    if image is None or contour is None:
        return None

    image = cv2.resize(
        image,
        IMAGE_SIZE
    )

    x, y, w, h = cv2.boundingRect(
        contour
    )

    x1 = max(
        0,
        x - padding
    )

    y1 = max(
        0,
        y - padding
    )

    x2 = min(
        image.shape[1],
        x + w + padding
    )

    y2 = min(
        image.shape[0],
        y + h + padding
    )

    crop = image[
        y1:y2,
        x1:x2
    ]

    if crop.size == 0:
        return None

    return crop


# ================================================================
# DEFECT LIBRARY CLASSIFIER
# ================================================================

def classify_against_defect_library(
    test_img: np.ndarray,
    regions: List[np.ndarray],
    library: Dict[str, List[str]],
) -> Tuple[str, float]:
    """
    Compare detected defect regions against every defect class.

    Returns:

        defect_name
        confidence

    The classifier does NOT stop at Bend_Damage.

    Every available defect folder is evaluated.
    """

    if not regions:

        return "Unknown_Defect", 0.0

    # Use up to 3 largest regions.
    candidate_regions = regions[:3]

    best_class = "Unknown_Defect"
    best_score = 0.0

    class_scores: Dict[str, float] = {}

    for defect_name in DEFECT_CLASSES:

        reference_paths = library.get(
            defect_name,
            []
        )

        if not reference_paths:
            continue

        defect_best_score = 0.0

        for contour in candidate_regions:

            crop = _crop_region(
                test_img,
                contour
            )

            if crop is None:
                continue

            for ref_path in reference_paths:

                ref_img = cv2.imread(
                    ref_path
                )

                if ref_img is None:
                    continue

                score = compare_defect_images(
                    crop,
                    ref_img
                )

                if score > defect_best_score:

                    defect_best_score = score

                if score > best_score:

                    best_score = score
                    best_class = defect_name

        class_scores[
            defect_name
        ] = defect_best_score

    # Logging is very useful when tuning classification.
    if class_scores:

        ranking = sorted(
            class_scores.items(),
            key=lambda item: item[1],
            reverse=True
        )

        logger.info(
            "Defect ranking:"
        )

        for name, score in ranking[:5]:

            logger.info(
                "    %-25s %.4f",
                name,
                score
            )

    if best_score < DEFECT_MATCH_THRESHOLD:

        logger.warning(
            "No defect class passed threshold. "
            "Best=%s score=%.4f threshold=%.4f",
            best_class,
            best_score,
            DEFECT_MATCH_THRESHOLD,
        )

        return (
            "Unknown_Defect",
            best_score
        )

    return (
        best_class,
        best_score
    )


# ================================================================
# FALLBACK HEURISTIC
# ================================================================

ZONE_MAP = [
    (0.10, "Head_Damage"),
    (0.20, "Face_Damage"),
    (0.30, "Seat_Damage"),
    (0.40, "Neck_Damage"),
    (0.75, "Stem_Damage"),
    (0.85, "Groove_Damage"),
    (0.93, "End_Chamfer"),
    (1.01, "Tip_Damage"),
]


def _zone_for_y(
    y_frac: float,
) -> str:

    for boundary, label in ZONE_MAP:

        if y_frac <= boundary:
            return label

    return "Tip_Damage"


def _fallback_defect_classification(
    test_img: np.ndarray,
    ref_img: np.ndarray,
    regions: List[np.ndarray],
) -> str:
    """
    Used only when the defect library is unavailable.

    This is NOT the main classifier.
    """

    if not regions:

        return "Unknown_Defect"

    largest = regions[0]

    x, y, w, h = cv2.boundingRect(
        largest
    )

    frame_w, frame_h = IMAGE_SIZE

    area_frac = (
        (w * h)
        /
        float(
            frame_w * frame_h
        )
    )

    y_center_frac = (
        (y + h / 2.0)
        /
        frame_h
    )

    aspect = (
        max(w, h)
        /
        max(
            1.0,
            min(w, h)
        )
    )

    contour_area = cv2.contourArea(
        largest
    )

    solidity = (
        contour_area
        /
        max(
            1.0,
            w * h
        )
    )

    # Long thin defect.
    if (
        aspect >= 4.0
        and
        area_frac <= 0.03
    ):

        if solidity >= 0.55:
            return "Scratch"

        return "Crack_Damage"

    # Large area difference.
    if area_frac >= 0.08:

        color_diff = _mean_color_diff(
            test_img,
            ref_img,
            (x, y, w, h)
        )

        if color_diff >= 18:

            return "Discoloration_Damage"

    return _zone_for_y(
        y_center_frac
    )


# ================================================================
# COLOR DIFFERENCE
# ================================================================

def _mean_color_diff(
    test_img: np.ndarray,
    ref_img: np.ndarray,
    bbox: Tuple[int, int, int, int],
) -> float:

    x, y, w, h = bbox

    test_resized = cv2.resize(
        test_img,
        IMAGE_SIZE
    )

    ref_resized = cv2.resize(
        ref_img,
        IMAGE_SIZE
    )

    test_roi = test_resized[
        y:y + h,
        x:x + w
    ]

    ref_roi = ref_resized[
        y:y + h,
        x:x + w
    ]

    if (
        test_roi.size == 0
        or
        ref_roi.size == 0
    ):
        return 0.0

    test_mean = cv2.mean(
        test_roi
    )[:3]

    ref_mean = cv2.mean(
        ref_roi
    )[:3]

    return float(
        np.mean(
            [
                abs(a - b)
                for a, b
                in zip(
                    test_mean,
                    ref_mean
                )
            ]
        )
    )


# ================================================================
# DEFECT CLASSIFIER
# ================================================================

def classify_valve_defect(
    test_img: np.ndarray,
    ref_img: np.ndarray,
    test_edges: np.ndarray,
    ref_edges: np.ndarray,
    regions: List[np.ndarray],
) -> str:
    """
    Main defect classifier.

    IMPORTANT:
    It checks the complete defect library first.

    It does NOT immediately classify the valve as Bent_Valve.
    """

    if not regions:

        logger.warning(
            "No defect regions detected."
        )

        return "Unknown_Defect"

    library = get_defect_library_images()

    total_reference_images = sum(
        len(images)
        for images in library.values()
    )

    logger.info(
        "Defect classification started. "
        "Regions=%d LibraryImages=%d",
        len(regions),
        total_reference_images
    )

    # ------------------------------------------------------------
    # PRIMARY CLASSIFIER
    # ------------------------------------------------------------

    if total_reference_images > 0:

        defect_name, confidence = (
            classify_against_defect_library(
                test_img,
                regions,
                library,
            )
        )

        logger.info(
            "Primary defect classification: "
            "%s (%.2f%%)",
            defect_name,
            confidence * 100.0,
        )

        if defect_name != "Unknown_Defect":

            return defect_name

    # ------------------------------------------------------------
    # FALLBACK
    # ------------------------------------------------------------

    fallback = _fallback_defect_classification(
        test_img,
        ref_img,
        regions
    )

    logger.warning(
        "Using fallback defect classifier: %s",
        fallback
    )

    return fallback


# ================================================================
# OVERLAY
# ================================================================

def _overlay_part_info(
    image: np.ndarray,
    part_number: str,
    status_text: str,
    status_color: Tuple[int, int, int],
) -> np.ndarray:

    img = image.copy()

    h, w = img.shape[:2]

    banner_h = 65

    overlay = img.copy()

    cv2.rectangle(
        overlay,
        (0, 0),
        (w, banner_h),
        (30, 30, 30),
        -1
    )

    cv2.addWeighted(
        overlay,
        0.65,
        img,
        0.35,
        0,
        img
    )

    cv2.putText(
        img,
        f"Part: {part_number}",
        (10, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    cv2.putText(
        img,
        status_text,
        (10, 52),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.60,
        status_color,
        2,
        cv2.LINE_AA,
    )

    return img


# ================================================================
# PART-SPECIFIC CROSS VALIDATION
# ================================================================

def _find_best_match_in_other_parts(
    test_features: Dict[str, Any],
    active_part_number: str,
    trained_folder: str,
) -> Tuple[float, Optional[str]]:

    best_score = 0.0

    best_part: Optional[str] = None

    try:

        other_parts = get_available_part_numbers(
            trained_folder
        )

    except Exception as e:

        logger.warning(
            "Could not get available parts: %s",
            e
        )

        return 0.0, None

    for part in other_parts:

        if str(part) == str(
            active_part_number
        ):
            continue

        part_folder = os.path.join(
            trained_folder,
            str(part)
        )

        if not os.path.isdir(
            part_folder
        ):
            continue

        try:

            filenames = os.listdir(
                part_folder
            )

        except Exception:

            continue

        for fname in filenames:

            if not fname.lower().endswith(
                IMAGE_EXTENSIONS
            ):
                continue

            full_path = os.path.join(
                part_folder,
                fname
            )

            ref_img = cv2.imread(
                full_path
            )

            if ref_img is None:
                continue

            ref_img_r = cv2.resize(
                ref_img,
                IMAGE_SIZE
            )

            ref_feats = extract_edge_features(
                detect_edges(
                    ref_img_r
                )
            )

            if not ref_feats:
                continue

            score = compare_edge_features(
                test_features,
                ref_feats
            )

            if score > best_score:

                best_score = score

                best_part = str(part)

    return best_score, best_part


# ================================================================
# MAIN IMAGE PROCESSING
# ================================================================

def process_image_web(
    frame: np.ndarray,
    filename: str,
    active_part_number: Optional[str] = None,
):
    """
    Main inspection function.

    Return format is kept compatible with your existing Flask app:

        result
        best_score
        result_img_path
        best_match
        defect_type
        detected_part_number
        part_name
    """

    try:

        if frame is None:

            return (
                "Error",
                0.0,
                None,
                "No image",
                "Unknown_Defect",
                "Unknown",
                "Unknown",
            )

        # --------------------------------------------------------
        # PREPARE IMAGE
        # --------------------------------------------------------

        resized_frame = cv2.resize(
            frame,
            IMAGE_SIZE
        )

        test_edges = detect_edges(
            resized_frame
        )

        test_features = extract_edge_features(
            test_edges
        )

        if not test_features:

            return (
                "Error",
                0.0,
                None,
                "No edges",
                "Unknown_Defect",
                "Unknown",
                "Unknown",
            )

        # --------------------------------------------------------
        # PART SELECTION
        # --------------------------------------------------------

        use_part_restricted = (
            active_part_number
            and
            str(active_part_number)
            .strip()
            .lower()
            not in (
                "unknown",
                "none",
                "auto",
                "",
            )
        )

        if not use_part_restricted:

            logger.error(
                "Active part number is required."
            )

            return (
                "Error",
                0.0,
                None,
                "No active part",
                "Unknown_Defect",
                "Unknown",
                "Unknown",
            )

        # --------------------------------------------------------
        # LOAD PART REFERENCE IMAGES
        # --------------------------------------------------------

        ref_images, part_folder = (
            get_images_for_part(
                TRAINED_IMAGES_FOLDER,
                active_part_number
            )
        )

        if not ref_images:

            logger.warning(
                "[Part %s] No reference images found. "
                "Expected folder: %s",
                active_part_number,
                part_folder,
            )

            return (
                "Error",
                0.0,
                None,
                f"No references for Part {active_part_number}",
                "Unknown_Defect",
                str(active_part_number),
                "Unknown",
            )

        # --------------------------------------------------------
        # FIND BEST PART REFERENCE
        # --------------------------------------------------------

        best_score = 0.0

        best_match: Optional[str] = None

        best_ref_features = None

        best_ref_image: Optional[np.ndarray] = None

        for ref_path in ref_images:

            ref_img = cv2.imread(
                ref_path
            )

            if ref_img is None:

                logger.warning(
                    "Could not read reference: %s",
                    ref_path
                )

                continue

            ref_img_r = cv2.resize(
                ref_img,
                IMAGE_SIZE
            )

            ref_edges = detect_edges(
                ref_img_r
            )

            ref_feats = extract_edge_features(
                ref_edges
            )

            if not ref_feats:
                continue

            score = compare_edge_features(
                test_features,
                ref_feats,
                debug_label=(
                    f"{filename} vs "
                    f"{os.path.basename(ref_path)}"
                ),
            )

            if score > best_score:

                best_score = score

                best_match = os.path.basename(
                    ref_path
                )

                best_ref_features = ref_feats

                best_ref_image = ref_img_r

        best_score = round(
            float(best_score),
            4
        )

        detected_part_number = str(
            active_part_number
        )

        # --------------------------------------------------------
        # ACCEPTED
        # --------------------------------------------------------

        if best_score >= EDGE_MATCH_THRESHOLD:

            result = "Accepted"

            defect_type = "OK"

            status_text = (
                f"OK  Part "
                f"{active_part_number}"
            )

            status_color = (
                0,
                255,
                0
            )

            output_image = resized_frame

        # --------------------------------------------------------
        # REJECTED
        # --------------------------------------------------------

        else:

            result = "Rejected"

            if best_ref_image is not None:

                ref_for_defects = (
                    best_ref_image
                )

            else:

                ref_for_defects = (
                    resized_frame
                )

            # ----------------------------------------------------
            # DETECT ALL DIFFERENCE REGIONS
            # ----------------------------------------------------

            defect_regions = (
                find_defect_regions(
                    resized_frame,
                    ref_for_defects,
                    MIN_DEFECT_AREA,
                )
            )

            logger.info(
                "[%s] Detected %d defect regions.",
                filename,
                len(defect_regions)
            )

            # ----------------------------------------------------
            # CLASSIFY DEFECT AGAINST ALL FOLDERS
            # ----------------------------------------------------

            defect_type = classify_valve_defect(
                resized_frame,
                ref_for_defects,
                test_edges,
                detect_edges(
                    ref_for_defects
                ),
                defect_regions,
            )

            status_text = (
                f"NG  Part "
                f"{active_part_number}  "
                f"{defect_type}"
            )

            status_color = (
                0,
                165,
                255
            )

            output_image = (
                draw_defect_regions(
                    resized_frame,
                    defect_regions
                )
            )

        # --------------------------------------------------------
        # ADD STATUS BANNER
        # --------------------------------------------------------

        output_image = _overlay_part_info(
            output_image,
            detected_part_number,
            status_text,
            status_color,
        )

        # --------------------------------------------------------
        # SAVE RESULT
        # --------------------------------------------------------

        result_img_path = os.path.join(
            "static",
            "uploads",
            filename
        )

        ensure_dir_exists(
            os.path.dirname(
                result_img_path
            )
        )

        success = cv2.imwrite(
            result_img_path,
            output_image
        )

        if not success:

            logger.error(
                "Failed to save result image: %s",
                result_img_path
            )

        # --------------------------------------------------------
        # PART NAME
        # --------------------------------------------------------

        part_name = (
            best_match
            if best_match
            else "Unknown"
        )

        # --------------------------------------------------------
        # LOG
        # --------------------------------------------------------

        logger.info(
            "[Part %s] %s -> %s (%s) "
            "Score=%.4f Reference=%s",
            detected_part_number,
            filename,
            result,
            defect_type,
            best_score,
            best_match,
        )

        return (
            result,
            best_score,
            result_img_path,
            best_match,
            defect_type,
            detected_part_number,
            part_name,
        )

    except Exception as e:

        logger.exception(
            "Processing error: %s",
            e
        )

        return (
            "Error",
            0.0,
            None,
            "Unknown",
            "Unknown_Defect",
            "Unknown",
            "Unknown",
        )


# ================================================================
# TRAINING / VISUALIZATION
# ================================================================

def train_reference_edges(
    part_number: str,
    filepath: str,
):

    try:

        img = cv2.imread(
            filepath
        )

        if img is None:

            logger.error(
                "Failed to read image: %s",
                filepath
            )

            return None, None

        img_resized = cv2.resize(
            img,
            IMAGE_SIZE
        )

        edges = detect_edges(
            img_resized
        )

        features = extract_edge_features(
            edges
        )

        if features is None:

            logger.warning(
                "No features extracted from %s",
                filepath
            )

            return None, None

        result_img = mark_defect_area(
            img_resized,
            img_resized
        )

        logger.info(
            "Trained edges for part %s from %s",
            part_number,
            filepath
        )

        return (
            result_img,
            features
        )

    except Exception as e:

        logger.exception(
            "Error training edges: %s",
            e
        )

        return None, None


def get_edge_visualization(
    img_path: str,
):

    try:

        img = cv2.imread(
            img_path
        )

        if img is None:

            logger.error(
                "Failed to read image: %s",
                img_path
            )

            return None

        img_resized = cv2.resize(
            img,
            IMAGE_SIZE
        )

        edges = detect_edges(
            img_resized
        )

        edges_bgr = cv2.cvtColor(
            edges,
            cv2.COLOR_GRAY2BGR
        )

        logger.info(
            "Generated edge visualization for %s",
            img_path
        )

        return edges_bgr

    except Exception as e:

        logger.exception(
            "Error generating edge visualization: %s",
            e
        )

        return None


# ================================================================
# PIXEL TO MM
# ================================================================

def pixels_to_mm(
    pixels: float,
    scale: float = 0.05,
) -> float:

    try:

        return float(
            pixels * scale
        )

    except Exception:

        return 0.0


# ================================================================
# DEFECT LIBRARY DIAGNOSTIC
# ================================================================

def print_defect_library_status() -> None:
    """
    Call this once to check whether all defect folders
    are being detected correctly.
    """

    print()
    print("=" * 70)
    print("DEFECT LIBRARY STATUS")
    print("=" * 70)

    roots = find_defect_library_roots()

    if not roots:

        print(
            "ERROR: No defect library found."
        )

        print(
            "Expected folders:"
        )

        for defect in DEFECT_CLASSES:
            print(
                f"  - {defect}"
            )

        print("=" * 70)

        return

    for root in roots:

        print(
            f"\nLibrary Root: {root}"
        )

        library = get_defect_library_images(
            root
        )

        for defect in DEFECT_CLASSES:

            count = len(
                library.get(
                    defect,
                    []
                )
            )

            status = (
                "OK"
                if count > 0
                else "MISSING"
            )

            print(
                f"  {status:7} "
                f"{defect:25} "
                f"{count} image(s)"
            )

    print("=" * 70)