"""
Google Drive integration — list and download image files from a Drive folder.
Requires a Google Cloud service account JSON key file.
"""

import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Image MIME types we can process
IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
}

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _get_service(credentials_path: str):
    """Build a Google Drive API service from a service account key file."""
    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def list_image_files(folder_id: str, credentials_path: str) -> list[dict]:
    """
    List all image files in a Google Drive folder.
    Returns a list of dicts with 'id', 'name', and 'mimeType'.
    """
    service = _get_service(credentials_path)

    # Query for image files in the specified folder
    mime_query = " or ".join(f"mimeType='{m}'" for m in IMAGE_MIMES)
    query = f"'{folder_id}' in parents and ({mime_query}) and trashed=false"

    results = []
    page_token = None

    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )

        results.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return results


def download_file(file_id: str, credentials_path: str) -> bytes:
    """Download a file from Google Drive and return its bytes."""
    service = _get_service(credentials_path)
    request = service.files().get_media(fileId=file_id)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue()
