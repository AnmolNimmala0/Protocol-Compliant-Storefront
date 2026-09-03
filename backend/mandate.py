from dotenv import load_dotenv
import os
import hmac
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from database import SessionLocal
from models import Mandate, Product, AuditLog


load_dotenv()

HMAC_SECRET = os.getenv("HMAC_SECRET")

if HMAC_SECRET is None:
    raise ValueError("HMAC_SECRET is not set in .env")


# =========================================================
# HMAC SIGNATURE
# =========================================================

def generate_signature(
    buyer_id,
    product_id,
    quantity,
    agreed_price
):
    """
    Generate a tamper-evident HMAC signature for a mandate.

    The signature binds together:
        buyer_id
        product_id
        quantity
        agreed_price
    """

    message = (
        f"{buyer_id}|"
        f"{product_id}|"
        f"{quantity}|"
        f"{agreed_price}"
    )

    signature = hmac.new(
        HMAC_SECRET.encode(),
        message.encode(),
        digestmod=hashlib.sha256
    ).hexdigest()

    return signature


# =========================================================
# CREATE MANDATE
# =========================================================

def create_mandate(
    buyer_id,
    product_id,
    quantity,
    agreed_price
):
    """
    Create a pending financial mandate.

    The mandate is signed using HMAC and expires after
    five minutes.
    """

    db = SessionLocal()

    try:
        mandate_id = uuid.uuid4()

        created_at = datetime.now(timezone.utc)

        expires_at = (
            created_at +
            timedelta(minutes=5)
        )

        signature = generate_signature(
            buyer_id,
            product_id,
            quantity,
            agreed_price
        )

        mandate = Mandate(
            mandate_id=mandate_id,
            buyer_agent_id=buyer_id,
            product_id=product_id,
            quantity=quantity,
            agreed_price=agreed_price,
            signature=signature,
            status="pending",
            created_at=created_at,
            expires_at=expires_at
        )

        db.add(mandate)
        db.commit()
        db.refresh(mandate)

        return mandate

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


# =========================================================
# AUDIT LOG
# =========================================================

def log_audit_event(
    db,
    mandate_id,
    event_type,
    detail,
    session_id=None
):
    """
    Record an event in the audit trail.

    session_id:
        Identifies the complete Buyer Agent execution.

    mandate_id:
        Identifies the financial mandate once one exists.

    Both are optional because some events occur before
    mandate creation.
    """

    audit = AuditLog(
        session_id=session_id,
        mandate_id=mandate_id,
        event_type=event_type,
        detail=detail,
        created_at=datetime.now(timezone.utc)
    )

    db.add(audit)
    db.commit()


# =========================================================
# VALIDATE MANDATE
# =========================================================

def validate_mandate(mandate_id):
    """
    Validate a mandate immediately before financial execution.

    Checks:

    1. Mandate exists
    2. HMAC signature is valid
    3. Mandate has not expired
    4. Mandate has not already been used
    5. Product still exists
    6. Live stock is sufficient
    7. Agreed price respects merchant discount policy
    """

    db = SessionLocal()

    try:

        # -----------------------------------------------------
        # 1. FIND MANDATE
        # -----------------------------------------------------

        mandate = (
            db.query(Mandate)
            .filter(
                Mandate.mandate_id == mandate_id
            )
            .first()
        )

        if mandate is None:
            return False, "Mandate not found"

        # -----------------------------------------------------
        # 2. VERIFY SIGNATURE
        # -----------------------------------------------------

        expected_signature = generate_signature(
            mandate.buyer_agent_id,
            mandate.product_id,
            mandate.quantity,
            mandate.agreed_price
        )

        if mandate.signature is None:

            mandate.status = "declined"
            db.commit()

            log_audit_event(
                db,
                mandate.mandate_id,
                "validation_failed",
                {
                    "reason": "Mandate has no signature"
                }
            )

            return False, "Mandate has no signature"

        if not hmac.compare_digest(
            expected_signature,
            str(mandate.signature)
        ):

            mandate.status = "declined"
            db.commit()

            log_audit_event(
                db,
                mandate.mandate_id,
                "validation_failed",
                {
                    "reason": "Invalid mandate signature"
                }
            )

            return False, "Invalid mandate signature"

        # -----------------------------------------------------
        # 3. CHECK EXPIRY
        # -----------------------------------------------------

        now = datetime.now(timezone.utc)

        if mandate.expires_at is None:
            mandate.status = "declined"
            db.commit()

            log_audit_event(
                db,
                mandate.mandate_id,
                "validation_failed",
                {
                    "reason": "Mandate has no expiry time"
                }
            )

            return False, "Mandate has no expiry time"

        expires_at = (
            mandate.expires_at.replace(
                tzinfo=timezone.utc
            )
            if mandate.expires_at.tzinfo is None
            else mandate.expires_at
        )

        if now >= expires_at:

            mandate.status = "declined"
            db.commit()

            log_audit_event(
                db,
                mandate.mandate_id,
                "validation_failed",
                {
                    "reason": "Mandate has expired"
                }
            )

            return False, "Mandate has expired"

        # -----------------------------------------------------
        # 4. REPLAY CHECK
        # -----------------------------------------------------

        if mandate.status != "pending":

            previous_status = mandate.status

            mandate.status = "declined"
            db.commit()

            log_audit_event(
                db,
                mandate.mandate_id,
                "validation_failed",
                {
                    "reason": "Mandate cannot be reused",
                    "status": previous_status
                }
            )

            return False, (
                f"Mandate cannot be used: "
                f"status is {previous_status}"
            )

        # -----------------------------------------------------
        # 5. GET CURRENT PRODUCT
        # -----------------------------------------------------

        product = (
            db.query(Product)
            .filter(
                Product.id == mandate.product_id
            )
            .first()
        )

        if product is None:

            mandate.status = "declined"
            db.commit()

            log_audit_event(
                db,
                mandate.mandate_id,
                "validation_failed",
                {
                    "reason": "Product no longer exists"
                }
            )

            return False, "Product no longer exists"

        # -----------------------------------------------------
        # 6. CHECK LIVE STOCK
        # -----------------------------------------------------

        if product.stock < mandate.quantity:

            mandate.status = "declined"
            db.commit()

            log_audit_event(
                db,
                mandate.mandate_id,
                "validation_failed",
                {
                    "reason": "Insufficient stock",
                    "requested": mandate.quantity,
                    "available": product.stock
                }
            )

            return False, "Insufficient stock"

        # -----------------------------------------------------
        # 7. CHECK MERCHANT DISCOUNT POLICY
        # -----------------------------------------------------

        max_discount = (
            product.max_discount_pct or 0
        )

        minimum_price = (
            product.price *
            (100 - max_discount) //
            100
        )

        if mandate.agreed_price < minimum_price:

            mandate.status = "declined"
            db.commit()

            log_audit_event(
                db,
                mandate.mandate_id,
                "validation_failed",
                {
                    "reason": (
                        "Agreed price exceeds "
                        "merchant discount policy"
                    ),
                    "agreed_price": mandate.agreed_price,
                    "minimum_price": minimum_price
                }
            )

            return False, (
                "Agreed price exceeds "
                "merchant discount policy"
            )

        # -----------------------------------------------------
        # ALL CHECKS PASSED
        # -----------------------------------------------------

        return True, None

    finally:
        db.close()