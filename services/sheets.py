# services/sheets.py
import os
import logging
from typing import Optional, Tuple, List
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SHEETS_ID = os.getenv("SHEETS_ID")
SHEET_NAME = os.getenv("SHEET_NAME")
SERVICE_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
TOTAL_COLUMNS = int(os.getenv("SHEETS_TOTAL_COLUMNS", "15"))
SHEET_GID = int(os.getenv("SHEET_GID", "0"))

if not SHEETS_ID:
    raise RuntimeError("SHEETS_ID не задан")
if not SHEET_NAME:
    raise RuntimeError("SHEET_NAME не задан")
if not SERVICE_FILE:
    raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE не задан")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_FILE, scopes=SCOPES
)
service = build("sheets", "v4", credentials=credentials)
sheet = service.spreadsheets()


def _pad_row(values: list, total: int) -> list:
    """Возвращает список ровно из `total` элементов, дополняя пустыми в конце."""
    v = list(values)[:total]
    if len(v) < total:
        v += [""] * (total - len(v))
    return v


def _col_letter(idx_1_based: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA ..."""
    s, n = "", idx_1_based
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def append_row_to_sheets(values: list) -> Tuple[bool, object]:
    """
    Вставляет новую строку в начало листа (index 0) и записывает туда values.
    Возвращает (True, result) или (False, error_str).

    Реализация:
    1) Используем numeric `SHEET_GID` из .env.
    2) Делаем batchUpdate с request 'insertDimension' (insert row at start после заголовка).
    3) Записываем значения в A2.. (обязательно pad до TOTAL_COLUMNS).
    """
    try:
        # 1) Вставляем пустую строку в начало (вторая строка, т.к. первая — заголовок)
        requests = [
            {
                "insertDimension": {
                    "range": {
                        "sheetId": SHEET_GID,
                        "dimension": "ROWS",
                        "startIndex": 1,
                        "endIndex": 2,
                    },
                    "inheritFromBefore": False,
                }
            }
        ]
        batch_body = {"requests": requests}
        service.spreadsheets().batchUpdate(
            spreadsheetId=SHEETS_ID, body=batch_body
        ).execute()

        # 2) Записываем значения во вторую строку A2.. (обязательно pad до TOTAL_COLUMNS)
        row = _pad_row(values, TOTAL_COLUMNS)
        result = sheet.values().update(
            spreadsheetId=SHEETS_ID,
            range=f"{SHEET_NAME}!A2",
            valueInputOption="RAW",
            body={"values": [row]},
        ).execute()

        logger.debug("sheets.prepend result: %s", result)
        return True, result

    except Exception as e:
        logger.exception("SHEETS ERROR append_row_to_sheets")
        return False, str(e)


def find_row_by_id(record_id: str) -> Optional[int]:
    """
    Возвращает 1-based номер строки, где в кол. A равен record_id. None если не нашли.
    """
    try:
        res = sheet.values().get(spreadsheetId=SHEETS_ID, range=f"{SHEET_NAME}!A:A").execute()
        values = res.get("values", [])
        for i, row in enumerate(values, start=1):
            if row and len(row) >= 1 and row[0] == record_id:
                return i
        return None
    except Exception:
        logger.exception("SHEETS ERROR find_row_by_id")
        return None


def update_cell(row_idx_1_based: int, col_idx_1_based: int, value: str) -> Tuple[bool, object]:
    """Обновляет одну ячейку. Возвращает (True, result) или (False, error_str)."""
    try:
        rng = f"{SHEET_NAME}!{_col_letter(col_idx_1_based)}{row_idx_1_based}"
        body = {"values": [[value]]}
        result = sheet.values().update(
            spreadsheetId=SHEETS_ID,
            range=rng,
            valueInputOption="RAW",
            body=body,
        ).execute()
        logger.debug("sheets.update_cell %s = %s -> %s", rng, value, result)
        return True, result
    except Exception as e:
        logger.exception("SHEETS ERROR update_cell")
        return False, str(e)


def update_messenger_by_id(record_id: str, messenger: str) -> Tuple[bool, object]:
    """
    Находим строку по id (A) и пишем messenger в колонку O (по умолчанию 15).
    Возвращает (True, result) или (False, error_str).
    """
    try:
        row = find_row_by_id(record_id)
        if not row:
            logger.warning("update_messenger_by_id: ID not found %s", record_id)
            return False, "ID not found"
        # колонка O = 15 (1-based)
        return update_cell(row, 15, messenger)
    except Exception:
        logger.exception("SHEETS ERROR update_messenger_by_id")
        return False, "internal error"
