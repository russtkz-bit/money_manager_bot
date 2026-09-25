"""
csv_import.py — parses bank/card statement exports (CSV) into transaction
rows ready for database.add_transaction().

Bank CSV exports vary wildly in column names, delimiter, date format and
decimal separator, so this looks for common header aliases and sniffs the
format rather than requiring one exact layout. It never touches the
database or Telegram — bot.py drives those from the rows this returns, so
the parsing logic itself stays testable in isolation.
"""

import csv
import io
from datetime import datetime
from typing import Dict, List, Optional, Tuple

DATE_HEADERS = {
    "date", "дата", "transaction date", "posted date", "дата операции",
    "дата платежа",
}
DESC_HEADERS = {
    "description", "описание", "merchant", "payee", "details",
    "назначение платежа", "описание операции",
}
AMOUNT_HEADERS = {"amount", "сумма", "сумма операции"}
DEBIT_HEADERS = {"debit", "расход", "withdrawal", "expense", "списание"}
CREDIT_HEADERS = {"credit", "приход", "deposit", "income", "поступление", "зачисление"}

DATE_FORMATS = [
    "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y",
    "%d.%m.%y", "%Y-%m-%dT%H:%M:%S",
]

# Guardrails so one huge/malformed upload can't hang the bot or blow up memory.
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000


class CsvImportError(Exception):
    """Raised when the file can't be parsed at all (wrong encoding, empty,
    no recognizable columns) — as opposed to individual bad rows, which are
    collected as `errors` instead of aborting the whole import."""


def _parse_date(raw: str) -> Optional[str]:
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Optional[float]:
    raw = raw.strip().replace(" ", "").replace("\xa0", "")
    if not raw:
        return None
    if raw.startswith("+"):
        raw = raw[1:]
    if "," in raw and "." in raw:
        # Whichever separator appears last is the decimal point:
        # "1.234,56" (EU) vs "1,234.56" (US).
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        parts = raw.split(",")
        # A thousands separator always groups digits in 3s, so any other
        # trailing group length (most commonly 1 or 2, e.g. "12,5" or
        # "12,50") can only be a decimal comma — treating "== 2" as the
        # only decimal case silently mis-parsed "12,5" as 125.
        if len(parts[-1]) != 3:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _find_column(headers: List[str], candidates: set) -> Optional[int]:
    for i, h in enumerate(headers):
        if h.strip().lower() in candidates:
            return i
    return None


def parse_statement(raw_bytes: bytes) -> Tuple[List[Dict], List[str]]:
    """Parse a bank statement CSV.

    Returns (rows, errors):
      rows: [{"date": "YYYY-MM-DD", "amount": float>0, "type": "income"|"expense",
              "description": str}, ...]
      errors: human-readable strings for individual rows that couldn't be
              parsed (the rest of the file is still processed).

    Raises CsvImportError if the file can't be read at all or none of its
    columns look like a date/amount.
    """
    if len(raw_bytes) > MAX_FILE_BYTES:
        raise CsvImportError("file_too_large")

    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise CsvImportError("unreadable_encoding")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    rows_raw = list(reader)
    if not rows_raw:
        raise CsvImportError("empty_file")
    if len(rows_raw) - 1 > MAX_ROWS:
        raise CsvImportError("too_many_rows")

    header = rows_raw[0]
    date_i = _find_column(header, DATE_HEADERS)
    desc_i = _find_column(header, DESC_HEADERS)
    amount_i = _find_column(header, AMOUNT_HEADERS)
    debit_i = _find_column(header, DEBIT_HEADERS)
    credit_i = _find_column(header, CREDIT_HEADERS)

    if date_i is None or (amount_i is None and debit_i is None and credit_i is None):
        raise CsvImportError("unrecognized_columns")

    rows: List[Dict] = []
    errors: List[str] = []
    for line_no, raw_row in enumerate(rows_raw[1:], start=2):
        if not raw_row or all(not c.strip() for c in raw_row):
            continue

        date_str = _parse_date(raw_row[date_i]) if date_i < len(raw_row) else None
        if not date_str:
            errors.append(f"row {line_no}: unrecognized date")
            continue

        description = raw_row[desc_i].strip() if desc_i is not None and desc_i < len(raw_row) else ""

        if amount_i is not None:
            amt = _parse_amount(raw_row[amount_i]) if amount_i < len(raw_row) else None
            if amt is None:
                errors.append(f"row {line_no}: unrecognized amount")
                continue
            t_type = "income" if amt >= 0 else "expense"
            amount = abs(amt)
        else:
            debit = _parse_amount(raw_row[debit_i]) if debit_i is not None and debit_i < len(raw_row) else None
            credit = _parse_amount(raw_row[credit_i]) if credit_i is not None and credit_i < len(raw_row) else None
            if credit:
                t_type, amount = "income", abs(credit)
            elif debit:
                t_type, amount = "expense", abs(debit)
            else:
                errors.append(f"row {line_no}: no amount in debit/credit columns")
                continue

        if amount == 0:
            continue

        rows.append({
            "date": date_str,
            "amount": amount,
            "type": t_type,
            "description": description[:255],
        })

    return rows, errors
