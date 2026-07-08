from __future__ import annotations

import io
import json
from typing import Any

from backend.tools.google_workspace_api import google_api_request


def _doc_text_from_content(content: list[dict[str, Any]] | None) -> str:
    chunks: list[str] = []
    for el in content or []:
        para = ((el.get("paragraph") or {}).get("elements") or [])
        for part in para:
            text_run = (part.get("textRun") or {}).get("content")
            if text_run:
                chunks.append(str(text_run))
    return "".join(chunks).strip()


def _json_or_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True)
    except Exception:
        return str(value)


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


def google_docs_append_text(founder_id: str, document_id: str, text: str) -> dict[str, Any]:
    if not founder_id or not document_id or not text.strip():
        return {"error": "founder_id, document_id, and text are required"}
    _, doc = google_api_request(
        founder_id,
        method="GET",
        url=f"https://docs.googleapis.com/v1/documents/{document_id}",
        services=("google_workspace", "google_docs", "google_drive", "google"),
    )
    if doc.get("error"):
        return doc
    end_index = int(doc.get("body", {}).get("content", [{}])[-1].get("endIndex") or 1)
    _, updated = google_api_request(
        founder_id,
        method="POST",
        url=f"https://docs.googleapis.com/v1/documents/{document_id}:batchUpdate",
        services=("google_workspace", "google_docs", "google_drive", "google"),
        json_body={"requests": [{"insertText": {"location": {"index": max(1, end_index - 1)}, "text": text}}]},
    )
    if updated.get("error"):
        return updated
    return {"ok": True, "document_id": document_id, "written": len(text)}


def google_docs_read_document(founder_id: str, document_id: str) -> dict[str, Any]:
    if not founder_id or not document_id:
        return {"error": "founder_id and document_id are required"}
    _, payload = google_api_request(
        founder_id,
        method="GET",
        url=f"https://docs.googleapis.com/v1/documents/{document_id}",
        services=("google_workspace", "google_docs", "google_drive", "google"),
    )
    if payload.get("error"):
        return payload
    body = payload.get("body", {}) or {}
    content = body.get("content") or []
    return {
        "ok": True,
        "document_id": document_id,
        "title": payload.get("title") or "",
        "text": _doc_text_from_content(content),
        "url": f"https://docs.google.com/document/d/{document_id}/edit",
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


def google_sheets_update_range(founder_id: str, spreadsheet_id: str, range_a1: str, values: list[list[Any]]) -> dict[str, Any]:
    if not founder_id or not spreadsheet_id or not range_a1:
        return {"error": "founder_id, spreadsheet_id, and range_a1 are required"}
    _, payload = google_api_request(
        founder_id,
        method="PUT",
        url=f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_a1}",
        services=("google_workspace", "google_sheets", "google_drive", "google"),
        params={"valueInputOption": "USER_ENTERED"},
        json_body={"range": range_a1, "majorDimension": "ROWS", "values": [list(row) for row in (values or [])]},
    )
    if payload.get("error"):
        return payload
    return {
        "ok": True,
        "spreadsheet_id": spreadsheet_id,
        "updated_range": payload.get("updatedRange") or range_a1,
        "updated_rows": payload.get("updatedRows"),
        "updated_columns": payload.get("updatedColumns"),
        "updated_cells": payload.get("updatedCells"),
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


def google_slides_add_slide(founder_id: str, presentation_id: str, title: str = "", body: str = "") -> dict[str, Any]:
    if not founder_id or not presentation_id:
        return {"error": "founder_id and presentation_id are required"}
    slide_id = "slide_" + presentation_id[-8:]
    title_id = slide_id + "_title"
    body_id = slide_id + "_body"
    requests = [{
        "createSlide": {
            "objectId": slide_id,
            "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
            "placeholderIdMappings": [
                {"layoutPlaceholder": {"type": "TITLE", "index": 0}, "objectId": title_id},
                {"layoutPlaceholder": {"type": "BODY", "index": 0}, "objectId": body_id},
            ],
        }
    }]
    if title:
        requests.append({"insertText": {"objectId": title_id, "insertionIndex": 0, "text": title}})
    if body:
        requests.append({"insertText": {"objectId": body_id, "insertionIndex": 0, "text": body}})
    _, payload = google_api_request(
        founder_id,
        method="POST",
        url=f"https://slides.googleapis.com/v1/presentations/{presentation_id}:batchUpdate",
        services=("google_workspace", "google_slides", "google_drive", "google"),
        json_body={"requests": requests},
    )
    if payload.get("error"):
        return payload
    return {"ok": True, "presentation_id": presentation_id, "slide_id": slide_id}


def google_drive_list_files(founder_id: str, query: str = "", page_size: int = 20) -> dict[str, Any]:
    if not founder_id:
        return {"error": "founder_id is required"}
    _, payload = google_api_request(
        founder_id,
        method="GET",
        url="https://www.googleapis.com/drive/v3/files",
        services=("google_workspace", "google_drive", "google"),
        params={
            "pageSize": max(1, min(int(page_size or 20), 100)),
            "q": query or None,
            "fields": "files(id,name,mimeType,webViewLink,modifiedTime,size),nextPageToken",
            "orderBy": "modifiedTime desc",
        },
    )
    if payload.get("error"):
        return payload
    return {"ok": True, "files": payload.get("files") or [], "next_page_token": payload.get("nextPageToken") or ""}


def google_drive_create_text_file(founder_id: str, name: str, content: str, mime_type: str = "text/plain") -> dict[str, Any]:
    if not founder_id or not name:
        return {"error": "founder_id and name are required"}
    boundary = "astra-google-upload"
    meta = json.dumps({"name": name, "mimeType": mime_type})
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--"
    )
    _, payload = google_api_request(
        founder_id,
        method="POST",
        url="https://www.googleapis.com/upload/drive/v3/files",
        services=("google_workspace", "google_drive", "google"),
        params={"uploadType": "multipart", "fields": "id,name,webViewLink,mimeType"},
        data=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )
    if payload.get("error"):
        return payload
    return {"ok": True, "file_id": payload.get("id") or "", "name": payload.get("name") or name, "url": payload.get("webViewLink") or ""}


def google_drive_read_file(founder_id: str, file_id: str) -> dict[str, Any]:
    if not founder_id or not file_id:
        return {"error": "founder_id and file_id are required"}
    _, meta = google_api_request(
        founder_id,
        method="GET",
        url=f"https://www.googleapis.com/drive/v3/files/{file_id}",
        services=("google_workspace", "google_drive", "google"),
        params={"fields": "id,name,mimeType,webViewLink,size"},
    )
    if meta.get("error"):
        return meta
    mime_type = str(meta.get("mimeType") or "")
    if mime_type == "application/vnd.google-apps.document":
        return google_docs_read_document(founder_id, file_id)
    export_mime = None
    if mime_type == "application/vnd.google-apps.spreadsheet":
        export_mime = "text/csv"
    elif mime_type == "application/vnd.google-apps.presentation":
        export_mime = "text/plain"
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
    params = {"alt": "media"}
    if export_mime:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
        params = {"mimeType": export_mime}
    resp, payload = google_api_request(
        founder_id,
        method="GET",
        url=url,
        services=("google_workspace", "google_drive", "google"),
        params=params,
        headers={"Accept": export_mime or "text/plain,application/json,*/*"},
    )
    if payload.get("error"):
        return payload
    text = ""
    if resp is not None:
        try:
            text = resp.text
        except Exception:
            text = ""
    return {
        "ok": True,
        "file_id": file_id,
        "name": meta.get("name") or "",
        "mime_type": mime_type,
        "url": meta.get("webViewLink") or "",
        "text": text[:200000],
    }


def google_calendar_create_event(
    founder_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    timezone: str = "UTC",
) -> dict[str, Any]:
    if not founder_id or not summary or not start_time or not end_time:
        return {"error": "founder_id, summary, start_time, and end_time are required"}
    _, payload = google_api_request(
        founder_id,
        method="POST",
        url="https://www.googleapis.com/calendar/v3/calendars/primary/events",
        services=("google_workspace", "google_calendar", "google_drive", "google"),
        json_body={
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_time, "timeZone": timezone or "UTC"},
            "end": {"dateTime": end_time, "timeZone": timezone or "UTC"},
        },
    )
    if payload.get("error"):
        return payload
    return {
        "ok": True,
        "event_id": payload.get("id") or "",
        "html_link": payload.get("htmlLink") or "",
        "status": payload.get("status") or "",
    }


def google_calendar_list_events(founder_id: str, time_min: str = "", time_max: str = "", max_results: int = 10) -> dict[str, Any]:
    if not founder_id:
        return {"error": "founder_id is required"}
    _, payload = google_api_request(
        founder_id,
        method="GET",
        url="https://www.googleapis.com/calendar/v3/calendars/primary/events",
        services=("google_workspace", "google_calendar", "google_drive", "google"),
        params={
            "timeMin": time_min or None,
            "timeMax": time_max or None,
            "maxResults": max(1, min(int(max_results or 10), 100)),
            "singleEvents": "true",
            "orderBy": "startTime",
        },
    )
    if payload.get("error"):
        return payload
    return {
        "ok": True,
        "events": [
            {
                "id": item.get("id"),
                "summary": item.get("summary"),
                "status": item.get("status"),
                "html_link": item.get("htmlLink"),
                "start": item.get("start"),
                "end": item.get("end"),
            }
            for item in (payload.get("items") or [])
        ],
    }
