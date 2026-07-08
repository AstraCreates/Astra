from __future__ import annotations

from typing import Any

from backend.tools.google_workspace_api import google_api_request


def google_docs_create_document(founder_id: str, title: str, text: str = "") -> dict[str, Any]:
    if not founder_id or not title:
        return {"error": "founder_id and title are required"}
    _, created = google_api_request(
        founder_id,
        method="POST",
        url="https://docs.googleapis.com/v1/documents",
        services=("google_workspace", "google_docs", "google_drive", "google"),
        json_body={"title": title},
    )
    if created.get("error"):
        return created
    document_id = str(created.get("documentId") or "")
    if text.strip() and document_id:
        _, updated = google_api_request(
            founder_id,
            method="POST",
            url=f"https://docs.googleapis.com/v1/documents/{document_id}:batchUpdate",
            services=("google_workspace", "google_docs", "google_drive", "google"),
            json_body={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]},
        )
        if updated.get("error"):
            return updated
    return {
        "ok": True,
        "document_id": document_id,
        "title": created.get("title") or title,
        "url": f"https://docs.google.com/document/d/{document_id}/edit" if document_id else "",
    }


def google_sheets_create_spreadsheet(
    founder_id: str,
    title: str,
    sheet_name: str = "Sheet1",
    headers: list[Any] | None = None,
    rows: list[list[Any]] | None = None,
) -> dict[str, Any]:
    if not founder_id or not title:
        return {"error": "founder_id and title are required"}
    _, created = google_api_request(
        founder_id,
        method="POST",
        url="https://sheets.googleapis.com/v4/spreadsheets",
        services=("google_workspace", "google_sheets", "google_drive", "google"),
        json_body={
            "properties": {"title": title},
            "sheets": [{"properties": {"title": sheet_name or "Sheet1"}}],
        },
    )
    if created.get("error"):
        return created
    spreadsheet_id = str(created.get("spreadsheetId") or "")
    if spreadsheet_id:
        values: list[list[Any]] = []
        if headers:
            values.append(list(headers))
        if rows:
            values.extend([list(row) for row in rows])
        if values:
            _, updated = google_api_request(
                founder_id,
                method="PUT",
                url=f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_name}!A1",
                services=("google_workspace", "google_sheets", "google_drive", "google"),
                params={"valueInputOption": "USER_ENTERED"},
                json_body={"range": f"{sheet_name}!A1", "majorDimension": "ROWS", "values": values},
            )
            if updated.get("error"):
                return updated
    return {
        "ok": True,
        "spreadsheet_id": spreadsheet_id,
        "title": title,
        "sheet_name": sheet_name,
        "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit" if spreadsheet_id else "",
    }


def google_sheets_append_row(founder_id: str, spreadsheet_id: str, sheet_name: str, values: list[Any]) -> dict[str, Any]:
    if not founder_id or not spreadsheet_id or not sheet_name:
        return {"error": "founder_id, spreadsheet_id, and sheet_name are required"}
    _, payload = google_api_request(
        founder_id,
        method="POST",
        url=f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_name}!A1:append",
        services=("google_workspace", "google_sheets", "google_drive", "google"),
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json_body={"majorDimension": "ROWS", "values": [list(values or [])]},
    )
    if payload.get("error"):
        return payload
    updates = payload.get("updates") or {}
    return {
        "ok": True,
        "spreadsheet_id": spreadsheet_id,
        "updated_range": updates.get("updatedRange"),
        "updated_rows": updates.get("updatedRows"),
        "updated_columns": updates.get("updatedColumns"),
    }


def google_sheets_read(founder_id: str, spreadsheet_id: str, range_a1: str = "A1:Z100") -> dict[str, Any]:
    if not founder_id or not spreadsheet_id:
        return {"error": "founder_id and spreadsheet_id are required"}
    _, payload = google_api_request(
        founder_id,
        method="GET",
        url=f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_a1}",
        services=("google_workspace", "google_sheets", "google_drive", "google"),
    )
    if payload.get("error"):
        return payload
    return {
        "ok": True,
        "spreadsheet_id": spreadsheet_id,
        "range": payload.get("range") or range_a1,
        "major_dimension": payload.get("majorDimension") or "ROWS",
        "values": payload.get("values") or [],
    }


def google_slides_create_presentation(founder_id: str, title: str) -> dict[str, Any]:
    if not founder_id or not title:
        return {"error": "founder_id and title are required"}
    _, created = google_api_request(
        founder_id,
        method="POST",
        url="https://slides.googleapis.com/v1/presentations",
        services=("google_workspace", "google_slides", "google_drive", "google"),
        json_body={"title": title},
    )
    if created.get("error"):
        return created
    presentation_id = str(created.get("presentationId") or "")
    return {
        "ok": True,
        "presentation_id": presentation_id,
        "title": created.get("title") or title,
        "url": f"https://docs.google.com/presentation/d/{presentation_id}/edit" if presentation_id else "",
    }
