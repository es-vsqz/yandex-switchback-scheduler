"""
Тонкая обёртка над Google Sheets API v4 для записи лога сравнения план/факт.

Авторизация — через сервисный аккаунт (секрет GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON,
в коде его нет). Сама таблица должна быть расшарена на email сервисного аккаунта
(client_email из JSON-ключа) с правом редактора — иначе запись не пройдёт.
"""

import json
import os
import time
import urllib.error
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON", "").strip()

# Google Sheets время от времени коротко отвечает 503/500/429 без нашей вины
# (видели это несколько раз подряд на проде) — такие ответы стоит перепробовать,
# а не сразу заваливать весь прогон.
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2


class SheetsApiError(Exception):
    pass


def _urlopen_with_retry(req: urllib.request.Request):
    last_exc = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in RETRY_STATUSES or attempt == RETRY_ATTEMPTS:
                raise SheetsApiError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}")
            print(f"Google Sheets ответил {exc.code} (попытка {attempt}/{RETRY_ATTEMPTS}), повторяю через {RETRY_BACKOFF_SECONDS}с...")
            time.sleep(RETRY_BACKOFF_SECONDS)
    raise SheetsApiError(str(last_exc))


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
    with _urlopen_with_retry(req) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
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
    with _urlopen_with_retry(req) as resp:
        resp.read()
