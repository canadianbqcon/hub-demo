from __future__ import annotations

import logging

import google_auth
from config import CONFIG_DIR
from google_auth import CREDENTIALS_FILE  # noqa: F401  (module surface)

logger = logging.getLogger(__name__)

TOKEN_FILE = CONFIG_DIR / "sheets_token.json"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


_auth = google_auth.GoogleAuth(TOKEN_FILE, SCOPES)

has_credentials = _auth.has_credentials
is_authenticated = _auth.is_authenticated
needs_reauth = _auth.needs_reauth
get_auth_url = _auth.get_auth_url
handle_callback = _auth.handle_callback
_load_creds = _auth.load_creds


def _get_service():
    return _auth.service("sheets", "v4")


# ── Spreadsheet metadata ───────────────────────────────────────────────────────


def get_spreadsheet(spreadsheet_id: str) -> dict:
    """Return full spreadsheet metadata including all sheet properties."""
    return _get_service().spreadsheets().get(spreadsheetId=spreadsheet_id).execute()


def get_sheet_names(spreadsheet_id: str) -> list[str]:
    """Return a list of sheet (tab) names in the spreadsheet."""
    info = get_spreadsheet(spreadsheet_id)
    return [s["properties"]["title"] for s in info.get("sheets", [])]


def get_sheet_id(spreadsheet_id: str, sheet_name: str) -> int | None:
    """Return the numeric sheetId for a named sheet tab."""
    info = get_spreadsheet(spreadsheet_id)
    for sheet in info.get("sheets", []):
        if sheet["properties"]["title"] == sheet_name:
            return sheet["properties"]["sheetId"]
    return None


# ── Reading ────────────────────────────────────────────────────────────────────


def read_range(spreadsheet_id: str, range_name: str) -> list[list]:
    """Read a cell range. range_name uses A1 notation, e.g. 'Sheet1!A1:D10'.

    Returns a list of rows, each row a list of cell values (strings).
    Trailing empty cells in a row are omitted by the API.
    """
    resp = (
        _get_service()
        .spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=range_name,
        )
        .execute()
    )
    return resp.get("values", [])


def read_sheet(spreadsheet_id: str, sheet_name: str = "Sheet1") -> list[list]:
    """Read an entire sheet tab. Returns all rows as a list of lists."""
    return read_range(spreadsheet_id, sheet_name)


def read_all_sheets(spreadsheet_id: str) -> dict[str, list[list]]:
    """Read every sheet in the spreadsheet. Returns {sheet_name: rows}."""
    names = get_sheet_names(spreadsheet_id)
    return {name: read_sheet(spreadsheet_id, name) for name in names}


# ── Writing ────────────────────────────────────────────────────────────────────


def write_range(
    spreadsheet_id: str,
    range_name: str,
    values: list[list],
    value_input_option: str = "USER_ENTERED",
) -> dict:
    """Write values to a cell range. Overwrites existing content in that range.

    value_input_option: 'USER_ENTERED' parses formulas and dates;
                        'RAW' stores exactly as given.
    """
    return (
        _get_service()
        .spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption=value_input_option,
            body={"values": values},
        )
        .execute()
    )


def append_rows(
    spreadsheet_id: str,
    range_name: str,
    rows: list[list],
    value_input_option: str = "USER_ENTERED",
) -> dict:
    """Append rows after the last row with data in the given range.

    range_name only needs to identify the sheet (e.g. 'Sheet1' or 'Sheet1!A:Z').
    The API finds the first empty row automatically.
    """
    return (
        _get_service()
        .spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption=value_input_option,
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        )
        .execute()
    )


def clear_range(spreadsheet_id: str, range_name: str) -> dict:
    """Clear all values from a cell range (keeps formatting)."""
    return (
        _get_service()
        .spreadsheets()
        .values()
        .clear(
            spreadsheetId=spreadsheet_id,
            range=range_name,
        )
        .execute()
    )


def batch_write(
    spreadsheet_id: str,
    updates: list[dict],
    value_input_option: str = "USER_ENTERED",
) -> dict:
    """Write multiple ranges in a single API call.

    Each entry in updates: {'range': 'Sheet1!A1:B2', 'values': [[...], [...]]}.
    """
    return (
        _get_service()
        .spreadsheets()
        .values()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": value_input_option, "data": updates},
        )
        .execute()
    )


# ── Spreadsheet structure ──────────────────────────────────────────────────────


def create_spreadsheet(title: str, sheet_names: list[str] | None = None) -> dict:
    """Create a new spreadsheet. Returns spreadsheet metadata including spreadsheetId.

    If sheet_names is provided, creates those tabs; otherwise a single 'Sheet1'.
    """
    sheets = []
    for i, name in enumerate(sheet_names or ["Sheet1"]):
        sheets.append({"properties": {"sheetId": i, "title": name, "index": i}})
    body = {"properties": {"title": title}, "sheets": sheets}
    return _get_service().spreadsheets().create(body=body).execute()


def add_sheet(spreadsheet_id: str, title: str) -> dict:
    """Add a new sheet tab to an existing spreadsheet."""
    return batch_update(
        spreadsheet_id, [{"addSheet": {"properties": {"title": title}}}]
    )


def delete_sheet(spreadsheet_id: str, sheet_name: str) -> dict | None:
    """Delete a sheet tab by name."""
    sheet_id = get_sheet_id(spreadsheet_id, sheet_name)
    if sheet_id is None:
        return None
    return batch_update(spreadsheet_id, [{"deleteSheet": {"sheetId": sheet_id}}])


def delete_rows(
    spreadsheet_id: str,
    sheet_name: str,
    start_index: int,
    end_index: int,
) -> dict | None:
    """Delete rows by 0-based index range [start_index, end_index).

    Example: delete_rows(id, 'Sheet1', 1, 3) removes rows 2 and 3 (0-indexed).
    """
    sheet_id = get_sheet_id(spreadsheet_id, sheet_name)
    if sheet_id is None:
        return None
    return batch_update(
        spreadsheet_id,
        [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start_index,
                        "endIndex": end_index,
                    }
                }
            }
        ],
    )


def batch_update(spreadsheet_id: str, requests: list[dict]) -> dict:
    """Execute a raw batchUpdate for structural changes (formatting, merges, etc.)."""
    return (
        _get_service()
        .spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        )
        .execute()
    )
