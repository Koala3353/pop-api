# 📱 Receipt OCR API (pop-checker)

A Python API that extracts transaction details from **GCash**, **PayMaya**, and **BDO Pay** receipt screenshots.

Upload a receipt image → get back the **transaction number**, **amount**, **time**, and **confidence score** as structured JSON.

## Quick Start

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
uvicorn app:app --reload --port 8000
```

The API will be running at `http://localhost:8000`. Interactive docs at **http://localhost:8000/docs**.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/parse-receipt` | Upload **one** receipt image |
| `POST` | `/parse-receipts` | Upload **multiple** receipt images (batch) |
| `POST` | `/parse-drive-folder` | Process all images in a **Google Drive** folder |
| `GET`  | `/health`        | Health check |

---

## Usage Examples

### Single receipt

```bash
curl -X POST http://localhost:8000/parse-receipt \
  -F "file=@receipt.png"
```

```json
{
  "success": true,
  "provider": "gcash",
  "transaction_id": "7037516197197",
  "amount": "320.00",
  "time": "Feb 5, 2026 7:23 PM",
  "confidence": 0.9781,
  "filename": "receipt.png",
  "error": null
}
```

### Batch (multiple receipts)

```bash
curl -X POST http://localhost:8000/parse-receipts \
  -F "files=@receipt1.png" \
  -F "files=@receipt2.jpg" \
  -F "files=@receipt3.png"
```

```json
{
  "total": 3,
  "successful": 2,
  "failed": 1,
  "results": [
    { "success": true, "transaction_id": "7037516197197", "amount": "320.00", "confidence": 0.98, ... },
    { "success": true, "transaction_id": "6037260329062", "amount": "120.00", "confidence": 0.97, ... },
    { "success": false, "error": "No text detected in image.", ... }
  ]
}
```

### Google Drive folder

```bash
curl -X POST http://localhost:8000/parse-drive-folder \
  -H "Content-Type: application/json" \
  -d '{"folder_id": "YOUR_FOLDER_ID", "credentials_path": "service_account.json"}'
```

#### Google Drive Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable the **Google Drive API**
3. Create a **Service Account** → Download the JSON key
4. Save the key as `service_account.json` in this project folder
5. **Share your Drive folder** with the service account email (found in the JSON under `client_email`)

---

## Supported Receipt Types

- ✅ GCash Express Send / Send Money
- ✅ PayMaya / Maya transfers
- ✅ BDO Pay

## Response Fields

| Field | Description |
|-------|-------------|
| `success` | Whether valid transaction data was found |
| `provider` | `"gcash"`, `"paymaya"`, `"bdo"`, or `null` |
| `transaction_id` | Reference / transaction number |
| `amount` | Transaction amount (e.g. `"320.00"`) |
| `time` | Date and time from the receipt |
| `confidence` | OCR confidence score (0.0–1.0) |
| `filename` | Original filename |
| `raw_text` | All OCR-detected text lines (for debugging) |

## Running Tests

```bash
python test_parsers.py
```

## Tech Stack

- **PaddleOCR** — deep-learning OCR engine
- **FastAPI** — async web framework
- **OpenCV + Pillow** — image preprocessing
- **Google Drive API** — folder scanning (optional)
