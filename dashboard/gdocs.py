from __future__ import annotations

import logging

import google_auth
from config import CONFIG_DIR
from google_auth import CREDENTIALS_FILE  # noqa: F401  (module surface)

logger = logging.getLogger(__name__)

TOKEN_FILE = CONFIG_DIR / "docs_token.json"

SCOPES = ["https://www.googleapis.com/auth/documents"]


_auth = google_auth.GoogleAuth(TOKEN_FILE, SCOPES)

has_credentials = _auth.has_credentials
is_authenticated = _auth.is_authenticated
needs_reauth = _auth.needs_reauth
get_auth_url = _auth.get_auth_url
handle_callback = _auth.handle_callback
_load_creds = _auth.load_creds


def _get_service():
    return _auth.service("docs", "v1")


# ── Reading ────────────────────────────────────────────────────────────────────


def get_doc(document_id: str) -> dict:
    """Return the full document resource (structured body, styles, lists, etc.)."""
    return _get_service().documents().get(documentId=document_id).execute()


def read_doc(document_id: str) -> str:
    """Return the document body as plain text."""
    doc = get_doc(document_id)
    return _extract_text(doc)


def _extract_text(doc: dict) -> str:
    parts: list[str] = []
    for block in doc.get("body", {}).get("content", []):
        para = block.get("paragraph", {})
        for elem in para.get("elements", []):
            text = elem.get("textRun", {}).get("content", "")
            if text:
                parts.append(text)
        table = block.get("table", {})
        for row in table.get("tableRows", []):
            for cell in row.get("tableCells", []):
                for cell_block in cell.get("content", []):
                    for elem in cell_block.get("paragraph", {}).get("elements", []):
                        text = elem.get("textRun", {}).get("content", "")
                        if text:
                            parts.append(text)
    return "".join(parts)


def _end_index(doc: dict) -> int:
    """Return the last writable index in the document body."""
    content = doc.get("body", {}).get("content", [])
    if not content:
        return 1
    return max(content[-1].get("endIndex", 1) - 1, 1)


# ── Writing ────────────────────────────────────────────────────────────────────


def create_doc(title: str) -> dict:
    """Create a new empty Google Doc. Returns document metadata including documentId."""
    return _get_service().documents().create(body={"title": title}).execute()


def batch_update(document_id: str, requests: list[dict]) -> dict:
    """Execute a raw batchUpdate. Use for advanced formatting or structural changes."""
    return (
        _get_service()
        .documents()
        .batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        )
        .execute()
    )


def insert_text(document_id: str, text: str, index: int = 1) -> dict:
    """Insert text at a specific character index (default: beginning of document)."""
    return batch_update(
        document_id, [{"insertText": {"location": {"index": index}, "text": text}}]
    )


def append_text(document_id: str, text: str) -> dict:
    """Append text to the end of the document."""
    doc = get_doc(document_id)
    idx = _end_index(doc)
    return batch_update(
        document_id, [{"insertText": {"location": {"index": idx}, "text": text}}]
    )


def replace_text(
    document_id: str,
    find: str,
    replace_with: str,
    match_case: bool = True,
) -> dict:
    """Find and replace all occurrences of a string in the document."""
    return batch_update(
        document_id,
        [
            {
                "replaceAllText": {
                    "containsText": {"text": find, "matchCase": match_case},
                    "replaceText": replace_with,
                }
            }
        ],
    )


def clear_document(document_id: str) -> dict | None:
    """Delete all content from the document, leaving an empty body."""
    doc = get_doc(document_id)
    idx = _end_index(doc)
    if idx <= 1:
        return None
    return batch_update(
        document_id,
        [{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": idx}}}],
    )


def overwrite_document(document_id: str, new_content: str) -> dict | None:
    """Replace the entire document body with new_content."""
    clear_document(document_id)
    if not new_content:
        return None
    return batch_update(
        document_id, [{"insertText": {"location": {"index": 1}, "text": new_content}}]
    )


def delete_range(document_id: str, start_index: int, end_index: int) -> dict:
    """Delete a specific character range from the document."""
    return batch_update(
        document_id,
        [
            {
                "deleteContentRange": {
                    "range": {"startIndex": start_index, "endIndex": end_index}
                }
            }
        ],
    )
