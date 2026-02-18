"""
Receipt parsers — extract transaction ID, amount, and time from OCR text lines.
Tailored for GCash, PayMaya/Maya, and BDO Pay receipt formats.
"""

import re
from dataclasses import dataclass


@dataclass
class ReceiptData:
    """Parsed receipt fields."""
    provider: str | None = None          # "gcash", "paymaya", "bdo", or None
    transaction_id: str | None = None    # Reference / transaction number
    amount: str | None = None            # e.g. "320.00"
    time: str | None = None              # e.g. "Feb 5, 2026 7:23 PM"
    raw_text: list[str] | None = None    # all OCR lines for debugging


def detect_provider(lines: list[str]) -> str | None:
    """Detect whether the receipt is from GCash, PayMaya, or BDO Pay."""
    combined = " ".join(lines).lower()

    # Check BDO FIRST — BDO receipts can mention "Gcash" as the recipient
    # (e.g. "G-Xchange, Inc. / Gcash") so must be detected before GCash
    if "bdo" in combined or "bdopay" in combined:
        return "bdo"
    if "gcash" in combined or "g cash" in combined or "g-xchange" in combined:
        return "gcash"
    if "paymaya" in combined or "maya" in combined:
        return "paymaya"

    # GCash "Transaction Details" screen — doesn't say "GCash" but has
    # identifiable keywords like "Transaction Details" and "Transfer from"
    if "transaction details" in combined and "transfer from" in combined:
        return "gcash"

    return None


def _normalize_spaces(text: str) -> str:
    """Collapse multiple spaces into one and fix OCR-merged date/time."""
    text = re.sub(r"\s+", " ", text).strip()
    # Fix OCR-merged year+time like "202610:59PM" → "2026 10:59PM"
    text = re.sub(r"(\d{4})(\d{1,2}:\d{2})", r"\1 \2", text)
    return text


# ---------------------------------------------------------------------------
# Reference Number extraction
# ---------------------------------------------------------------------------

# GCash uses "Ref No." or "Ref. No." followed by digits (sometimes with spaces)
_REF_NO_PATTERN = re.compile(
    r"(?:Ref\.?\s*(?:No\.?|Number)?|Reference\s*(?:No\.?|Number)?|Transaction\s*(?:No\.?|Number|ID)?)"
    r"[\s.:]*"
    r"(\d[\d\s]{8,})",
    re.IGNORECASE,
)

# BDO Pay uses "Reference no." followed by alphanumeric with dashes (e.g. "BN-20260128-49830535")
_ALPHANUMERIC_REF_PATTERN = re.compile(
    r"(?:Ref(?:erence)?\s*(?:No\.?|Number)?|Transaction\s*(?:No\.?|Number|ID)?)"
    r"[\s.:]*"
    r"([A-Z]{2,}-[\w-]{8,})",
    re.IGNORECASE,
)

# Fallback: standalone 13-digit number (common GCash ref format)
_STANDALONE_REF_PATTERN = re.compile(r"\b(\d{13})\b")

# Fallback: 10+ digits possibly with spaces between groups
_SPACED_REF_PATTERN = re.compile(r"\b(\d{4}\s?\d{3}\s?\d{3,6})\b")

# Fallback: BDO-style alphanumeric ref anywhere (e.g. "BN-20260128-49830535")
_BDO_REF_PATTERN = re.compile(r"\b([A-Z]{2,}-\d{8}-\d{6,})\b", re.IGNORECASE)


def _extract_ref_no(lines: list[str]) -> str | None:
    """Extract the reference / transaction number."""

    def _clean_ref(raw: str, max_digits: int = 13) -> str:
        """Remove spaces and cap at max_digits to avoid adjacent text pollution."""
        digits = raw.replace(" ", "")
        return digits[:max_digits]

    # 1. Try alphanumeric ref pattern first (BDO Pay: "BN-20260128-49830535")
    for line in lines:
        m = _ALPHANUMERIC_REF_PATTERN.search(line)
        if m:
            return m.group(1).strip()

    # Also check combined text for alphanumeric refs
    combined = " ".join(lines)
    m = _ALPHANUMERIC_REF_PATTERN.search(combined)
    if m:
        return m.group(1).strip()

    # 2. Try numeric ref pattern per-line (GCash: "Ref No. 7037516197197")
    for line in lines:
        m = _REF_NO_PATTERN.search(line)
        if m:
            return _clean_ref(m.group(1))

    # Then try combined text (for cases where ref spans multiple OCR lines)
    m = _REF_NO_PATTERN.search(combined)
    if m:
        return _clean_ref(m.group(1))

    # 3. Fallback: BDO-style alphanumeric ref anywhere
    for line in lines:
        m = _BDO_REF_PATTERN.search(line)
        if m:
            return m.group(1)

    # 4. Fallback: look for a standalone 13-digit number
    for line in lines:
        m = _STANDALONE_REF_PATTERN.search(line)
        if m:
            return m.group(1)

    # 5. Fallback: spaced digit groups that form 10+ digits
    for line in lines:
        m = _SPACED_REF_PATTERN.search(line)
        if m:
            val = m.group(1).replace(" ", "")
            if len(val) >= 10:
                return val[:13]

    return None


# ---------------------------------------------------------------------------
# Amount extraction
# ---------------------------------------------------------------------------

# Matches amounts like "₱320.00", "P320.00", "PHP 320.00", "320.00"
_AMOUNT_PATTERN = re.compile(
    r"(?:[₱P]|PHP)\s*([0-9,]+\.?\d*)",
    re.IGNORECASE,
)

# "Amount" label followed by a number (GCash format: "Amount    320.00")
_AMOUNT_LABEL_PATTERN = re.compile(
    r"(?:Amount|Total\s*Amount\s*Sent?)[\s.:]*([0-9,]+\.\d{2})",
    re.IGNORECASE,
)

# Simple decimal number on its own line
_PLAIN_AMOUNT_PATTERN = re.compile(r"\b([0-9,]+\.\d{2})\b")


def _extract_amount(lines: list[str]) -> str | None:
    """Extract the transaction amount."""
    # Strategy: look for "Total Amount Sent" first (most specific),
    # then headline "PHP xxx.xx", then "Amount" label, then ₱/PHP prefix,
    # then plain decimals.

    combined = " ".join(lines)

    # 1. "Total Amount Sent ₱320.00" (big bold number on GCash receipts)
    total_pattern = re.compile(
        r"Total\s*Amount\s*Sent?\s*[₱P]?\s*([0-9,]+\.\d{2})",
        re.IGNORECASE,
    )
    m = total_pattern.search(combined)
    if m:
        return m.group(1).replace(",", "")

    # 2. Standalone "PHP xxx.xx" line (BDO Pay headline amount)
    #    Look for the FIRST "PHP xxx.xx" that is NOT preceded by "Send Money"
    #    or "Service Fee" to get the total, not a sub-line.
    headline_pattern = re.compile(
        r"^\s*PHP\s+([0-9,]+\.\d{2})\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    for line in lines:
        line_stripped = line.strip()
        # Skip sub-labels like "Send Money Amount PHP 320.00"
        if re.search(r"(?:send\s*money|service\s*fee)", line_stripped, re.IGNORECASE):
            continue
        m = headline_pattern.match(line_stripped)
        if m:
            return m.group(1).replace(",", "")

    # 3. "Amount" label
    for line in lines:
        m = _AMOUNT_LABEL_PATTERN.search(line)
        if m:
            return m.group(1).replace(",", "")

    # 4. Currency symbol prefix (₱, P, PHP)
    for line in lines:
        # Skip sub-labels
        if re.search(r"(?:send\s*money|service\s*fee)", line, re.IGNORECASE):
            continue
        m = _AMOUNT_PATTERN.search(line)
        if m:
            return m.group(1).replace(",", "")

    # 5. Any PHP-prefixed amount (including sub-labels as last resort)
    for line in lines:
        m = _AMOUNT_PATTERN.search(line)
        if m:
            return m.group(1).replace(",", "")

    # 6. Plain decimal (use first one that looks like money)
    amounts = []
    for line in lines:
        for m in _PLAIN_AMOUNT_PATTERN.finditer(line):
            val = m.group(1).replace(",", "")
            try:
                if float(val) > 0:
                    amounts.append(val)
            except ValueError:
                continue
    if amounts:
        return amounts[0]

    return None


# ---------------------------------------------------------------------------
# Date/Time extraction
# ---------------------------------------------------------------------------

# GCash format: "Jan 28, 2026 7:58 PM" or "Feb 5, 2026 7:23 PM"
# Also handles OCR-merged format: "Feb 12, 202610:59PM" (no space before time)
_DATETIME_PATTERN = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*"  # month
    r"\s+\d{1,2},?\s+\d{4}"                                      # day, year
    r"\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)",                    # time (\s* allows merged)
    re.IGNORECASE,
)

# Numeric date format: "01/28/2026 19:58" or "2026-01-28 7:58 PM"
_NUMERIC_DATE_PATTERN = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?"
    r"|\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)",
    re.IGNORECASE,
)


def _extract_time(lines: list[str]) -> str | None:
    """Extract the date/time from the receipt."""
    combined = " ".join(lines)

    # GCash text-based date
    m = _DATETIME_PATTERN.search(combined)
    if m:
        return _normalize_spaces(m.group(1))

    # Per-line search
    for line in lines:
        m = _DATETIME_PATTERN.search(line)
        if m:
            return _normalize_spaces(m.group(1))

    # Numeric date format
    m = _NUMERIC_DATE_PATTERN.search(combined)
    if m:
        return _normalize_spaces(m.group(1))

    for line in lines:
        m = _NUMERIC_DATE_PATTERN.search(line)
        if m:
            return _normalize_spaces(m.group(1))

    return None


# ---------------------------------------------------------------------------
# Main parse function
# ---------------------------------------------------------------------------

def parse_receipt(lines: list[str]) -> ReceiptData:
    """
    Parse OCR text lines from a GCash, PayMaya, or BDO Pay receipt.
    Returns a ReceiptData object with extracted fields.
    """
    provider = detect_provider(lines)
    transaction_id = _extract_ref_no(lines)
    amount = _extract_amount(lines)
    time = _extract_time(lines)

    return ReceiptData(
        provider=provider,
        transaction_id=transaction_id,
        amount=amount,
        time=time,
        raw_text=lines,
    )
