"""
Receipt-to-history matcher — cross-references receipt images against
transaction history entries to verify authenticity.

Each receipt gets a verdict:
  - "matched"    — found in transaction history (ref + amount match)
  - "not_found"  — no matching transaction in history at all
  - "mismatch"   — partial match (ref found but amount/time differs)
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from parsers import ReceiptData
from history_parser import HistoryTransaction


@dataclass
class MatchResult:
    """Result of matching a single receipt against transaction history."""
    receipt_filename: str | None = None
    verdict: str = "not_found"       # "matched", "not_found", "mismatch"
    receipt_ref: str | None = None
    receipt_amount: str | None = None
    receipt_time: str | None = None
    history_ref: str | None = None
    history_amount: str | None = None
    history_time: str | None = None
    details: str | None = None       # human-readable explanation


def _normalize_ref(ref: str | None) -> str | None:
    """Normalize a ref number for comparison (strip spaces, dashes, lowercase)."""
    if not ref:
        return None
    return re.sub(r"[\s\-]", "", ref).lower()


def _normalize_amount(amount: str | None) -> float | None:
    """Convert amount string to float for comparison."""
    if not amount:
        return None
    try:
        return float(amount.replace(",", ""))
    except ValueError:
        return None


def _parse_time(time_str: str | None) -> datetime | None:
    """Try to parse various date/time formats."""
    if not time_str:
        return None

    formats = [
        "%b %d, %Y %I:%M %p",     # "Jan 28, 2026 7:58 PM"
        "%b %d, %Y %H:%M",        # "Jan 28, 2026 19:58"
        "%B %d, %Y %I:%M %p",     # "January 28, 2026 7:58 PM"
        "%b %d %Y %I:%M %p",      # "Jan 28 2026 7:58 PM" (no comma)
        "%m/%d/%Y %I:%M %p",      # "01/28/2026 7:58 PM"
        "%Y-%m-%d %H:%M",         # "2026-01-28 19:58"
        "%b %d, %Y %I:%M:%S %p",  # with seconds
        "%b %d, %Y",              # date only
    ]

    time_str = time_str.strip()
    for fmt in formats:
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue

    return None


def match_receipt_to_history(
    receipt: ReceiptData,
    history: list[HistoryTransaction],
    time_tolerance_minutes: int = 10,
) -> MatchResult:
    """
    Match a single receipt against the transaction history.
    
    Matching priority:
    1. Ref number exact match → check amount
    2. Amount + time match (within tolerance) → likely match
    3. Amount-only match → possible match
    """
    r_ref = _normalize_ref(receipt.transaction_id)
    r_amount = _normalize_amount(receipt.amount)
    r_time = _parse_time(receipt.time)

    # ---- Strategy 1: Match by reference number ----
    if r_ref:
        for txn in history:
            h_ref = _normalize_ref(txn.ref_number)
            if h_ref and h_ref == r_ref:
                # Ref matched — check amount
                h_amount = _normalize_amount(txn.amount)
                if r_amount and h_amount and abs(r_amount - h_amount) < 0.01:
                    return MatchResult(
                        verdict="matched",
                        receipt_ref=receipt.transaction_id,
                        receipt_amount=receipt.amount,
                        receipt_time=receipt.time,
                        history_ref=txn.ref_number,
                        history_amount=txn.amount,
                        history_time=txn.date_time,
                        details="Reference number and amount match.",
                    )
                else:
                    return MatchResult(
                        verdict="mismatch",
                        receipt_ref=receipt.transaction_id,
                        receipt_amount=receipt.amount,
                        receipt_time=receipt.time,
                        history_ref=txn.ref_number,
                        history_amount=txn.amount,
                        history_time=txn.date_time,
                        details=f"Reference number matches but amount differs: "
                                f"receipt={receipt.amount}, history={txn.amount}",
                    )

    # ---- Strategy 2: Match by amount + time ----
    if r_amount and r_time:
        tolerance = timedelta(minutes=time_tolerance_minutes)
        for txn in history:
            h_amount = _normalize_amount(txn.amount)
            h_time = _parse_time(txn.date_time)
            if h_amount and abs(r_amount - h_amount) < 0.01:
                if h_time and abs(r_time - h_time) <= tolerance:
                    return MatchResult(
                        verdict="matched",
                        receipt_ref=receipt.transaction_id,
                        receipt_amount=receipt.amount,
                        receipt_time=receipt.time,
                        history_ref=txn.ref_number,
                        history_amount=txn.amount,
                        history_time=txn.date_time,
                        details=f"Amount and time match (within {time_tolerance_minutes} min).",
                    )

    # ---- Strategy 3: Amount-only match ----
    if r_amount:
        amount_matches = []
        for txn in history:
            h_amount = _normalize_amount(txn.amount)
            if h_amount and abs(r_amount - h_amount) < 0.01:
                amount_matches.append(txn)

        if len(amount_matches) == 1:
            txn = amount_matches[0]
            return MatchResult(
                verdict="matched",
                receipt_ref=receipt.transaction_id,
                receipt_amount=receipt.amount,
                receipt_time=receipt.time,
                history_ref=txn.ref_number,
                history_amount=txn.amount,
                history_time=txn.date_time,
                details="Amount matches (unique match). Time/ref could not be verified.",
            )
        elif len(amount_matches) > 1:
            return MatchResult(
                verdict="mismatch",
                receipt_ref=receipt.transaction_id,
                receipt_amount=receipt.amount,
                receipt_time=receipt.time,
                details=f"Amount {receipt.amount} found {len(amount_matches)} times in history. "
                        f"Cannot determine unique match without ref number.",
            )

    # ---- No match found ----
    return MatchResult(
        verdict="not_found",
        receipt_ref=receipt.transaction_id,
        receipt_amount=receipt.amount,
        receipt_time=receipt.time,
        details="No matching transaction found in history.",
    )


def verify_receipts(
    receipts: list[tuple[str, ReceiptData]],  # (filename, parsed receipt)
    history: list[HistoryTransaction],
    time_tolerance_minutes: int = 10,
) -> list[MatchResult]:
    """
    Match a list of receipts against transaction history.
    Returns a MatchResult for each receipt.
    """
    results: list[MatchResult] = []
    for filename, receipt in receipts:
        result = match_receipt_to_history(receipt, history, time_tolerance_minutes)
        result.receipt_filename = filename
        results.append(result)
    return results
