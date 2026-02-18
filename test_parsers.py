"""
Unit tests for receipt parsers.
Tests regex patterns against real OCR output formats from GCash receipts.
"""

from parsers import parse_receipt, detect_provider, ReceiptData


def test_gcash_standard_receipt():
    """Standard GCash Express Send receipt."""
    lines = [
        "Express Send",
        "AN---W KY-E T.",
        "+63 977 732 9406",
        "Sent via GCash",
        "Amount",
        "320.00",
        "Total Amount Sent",
        "P320.00",
        "Ref No. 7037516197197",
        "Feb 5, 2026 7:23 PM",
    ]
    result = parse_receipt(lines)
    assert result.provider == "gcash"
    assert result.transaction_id == "7037516197197"
    assert result.amount == "320.00"
    assert result.time == "Feb 5, 2026 7:23 PM"


def test_gcash_spaced_ref():
    """GCash receipt where ref number has spaces."""
    lines = [
        "Sent via GCash",
        "Amount 540.00",
        "Total Amount Sent P540.00",
        "Ref No. 7037 651 006674",
        "Feb 09, 2026 9:16 PM",
    ]
    result = parse_receipt(lines)
    assert result.provider == "gcash"
    assert result.transaction_id == "7037651006674"
    assert result.amount == "540.00"
    assert result.time == "Feb 09, 2026 9:16 PM"


def test_gcash_another_format():
    """Another common GCash receipt format."""
    lines = [
        "Express Send",
        "AN---W KY-E T.",
        "+63 9.. ... 9406",
        "Sent via GCash",
        "Amount",
        "420.00",
        "Total Amount Sent",
        "P420.00",
        "Ref No. 7037247387681",
        "Jan 28, 2026 7:58 PM",
    ]
    result = parse_receipt(lines)
    assert result.provider == "gcash"
    assert result.transaction_id == "7037247387681"
    assert result.amount == "420.00"
    assert result.time == "Jan 28, 2026 7:58 PM"


def test_gcash_ref_with_spaces_2037():
    """GCash ref starting with 2037 and spaces."""
    lines = [
        "Sent via GCash",
        "Amount 420.00",
        "Total Amount Sent P420.00",
        "Ref No. 2037 306 741072",
        "Jan 30, 2026 5:32 PM",
    ]
    result = parse_receipt(lines)
    assert result.transaction_id == "2037306741072"
    assert result.amount == "420.00"


def test_detect_gcash_provider():
    lines = ["Express Send", "Sent via GCash", "Amount 100.00"]
    assert detect_provider(lines) == "gcash"


def test_detect_paymaya_provider():
    lines = ["Maya", "Transaction Successful", "Amount 200.00"]
    assert detect_provider(lines) == "paymaya"


def test_detect_unknown_provider():
    lines = ["Some random text", "No payment provider here"]
    assert detect_provider(lines) is None


def test_no_useful_text():
    """Non-receipt image that produces random OCR text."""
    lines = ["cats", "funny", "meme"]
    result = parse_receipt(lines)
    assert result.provider is None
    assert result.transaction_id is None
    assert result.amount is None


def test_gcash_amount_on_same_line():
    """Amount and value on the same OCR line."""
    lines = [
        "Sent via GCash",
        "Amount 120.00",
        "Total Amount Sent P120.00",
        "Ref No. 6037260329062",
        "Jan 29, 2026 10:19 AM",
    ]
    result = parse_receipt(lines)
    assert result.amount == "120.00"
    assert result.time == "Jan 29, 2026 10:19 AM"


def test_bdo_pay_receipt():
    """BDO Pay receipt with alphanumeric ref and headline PHP amount."""
    lines = [
        "Sent!",
        "PHP 330.00",
        "Jan 28, 2026 05:26 AM",
        "Send Money Amount PHP 320.00",
        "Service Fee PHP 10.00",
        "To Andrew Tan",
        "G-Xchange, Inc. / Gcash",
        "09777329406",
        "From SMART CHECKING-INDVL (W/PSBK)",
        "5676",
        "Invoice number 012791",
        "Reference no.",
        "BN-20260128-49830535",
        "Thank you for using",
        "BDO pay",
    ]
    result = parse_receipt(lines)
    assert result.provider == "bdo"
    assert result.transaction_id == "BN-20260128-49830535"
    assert result.amount == "330.00"
    assert result.time == "Jan 28, 2026 05:26 AM"


def test_detect_bdo_provider():
    lines = ["Sent!", "PHP 330.00", "Thank you for using BDO pay"]
    assert detect_provider(lines) == "bdo"


def test_bdo_ref_alphanumeric():
    """BDO reference with dashes should be captured."""
    lines = [
        "Reference no.",
        "BN-20260128-49830535",
        "Thank you for using BDO pay",
    ]
    result = parse_receipt(lines)
    assert result.transaction_id == "BN-20260128-49830535"


if __name__ == "__main__":
    import sys
    # Run all test functions
    test_funcs = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    failed = 0
    for fn in test_funcs:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
