from __future__ import annotations

import io
import logging

import google_auth
from config import CONFIG_DIR
from google_auth import CREDENTIALS_FILE  # noqa: F401  (module surface)

logger = logging.getLogger(__name__)

TOKEN_FILE = CONFIG_DIR / "drive_token.json"

SCOPES = ["https://www.googleapis.com/auth/drive"]

_GOOGLE_MIME_TYPES = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.folder",
}

_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


_auth = google_auth.GoogleAuth(TOKEN_FILE, SCOPES)

has_credentials = _auth.has_credentials
is_authenticated = _auth.is_authenticated
needs_reauth = _auth.needs_reauth
get_auth_url = _auth.get_auth_url
handle_callback = _auth.handle_callback
_load_creds = _auth.load_creds


def _get_service():
    return _auth.service("drive", "v3")


# ── File listing and search ────────────────────────────────────────────────────


def list_files(
    query: str | None = None,
    parent_id: str | None = None,
    page_size: int = 100,
) -> list[dict]:
    """List files in Drive. Optionally filter by query string or parent folder."""
    service = _get_service()
    q_parts = ["trashed = false"]
    if query:
        q_parts.append(query)
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")
    results = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=" and ".join(q_parts),
                pageSize=min(page_size, 1000),
                fields="nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink)",
                pageToken=page_token,
            )
            .execute()
        )
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token or len(results) >= page_size:
            break
    return results[:page_size]


def search_files(query: str, page_size: int = 50) -> list[dict]:
    """Search files by name or full-text content."""
    return list_files(
        query=f"(name contains '{query}' or fullText contains '{query}')",
        page_size=page_size,
    )


def list_recent_files(page_size: int = 20) -> list[dict]:
    """List most recently modified files."""
    service = _get_service()
    resp = (
        service.files()
        .list(
            q="trashed = false",
            pageSize=page_size,
            orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, size, modifiedTime, webViewLink)",
        )
        .execute()
    )
    return resp.get("files", [])


# ── File metadata ──────────────────────────────────────────────────────────────


def get_file(file_id: str) -> dict:
    """Get file metadata."""
    return (
        _get_service()
        .files()
        .get(
            fileId=file_id,
            fields="id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink, description",
        )
        .execute()
    )


def get_file_permissions(file_id: str) -> list[dict]:
    """Get file sharing permissions."""
    resp = (
        _get_service()
        .permissions()
        .list(
            fileId=file_id,
            fields="permissions(id, type, role, emailAddress, displayName)",
        )
        .execute()
    )
    return resp.get("permissions", [])


# ── File content ───────────────────────────────────────────────────────────────


def read_file(file_id: str, export_mime_type: str | None = None) -> str:
    """Read file content as a string.

    For Google Workspace types (Docs, Sheets), exports to text/plain or text/csv
    unless export_mime_type overrides. For binary files, decodes as UTF-8.
    """
    service = _get_service()
    meta = get_file(file_id)
    mime = meta.get("mimeType", "")

    if mime in _GOOGLE_MIME_TYPES and mime != "application/vnd.google-apps.folder":
        export_type = export_mime_type or _EXPORT_MIME.get(mime, "text/plain")
        data = service.files().export(fileId=file_id, mimeType=export_type).execute()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)

    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    from googleapiclient.http import MediaIoBaseDownload

    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8", errors="replace")


def download_file(file_id: str, export_mime_type: str | None = None) -> bytes:
    """Download file content as raw bytes."""
    service = _get_service()
    meta = get_file(file_id)
    mime = meta.get("mimeType", "")

    if mime in _GOOGLE_MIME_TYPES and mime != "application/vnd.google-apps.folder":
        export_type = export_mime_type or _EXPORT_MIME.get(mime, "text/plain")
        data = service.files().export(fileId=file_id, mimeType=export_type).execute()
        return data if isinstance(data, bytes) else data.encode("utf-8")

    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# ── File creation and modification ─────────────────────────────────────────────


def create_file(
    title: str,
    text_content: str | None = None,
    content_mime_type: str | None = None,
    parent_id: str | None = None,
    convert_to_google: bool = True,
) -> dict:
    """Create a new file in Drive.

    If text_content is provided with content_mime_type='text/plain', converts to
    a Google Doc by default. Pass convert_to_google=False to keep as plain text.
    Similarly, text/csv converts to Google Sheets.
    """
    from googleapiclient.http import MediaInMemoryUpload

    file_meta: dict = {"name": title}
    if parent_id:
        file_meta["parents"] = [parent_id]

    if text_content is None:
        # Create empty Google Workspace file based on title hint or default to Doc
        if not content_mime_type:
            content_mime_type = "application/vnd.google-apps.document"
        file_meta["mimeType"] = content_mime_type
        return (
            _get_service()
            .files()
            .create(body=file_meta, fields="id, name, mimeType, webViewLink")
            .execute()
        )

    raw_mime = content_mime_type or "text/plain"
    if convert_to_google:
        if raw_mime == "text/plain":
            file_meta["mimeType"] = "application/vnd.google-apps.document"
        elif raw_mime == "text/csv":
            file_meta["mimeType"] = "application/vnd.google-apps.spreadsheet"

    media = MediaInMemoryUpload(text_content.encode("utf-8"), mimetype=raw_mime)
    return (
        _get_service()
        .files()
        .create(
            body=file_meta,
            media_body=media,
            fields="id, name, mimeType, webViewLink",
        )
        .execute()
    )


def update_file(
    file_id: str,
    text_content: str,
    content_mime_type: str = "text/plain",
) -> dict:
    """Overwrite an existing non-Google-Workspace file's content.

    For Google Docs, use gdocs.py. For Google Sheets, use gsheets.py.
    """
    from googleapiclient.http import MediaInMemoryUpload

    media = MediaInMemoryUpload(
        text_content.encode("utf-8"), mimetype=content_mime_type
    )
    return (
        _get_service()
        .files()
        .update(
            fileId=file_id,
            media_body=media,
            fields="id, name, mimeType, modifiedTime",
        )
        .execute()
    )


def copy_file(
    file_id: str, new_title: str | None = None, parent_id: str | None = None
) -> dict:
    """Copy a file. Returns the new file's metadata."""
    body: dict = {}
    if new_title:
        body["name"] = new_title
    if parent_id:
        body["parents"] = [parent_id]
    return (
        _get_service()
        .files()
        .copy(
            fileId=file_id,
            body=body,
            fields="id, name, mimeType, webViewLink",
        )
        .execute()
    )


def delete_file(file_id: str) -> bool:
    """Permanently delete a file. Returns True on success."""
    try:
        _get_service().files().delete(fileId=file_id).execute()
        return True
    except Exception:
        logger.exception("delete_file failed for file_id=%s", file_id)
        return False


def trash_file(file_id: str) -> bool:
    """Move a file to trash (recoverable). Returns True on success."""
    try:
        _get_service().files().update(fileId=file_id, body={"trashed": True}).execute()
        return True
    except Exception:
        logger.exception("trash_file failed for file_id=%s", file_id)
        return False


# ── Folder operations ──────────────────────────────────────────────────────────


def create_folder(name: str, parent_id: str | None = None) -> dict:
    """Create a folder in Drive. Returns folder metadata."""
    body: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]
    return (
        _get_service()
        .files()
        .create(body=body, fields="id, name, webViewLink")
        .execute()
    )


def move_file(
    file_id: str, new_parent_id: str, old_parent_id: str | None = None
) -> dict:
    """Move a file to a different folder."""
    service = _get_service()
    if old_parent_id is None:
        meta = get_file(file_id)
        parents = meta.get("parents", [])
        old_parent_id = parents[0] if parents else None
    kwargs: dict = {
        "fileId": file_id,
        "addParents": new_parent_id,
        "fields": "id, name, parents",
    }
    if old_parent_id:
        kwargs["removeParents"] = old_parent_id
    return service.files().update(**kwargs).execute()
