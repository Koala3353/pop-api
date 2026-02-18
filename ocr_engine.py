"""
OCR Engine — image preprocessing and text extraction using PaddleOCR.
"""

import io
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import cv2
from paddleocr import PaddleOCR

# Initialize PaddleOCR once (expensive to create)
_ocr = PaddleOCR(
    use_angle_cls=True,   # detect rotated text
    lang="en",            # English language
    show_log=False,       # suppress verbose logging
)


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    """
    Preprocess receipt image for better OCR accuracy.
    Returns an OpenCV-compatible numpy array (BGR).
    """
    # Load image from bytes
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Resize if too small (PaddleOCR works better with reasonable resolution)
    w, h = image.size
    if max(w, h) < 800:
        scale = 800 / max(w, h)
        image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # Enhance contrast (receipts often have low contrast on screenshots)
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(1.5)

    # Sharpen slightly
    image = image.filter(ImageFilter.SHARPEN)

    # Convert to OpenCV format (BGR numpy array)
    img_array = np.array(image)
    img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

    return img_bgr


def extract_text_with_confidence(image_bytes: bytes) -> tuple[list[str], float]:
    """
    Run PaddleOCR on the image and return:
      - all detected text lines sorted top-to-bottom
      - average OCR confidence score (0.0–1.0)
    """
    img = preprocess_image(image_bytes)

    # Run OCR — returns list of [boxes, (text, confidence)]
    results = _ocr.ocr(img, cls=True)

    if not results or not results[0]:
        return [], 0.0

    # Collect (y_position, text, confidence) so we can sort top-to-bottom
    lines: list[tuple[float, str, float]] = []
    for line in results[0]:
        box = line[0]        # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        text = line[1][0]    # recognized text
        confidence = line[1][1]

        # Skip very low-confidence detections
        if confidence < 0.5:
            continue

        # Use average Y of the bounding box for vertical sorting
        avg_y = sum(pt[1] for pt in box) / 4
        lines.append((avg_y, text, confidence))

    # Sort by vertical position (top to bottom)
    lines.sort(key=lambda x: x[0])

    texts = [text for _, text, _ in lines]
    avg_conf = sum(c for _, _, c in lines) / len(lines) if lines else 0.0

    return texts, round(avg_conf, 4)


def extract_text(image_bytes: bytes) -> list[str]:
    """
    Run PaddleOCR on the image and return all detected text lines,
    sorted top-to-bottom by their vertical position.
    """
    texts, _ = extract_text_with_confidence(image_bytes)
    return texts

