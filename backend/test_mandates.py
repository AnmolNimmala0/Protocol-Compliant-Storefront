from datetime import datetime, timedelta, timezone

from database import SessionLocal
from models import Mandate, Product
from mandate import create_mandate, validate_mandate


def test_valid_mandate():
    mandate = create_mandate(
        buyer_id="test-buyer",
        product_id=3,
        quantity=2,
        agreed_price=850000
    )

    valid, reason = validate_mandate(
        mandate.mandate_id
    )

    assert valid is True
    assert reason is None

    print("✅ VALID MANDATE: PASS")


def test_tampered_signature():
    mandate = create_mandate(
        buyer_id="test-buyer",
        product_id=3,
        quantity=2,
        agreed_price=850000
    )

    db = SessionLocal()

    try:
        stored_mandate = db.query(Mandate).filter(
            Mandate.mandate_id == mandate.mandate_id
        ).first()

        stored_mandate.agreed_price = 700000

        db.commit()

    finally:
        db.close()

    valid, reason = validate_mandate(
        mandate.mandate_id
    )

    assert valid is False
    assert reason == "Invalid mandate signature"

    print("✅ TAMPERED SIGNATURE: PASS")


def test_expired_mandate():
    mandate = create_mandate(
        buyer_id="test-buyer",
        product_id=3,
        quantity=2,
        agreed_price=850000
    )

    db = SessionLocal()

    try:
        stored_mandate = db.query(Mandate).filter(
            Mandate.mandate_id == mandate.mandate_id
        ).first()

        stored_mandate.expires_at = (
            datetime.now(timezone.utc)
            - timedelta(minutes=1)
        )

        db.commit()

    finally:
        db.close()

    valid, reason = validate_mandate(
        mandate.mandate_id
    )

    assert valid is False
    assert reason == "Mandate has expired"

    print("✅ EXPIRED MANDATE: PASS")


def test_replayed_mandate():
    mandate = create_mandate(
        buyer_id="test-buyer",
        product_id=3,
        quantity=2,
        agreed_price=850000
    )

    db = SessionLocal()

    try:
        stored_mandate = db.query(Mandate).filter(
            Mandate.mandate_id == mandate.mandate_id
        ).first()

        stored_mandate.status = "executed"

        db.commit()

    finally:
        db.close()

    valid, reason = validate_mandate(
        mandate.mandate_id
    )

    assert valid is False
    assert reason == "Mandate cannot be used: status is executed"

    print("✅ REPLAYED MANDATE: PASS")


def test_insufficient_stock():
    mandate = create_mandate(
        buyer_id="test-buyer",
        product_id=3,
        quantity=5,
        agreed_price=850000
    )

    db = SessionLocal()

    try:
        product = db.query(Product).filter(
            Product.id == 3
        ).first()

        original_stock = product.stock

        product.stock = 2

        db.commit()

    finally:
        db.close()

    valid, reason = validate_mandate(
        mandate.mandate_id
    )

    assert valid is False
    assert reason == "Insufficient stock"

    # Restore original stock
    db = SessionLocal()

    try:
        product = db.query(Product).filter(
            Product.id == 3
        ).first()

        product.stock = original_stock

        db.commit()

    finally:
        db.close()

    print("✅ INSUFFICIENT STOCK: PASS")


if __name__ == "__main__":
    test_valid_mandate()
    test_tampered_signature()
    test_expired_mandate()
    test_replayed_mandate()
    test_insufficient_stock()

    print("\n🎉 ALL MANDATE TESTS PASSED!")