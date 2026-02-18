"""
Transaction history PDF parser — extracts transactions from GCash/Maya/BDO
exported PDF statement files.

Uses pdfplumber for table extraction since GCash PDFs have structured tables
with columns: Date/Time, Description, Ref #, Debit, Credit, Balance.
"""

import re
from dataclasses import dataclass, field
import pdfplumber


@dataclass
class HistoryTransaction:
    """A single transaction from the history PDF."""
    date_time: str | None = None       # e.g. "Jan 28, 2026 7:58 PM"
    description: str | None = None     # e.g. "Transfer to AN***W KY*E T."
    ref_number: str | None = None      # e.g. "7037516197197"
    amount: str | None = None          # e.g. "320.00" (always positive)
    direction: str | None = None       # "debit" or "credit"
    balance: str | None = None         # running balance after transaction
    raw_row: list[str] | None = None   # raw cell values for debugging


def _clean_amount(val: str | None) -> str | None:
    """Extract numeric amount from a cell value like '320.00' or '-320.00'."""
    if not val or not val.strip():
        return None
    # Remove currency symbols, commas, spaces, and minus signs
    cleaned = re.sub(r"[₱P,\s-]", "", val.strip())
    # Must look like a number
    if re.match(r"^\d+\.?\d*$", cleaned) and float(cleaned) > 0:
        return cleaned
    return None


def _clean_ref(val: str | None) -> str | None:
    """Clean a reference number value."""
    if not val or not val.strip():
        return None
    cleaned = val.strip().replace(" ", "")
    # Must have at least some digits or be alphanumeric ref like BN-xxx
    if re.match(r"^[\dA-Z][\dA-Z\-]{5,}$", cleaned, re.IGNORECASE):
        return cleaned
    return None


def _normalize_date(val: str | None) -> str | None:
    """Normalize a date string."""
    if not val or not val.strip():
        return None
    return re.sub(r"\s+", " ", val.strip())


def parse_pdf_tables(pdf_path_or_bytes, is_bytes: bool = False) -> list[HistoryTransaction]:
    """
    Parse transaction rows from a GCash/Maya/BDO PDF statement.
    
    Args:
        pdf_path_or_bytes: file path string or bytes of the PDF
        is_bytes: True if pdf_path_or_bytes is bytes
    
    Returns:
        List of HistoryTransaction objects
    """
    if is_bytes:
        import io
        pdf = pdfplumber.open(io.BytesIO(pdf_path_or_bytes))
    else:
        pdf = pdfplumber.open(pdf_path_or_bytes)

    transactions: list[HistoryTransaction] = []

    for page in pdf.pages:
        # Try table extraction first (structured PDFs)
        tables = page.extract_tables()
        if tables:
            for table in tables:
                transactions.extend(_parse_table_rows(table))
        else:
            # Fall back to text extraction for unstructured PDFs
            text = page.extract_text()
            if text:
                transactions.extend(_parse_raw_text(text))

    pdf.close()
    return transactions


def _detect_columns(header_row: list[str]) -> dict[str, int]:
    """
    Detect column indices from a header row.
    Returns a dict mapping field names to column indices.
    """
    col_map: dict[str, int] = {}
    if not header_row:
        return col_map

    for i, cell in enumerate(header_row):
        if not cell:
            continue
        cell_lower = cell.strip().lower()

        if any(k in cell_lower for k in ["date", "time", "timestamp"]):
            col_map["date_time"] = i
        elif any(k in cell_lower for k in ["description", "details", "transaction", "particulars"]):
            col_map["description"] = i
        elif any(k in cell_lower for k in ["ref", "reference"]):
            col_map["ref_number"] = i
        elif "debit" in cell_lower or "out" in cell_lower:
            col_map["debit"] = i
        elif "credit" in cell_lower or "in" in cell_lower:
            col_map["credit"] = i
        elif "balance" in cell_lower:
            col_map["balance"] = i
        elif "amount" in cell_lower:
            col_map["amount"] = i
        elif "fee" in cell_lower:
            col_map["fee"] = i
        elif "status" in cell_lower:
            col_map["status"] = i

    return col_map


def _parse_table_rows(table: list[list[str]]) -> list[HistoryTransaction]:
    """Parse transactions from a single extracted table."""
    if not table or len(table) < 2:
        return []

    # First row is likely the header
    header = table[0]
    col_map = _detect_columns(header)

    # If we couldn't detect columns, try the second row as header
    if len(col_map) < 2 and len(table) > 2:
        header = table[1]
        col_map = _detect_columns(header)
        data_rows = table[2:]
    else:
        data_rows = table[1:]

    # If still no columns detected, try positional guess
    # Common GCash layout: [Date, Description, Ref, Debit, Credit, Balance]
    if len(col_map) < 2:
        num_cols = len(header) if header else 0
        if num_cols >= 5:
            col_map = {
                "date_time": 0,
                "description": 1,
                "ref_number": 2,
                "debit": 3,
                "credit": 4,
            }
            if num_cols >= 6:
                col_map["balance"] = 5

    transactions: list[HistoryTransaction] = []
    for row in data_rows:
        if not row or all(not cell or not cell.strip() for cell in row):
            continue

        # Skip rows that look like headers repeated
        row_text = " ".join(str(c) for c in row if c).lower()
        if "date" in row_text and "description" in row_text:
            continue

        txn = _row_to_transaction(row, col_map)
        if txn and (txn.amount or txn.ref_number):
            transactions.append(txn)

    return transactions


def _row_to_transaction(row: list[str], col_map: dict[str, int]) -> HistoryTransaction | None:
    """Convert a table row into a HistoryTransaction using the column map."""

    def get(field: str) -> str | None:
        idx = col_map.get(field)
        if idx is not None and idx < len(row):
            return row[idx]
        return None

    date_time = _normalize_date(get("date_time"))
    description = get("description")
    ref_number = _clean_ref(get("ref_number"))

    # Determine amount and direction from debit/credit columns
    debit_val = _clean_amount(get("debit"))
    credit_val = _clean_amount(get("credit"))
    amount_val = _clean_amount(get("amount"))

    if debit_val:
        amount = debit_val
        direction = "debit"
    elif credit_val:
        amount = credit_val
        direction = "credit"
    elif amount_val:
        amount = amount_val
        direction = "unknown"
    else:
        amount = None
        direction = None

    balance = _clean_amount(get("balance"))

    return HistoryTransaction(
        date_time=date_time,
        description=description.strip() if description else None,
        ref_number=ref_number,
        amount=amount,
        direction=direction,
        balance=balance,
        raw_row=[str(c) for c in row],
    )


# ---------------------------------------------------------------------------
# Fallback: raw text parsing for non-table PDFs
# ---------------------------------------------------------------------------

# Patterns for extracting transactions from raw text
_DATE_PATTERN = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*"
    r"\s+\d{1,2},?\s+\d{4}"
    r"(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)?)",
    re.IGNORECASE,
)

_REF_IN_TEXT = re.compile(
    r"(?:Ref\.?\s*(?:No\.?|#|Number)?|Reference\s*(?:No\.?|#)?)\s*:?\s*"
    r"([A-Z0-9][\w\-]{5,})",
    re.IGNORECASE,
)

_AMOUNT_IN_TEXT = re.compile(
    r"(?:[₱P]|PHP)\s*([0-9,]+\.\d{2})",
    re.IGNORECASE,
)


def _parse_raw_text(text: str) -> list[HistoryTransaction]:
    """Parse transactions from raw text (fallback for non-table PDFs)."""
    transactions: list[HistoryTransaction] = []
    lines = text.split("\n")

    current_date = None
    current_ref = None
    current_amount = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Try to find date
        date_match = _DATE_PATTERN.search(line)
        if date_match:
            # If we have a pending transaction, save it
            if current_ref or current_amount:
                transactions.append(HistoryTransaction(
                    date_time=current_date,
                    ref_number=current_ref,
                    amount=current_amount,
                    direction="unknown",
                    description=line,
                ))
                current_ref = None
                current_amount = None
            current_date = date_match.group(1).strip()

        # Try to find ref number
        ref_match = _REF_IN_TEXT.search(line)
        if ref_match:
            current_ref = ref_match.group(1).replace(" ", "")

        # Try to find amount
        amt_match = _AMOUNT_IN_TEXT.search(line)
        if amt_match:
            current_amount = amt_match.group(1).replace(",", "")

    # Save last pending transaction
    if current_ref or current_amount:
        transactions.append(HistoryTransaction(
            date_time=current_date,
            ref_number=current_ref,
            amount=current_amount,
            direction="unknown",
        ))

    return transactions
