"""
GCash/PayMaya/BDO Receipt OCR API
Accepts receipt images and extracts transaction ID, amount, and time.
Supports single image, batch upload, Google Drive folder scanning,
and transaction verification against PDF history.
"""

import asyncio
import httpx
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel
from ocr_engine import extract_text_with_confidence
from parsers import parse_receipt

app = FastAPI(
    title="Receipt OCR API",
    description="Upload GCash, PayMaya, or BDO Pay receipt screenshots to extract and verify transaction details.",
    version="3.0.0",
)

# Allow CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ReceiptResponse(BaseModel):
    """Single receipt result."""
    success: bool
    provider: str | None = None
    transaction_id: str | None = None
    amount: str | None = None
    time: str | None = None
    confidence: float = 0.0
    raw_text: list[str] = []
    error: str | None = None
    filename: str | None = None


class BatchResponse(BaseModel):
    """Batch processing result."""
    total: int
    successful: int
    failed: int
    results: list[ReceiptResponse]


class DriveRequest(BaseModel):
    """Request body for Google Drive folder processing."""
    folder_id: str
    credentials_path: str = "service_account.json"


# ---------------------------------------------------------------------------
# Shared processing logic
# ---------------------------------------------------------------------------

async def _download_image(url: str) -> tuple[bytes, str]:
    """
    Download an image from a URL.
    Returns (image_bytes, filename).
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=400, detail=f"Failed to download {url}: HTTP {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download {url}: {str(e)}")

    # Validate content type
    content_type = resp.headers.get("content-type", "").split(";")[0].strip()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"URL returned invalid content type '{content_type}'. Accepted: {', '.join(ALLOWED_TYPES)}",
        )

    if len(resp.content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"Downloaded file too large ({len(resp.content)} bytes).")

    # Extract filename from URL
    filename = urlparse(url).path.split("/")[-1] or "image"
    return resp.content, filename

async def _process_image(image_bytes: bytes, filename: str | None = None) -> ReceiptResponse:
    """Process a single image and return a ReceiptResponse."""
    # Run OCR
    try:
        lines, confidence = extract_text_with_confidence(image_bytes)
    except Exception as e:
        return ReceiptResponse(
            success=False,
            error=f"OCR failed: {str(e)}",
            filename=filename,
        )

    if not lines:
        return ReceiptResponse(
            success=False,
            confidence=0.0,
            error="No text detected in image. Make sure the image is a clear receipt screenshot.",
            raw_text=[],
            filename=filename,
        )

    # Parse receipt fields
    result = parse_receipt(lines)

    # Determine success
    is_valid = result.transaction_id is not None or result.amount is not None
    error_msg = None
    if not is_valid:
        error_msg = (
            "Could not extract transaction details. "
            "This may not be a valid GCash/PayMaya/BDO receipt."
        )

    return ReceiptResponse(
        success=is_valid,
        provider=result.provider,
        transaction_id=result.transaction_id,
        amount=result.amount,
        time=result.time,
        confidence=confidence,
        raw_text=result.raw_text or [],
        error=error_msg,
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/parse-receipt", response_model=ReceiptResponse)
async def parse_receipt_endpoint(file: UploadFile = File(...)):
    """
    Upload a single receipt image.
    Returns the extracted transaction ID, amount, time, and confidence.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Accepted: {', '.join(ALLOWED_TYPES)}",
        )

    image_bytes = await file.read()
    if len(image_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(image_bytes)} bytes). Max: {MAX_FILE_SIZE} bytes.",
        )

    return await _process_image(image_bytes, filename=file.filename)


class UrlRequest(BaseModel):
    """Request body for single URL parsing."""
    url: str


class BatchUrlRequest(BaseModel):
    """Request body for batch URL parsing."""
    urls: list[str]


@app.post("/parse-receipt-url", response_model=ReceiptResponse)
async def parse_receipt_url(request: UrlRequest):
    """
    Parse a receipt image from a URL.
    Accepts a JSON body with an image URL.
    """
    image_bytes, filename = await _download_image(request.url)
    return await _process_image(image_bytes, filename=filename)


@app.post("/parse-receipts-url", response_model=BatchResponse)
async def parse_receipts_url(request: BatchUrlRequest):
    """
    Parse multiple receipt images from URLs.
    Accepts a JSON body with a list of image URLs.
    """
    if not request.urls:
        raise HTTPException(status_code=400, detail="No URLs provided.")
    if len(request.urls) > 50:
        raise HTTPException(status_code=400, detail="Max 50 URLs per batch.")

    results: list[ReceiptResponse] = []
    for url in request.urls:
        try:
            image_bytes, filename = await _download_image(url)
            result = await _process_image(image_bytes, filename=filename)
        except HTTPException as e:
            result = ReceiptResponse(
                success=False,
                error=e.detail,
                filename=url,
            )
        results.append(result)

    successful = sum(1 for r in results if r.success)
    return BatchResponse(
        total=len(results),
        successful=successful,
        failed=len(results) - successful,
        results=results,
    )


@app.post("/parse-receipts", response_model=BatchResponse)
async def parse_receipts_batch(files: list[UploadFile] = File(...)):
    """
    Upload multiple receipt images at once.
    Returns results for each image, along with summary counts.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Max 50 files per batch.")

    results: list[ReceiptResponse] = []

    for file in files:
        # Skip invalid types gracefully
        if file.content_type not in ALLOWED_TYPES:
            results.append(ReceiptResponse(
                success=False,
                error=f"Invalid file type '{file.content_type}'.",
                filename=file.filename,
            ))
            continue

        image_bytes = await file.read()
        if len(image_bytes) > MAX_FILE_SIZE:
            results.append(ReceiptResponse(
                success=False,
                error=f"File too large ({len(image_bytes)} bytes).",
                filename=file.filename,
            ))
            continue

        result = await _process_image(image_bytes, filename=file.filename)
        results.append(result)

    successful = sum(1 for r in results if r.success)
    return BatchResponse(
        total=len(results),
        successful=successful,
        failed=len(results) - successful,
        results=results,
    )


@app.post("/parse-drive-folder", response_model=BatchResponse)
async def parse_drive_folder(request: DriveRequest):
    """
    Scan a Google Drive folder for receipt images and process each one.
    Requires a service account JSON key file with access to the folder.

    Body:
      - folder_id: Google Drive folder ID (from the folder URL)
      - credentials_path: path to service account JSON key (default: service_account.json)
    """
    try:
        from gdrive import list_image_files, download_file
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Google Drive dependencies not installed. Run: pip install google-auth httpx",
        )

    # List images in folder
    try:
        image_files = list_image_files(request.folder_id, request.credentials_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=400,
            detail=f"Credentials file not found: '{request.credentials_path}'. "
                   "Place your service account JSON key file in the project directory.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to access Google Drive folder: {str(e)}",
        )

    if not image_files:
        return BatchResponse(total=0, successful=0, failed=0, results=[])

    # Process each image
    results: list[ReceiptResponse] = []
    for file_info in image_files:
        try:
            image_bytes = download_file(file_info["id"], request.credentials_path)
            result = await _process_image(image_bytes, filename=file_info["name"])
        except Exception as e:
            result = ReceiptResponse(
                success=False,
                error=f"Failed to download/process: {str(e)}",
                filename=file_info["name"],
            )
        results.append(result)

    successful = sum(1 for r in results if r.success)
    return BatchResponse(
        total=len(results),
        successful=successful,
        failed=len(results) - successful,
        results=results,
    )


@app.post("/verify-receipts")
async def verify_receipts_endpoint(
    history_pdf: UploadFile = File(..., description="GCash/Maya/BDO transaction history PDF"),
    receipts: list[UploadFile] = File(..., description="Receipt images to verify"),
):
    """
    Verify receipt images against a transaction history PDF.

    Upload:
      - history_pdf: exported PDF from GCash/Maya/BDO with transaction history
      - receipts: one or more receipt screenshot images

    Returns a verification report showing which receipts match, mismatch,
    or are not found in the transaction history.
    """
    from history_parser import parse_pdf_tables
    from matcher import verify_receipts as run_verification, MatchResult

    # Validate PDF
    if not history_pdf.filename or not history_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="history_pdf must be a PDF file.")

    pdf_bytes = await history_pdf.read()

    # Parse transaction history from PDF
    try:
        history = parse_pdf_tables(pdf_bytes, is_bytes=True)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse PDF: {str(e)}",
        )

    if not history:
        raise HTTPException(
            status_code=400,
            detail="No transactions found in the PDF. Make sure this is a valid transaction history export.",
        )

    # Process each receipt image through OCR
    parsed_receipts: list[tuple[str, any]] = []
    receipt_responses: list[ReceiptResponse] = []

    for file in receipts:
        if file.content_type not in ALLOWED_TYPES:
            receipt_responses.append(ReceiptResponse(
                success=False,
                error=f"Invalid file type '{file.content_type}'.",
                filename=file.filename,
            ))
            continue

        image_bytes = await file.read()
        result = await _process_image(image_bytes, filename=file.filename)
        receipt_responses.append(result)

        if result.success:
            # Build a ReceiptData-like object for matching
            from parsers import ReceiptData
            parsed_receipts.append((
                file.filename,
                ReceiptData(
                    provider=result.provider,
                    transaction_id=result.transaction_id,
                    amount=result.amount,
                    time=result.time,
                ),
            ))

    # Run matching
    match_results = run_verification(parsed_receipts, history)

    # Build response
    verification_items = []
    for mr in match_results:
        verification_items.append({
            "filename": mr.receipt_filename,
            "verdict": mr.verdict,
            "details": mr.details,
            "receipt": {
                "ref": mr.receipt_ref,
                "amount": mr.receipt_amount,
                "time": mr.receipt_time,
            },
            "history_match": {
                "ref": mr.history_ref,
                "amount": mr.history_amount,
                "time": mr.history_time,
            } if mr.history_ref or mr.history_amount else None,
        })

    # Add entries for receipts that failed OCR
    for resp in receipt_responses:
        if not resp.success:
            verification_items.append({
                "filename": resp.filename,
                "verdict": "error",
                "details": resp.error or "OCR failed for this receipt.",
                "receipt": None,
                "history_match": None,
            })

    matched = sum(1 for v in verification_items if v["verdict"] == "matched")
    mismatched = sum(1 for v in verification_items if v["verdict"] == "mismatch")
    not_found = sum(1 for v in verification_items if v["verdict"] == "not_found")
    errors = sum(1 for v in verification_items if v["verdict"] == "error")

    return {
        "total_receipts": len(verification_items),
        "history_transactions_found": len(history),
        "summary": {
            "matched": matched,
            "mismatch": mismatched,
            "not_found": not_found,
            "errors": errors,
        },
        "results": verification_items,
    }


class ParsedReceiptInput(BaseModel):
    """A single pre-parsed receipt (from /parse-receipts output)."""
    transaction_id: str | None = None
    amount: str | None = None
    time: str | None = None
    provider: str | None = None
    filename: str | None = None


class VerifyParsedRequest(BaseModel):
    """Request body for /verify-parsed."""
    receipts: list[ParsedReceiptInput]


@app.post("/verify-parsed")
async def verify_parsed_endpoint(
    history_pdf: UploadFile = File(..., description="GCash/Maya/BDO transaction history PDF"),
    receipts_json: str = File(..., description="JSON string — the 'results' array from /parse-receipts"),
):
    """
    Verify pre-parsed receipts against a transaction history PDF.

    Instead of uploading images again, pass the JSON output from /parse-receipts.

    Upload:
      - history_pdf: exported PDF from GCash/Maya/BDO
      - receipts_json: the JSON string of the 'results' array from /parse-receipts

    Example receipts_json value:
      [{"transaction_id": "7037516197197", "amount": "320.00", "time": "Feb 5, 2026 7:23 PM", "filename": "receipt1.jpg"}]
    """
    import json as json_lib
    from history_parser import parse_pdf_tables
    from matcher import verify_receipts as run_verification
    from parsers import ReceiptData

    # Validate PDF
    if not history_pdf.filename or not history_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="history_pdf must be a PDF file.")

    pdf_bytes = await history_pdf.read()

    # Parse transaction history
    try:
        history = parse_pdf_tables(pdf_bytes, is_bytes=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {str(e)}")

    if not history:
        raise HTTPException(
            status_code=400,
            detail="No transactions found in the PDF.",
        )

    # Parse the receipts JSON
    try:
        parsed_list = json_lib.loads(receipts_json)
        if not isinstance(parsed_list, list):
            raise ValueError("Expected a JSON array")
    except (json_lib.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid receipts_json: {str(e)}")

    # Build ReceiptData objects
    receipt_pairs: list[tuple[str, ReceiptData]] = []
    for item in parsed_list:
        receipt_pairs.append((
            item.get("filename", "unknown"),
            ReceiptData(
                provider=item.get("provider"),
                transaction_id=item.get("transaction_id"),
                amount=item.get("amount"),
                time=item.get("time"),
            ),
        ))

    # Run matching
    match_results = run_verification(receipt_pairs, history)

    # Build response
    verification_items = []
    for mr in match_results:
        verification_items.append({
            "filename": mr.receipt_filename,
            "verdict": mr.verdict,
            "details": mr.details,
            "receipt": {
                "ref": mr.receipt_ref,
                "amount": mr.receipt_amount,
                "time": mr.receipt_time,
            },
            "history_match": {
                "ref": mr.history_ref,
                "amount": mr.history_amount,
                "time": mr.history_time,
            } if mr.history_ref or mr.history_amount else None,
        })

    matched = sum(1 for v in verification_items if v["verdict"] == "matched")
    mismatched = sum(1 for v in verification_items if v["verdict"] == "mismatch")
    not_found = sum(1 for v in verification_items if v["verdict"] == "not_found")

    return {
        "total_receipts": len(verification_items),
        "history_transactions_found": len(history),
        "summary": {
            "matched": matched,
            "mismatch": mismatched,
            "not_found": not_found,
        },
        "results": verification_items,
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def root():
    """
    Serve the landing page with API documentation and Vercel Speed Insights.
    """
    html_file = Path(__file__).parent / "templates" / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    else:
        # Fallback if template file is not found
        return """
        <html>
            <head><title>Receipt OCR API</title></head>
            <body>
                <h1>Receipt OCR API</h1>
                <p>Welcome to the Receipt OCR API. Visit <a href="/docs">/docs</a> for API documentation.</p>
            </body>
        </html>
        """
