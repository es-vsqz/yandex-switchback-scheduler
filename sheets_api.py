"""
Тонкая обёртка над Google Sheets API v4 для записи лога сравнения план/факт.

Авторизация — через сервисный аккаунт (секрет GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON,
в коде его нет). Сама таблица должна быть расшарена на email сервисного аккаунта
(client_email из JSON-ключа) с правом редактора — иначе запись не пройдёт.
"""

import json
import os
import urllib.error
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON", "").strip()


class SheetsApiError(Exception):
    pass


def _access_token() -> str:
    if not SERVICE_ACCOUNT_JSON:
        raise SheetsApiError("Не найден секрет GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON.")
    try:
        info = json.loads(SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError:
        raise SheetsApiError("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON не похож на корректный JSON.")
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    creds.refresh(Request())
    return creds.token


def get_first_sheet_title(spreadsheet_id: str) -> str:
    """Название первой вкладки — чтобы не гадать между 'Sheet1' и 'Лист1' по локали аккаунта."""
    token = _access_token()
    req = urllib.request.Request(
        f"{SHEETS_API}/{spreadsheet_id}?fields=sheets.properties.title",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SheetsApiError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}")
    return payload["sheets"][0]["properties"]["title"]


def append_rows(spreadsheet_id: str, sheet_name: str, rows: list) -> None:
    """Добавляет строки в конец листа (append), не трогая уже существующие."""
    token = _access_token()
    url = f"{SHEETS_API}/{spreadsheet_id}/values/{sheet_name}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS"
    body = json.dumps({"values": rows}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        raise SheetsApiError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}")
