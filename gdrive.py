"""
Google Drive integration — list and download image files from a Drive folder.
Uses lightweight httpx + google-auth instead of the heavy google-api-python-client.
Requires a Google Cloud service account JSON key file.
"""

import httpx
from google.oauth2 import service_account
from google.auth.transport.requests import Request

# Image MIME types we can process
IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
}

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DRIVE_API_URL = "https://www.googleapis.com/drive/v3/files"


def _get_access_token(credentials_path: str) -> str:
    """Get a valid access token from the service account key file."""
    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES
    )
    # Refresh to get the initial token
    creds.refresh(Request())
    return creds.token


def list_image_files(folder_id: str, credentials_path: str) -> list[dict]:
    """
    List all image files in a Google Drive folder.
    Returns a list of dicts with 'id', 'name', and 'mimeType'.
    """
    token = _get_access_token(credentials_path)
    headers = {"Authorization": f"Bearer {token}"}

    # Query for image files in the specified folder
    mime_query = " or ".join(f"mimeType='{m}'" for m in IMAGE_MIMES)
    query = f"'{folder_id}' in parents and ({mime_query}) and trashed=false"

    results = []
    page_token = None

    with httpx.Client(timeout=30.0) as client:
        while True:
            params = {
                "q": query,
                "fields": "nextPageToken, files(id, name, mimeType)",
                "pageSize": 100,
            }
            if page_token:
                params["pageToken"] = page_token

            resp = client.get(DRIVE_API_URL, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

            results.extend(data.get("files", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    return results


def download_file(file_id: str, credentials_path: str) -> bytes:
    """Download a file from Google Drive and return its bytes."""
    token = _get_access_token(credentials_path)
    headers = {"Authorization": f"Bearer {token}"}
    
    url = f"{DRIVE_API_URL}/{file_id}"
    params = {"alt": "media"}

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.content
