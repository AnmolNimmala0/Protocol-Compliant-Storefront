from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
import hmac
import hashlib
from datetime import datetime

from database import SessionLocal

from models import (
    Mandate,
    Product,
    AuditLog,
    RazorpayTransaction
)

from mandate import (
    create_mandate,
    validate_mandate,
    log_audit_event
)

from razorpay_service import (
    create_razorpay_order,
    RAZORPAY_KEY_ID
)

from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# ENVIRONMENT
# ---------------------------------------------------------

load_dotenv()

RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")

if RAZORPAY_WEBHOOK_SECRET is None:
    raise ValueError(
        "RAZORPAY_WEBHOOK_SECRET is not set in .env"
    )


# ---------------------------------------------------------
# DATABASE DEPENDENCY
# ---------------------------------------------------------

def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok"
    }


# ---------------------------------------------------------
# PRODUCT ENDPOINTS
# ---------------------------------------------------------

@app.get("/products")
def get_products(
    db: Session = Depends(get_db)
):
    products = db.query(Product).all()

    return products


@app.get("/products/{product_id}")
def get_product(
    product_id: int,
    db: Session = Depends(get_db)
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    return product


@app.get("/products/{product_id}/availability")
def check_availability(
    product_id: int,
    qty: int,
    db: Session = Depends(get_db)
):
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )

    if product is None:
        return {
            "available": False,
            "reason": "Product not found"
        }

    if product.stock >= qty:
        return {
            "available": True,
            "product_id": product.id,
            "requested_qty": qty,
            "stock": product.stock
        }

    return {
        "available": False,
        "product_id": product.id,
        "requested_qty": qty,
        "stock": product.stock,
        "reason": "Insufficient stock"
    }


# ---------------------------------------------------------
# MERCHANT TERMS
# ---------------------------------------------------------

@app.get("/terms")
def get_terms():
    return {
        "currency": "INR",
        "max_discount_pct": 10,
        "mandate_expiry_minutes": 30
    }


# ---------------------------------------------------------
# RAZORPAY ORDER CREATION
# ---------------------------------------------------------

def create_order_for_mandate(mandate):
    """
    Create a Razorpay order for an existing validated mandate
    and save the transaction in PostgreSQL.
    """

    # 1. Create Razorpay order
    order = create_razorpay_order(
        amount=mandate.agreed_price,
        mandate_id=mandate.mandate_id
    )

    print("✅ Razorpay order created!")
    print("Razorpay Order ID:", order["id"])


    # 2. Save Razorpay transaction
    db = SessionLocal()

    try:

        transaction = RazorpayTransaction(
            mandate_id=mandate.mandate_id,
            razorpay_order_id=order["id"],
            status="created",
            created_at=datetime.utcnow()
        )

        db.add(transaction)

        db.commit()

        db.refresh(transaction)

        print("✅ Razorpay transaction saved!")
        print("Transaction ID:", transaction.id)

    except Exception:

        db.rollback()

        raise

    finally:

        db.close()


    # 3. Return order information
    return {
        "key_id": RAZORPAY_KEY_ID,
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
        "mandate_id": str(mandate.mandate_id)
    }


# ---------------------------------------------------------
# CREATE RAZORPAY ORDER FOR EXISTING MANDATE
# ---------------------------------------------------------

@app.post("/create-order-for-mandate/{mandate_id}")
def create_order_for_mandate_endpoint(
    mandate_id: str
):

    # 1. Find mandate
    db = SessionLocal()

    try:

        mandate = (
            db.query(Mandate)
            .filter(Mandate.mandate_id == mandate_id)
            .first()
        )

        if mandate is None:
            raise HTTPException(
                status_code=404,
                detail="Mandate not found"
            )

    finally:

        db.close()


    # 2. Validate mandate again
    #
    # This is important because the mandate may have
    # expired or become invalid since it was created.

    is_valid, reason = validate_mandate(
        mandate.mandate_id
    )

    if not is_valid:

        raise HTTPException(
            status_code=400,
            detail=f"Mandate validation failed: {reason}"
        )


    print(
        "✅ Mandate validated before Razorpay order creation!"
    )


    # 3. Create Razorpay order
    return create_order_for_mandate(mandate)


# ---------------------------------------------------------
# RAZORPAY WEBHOOK
# ---------------------------------------------------------
@app.get("/mandates/{mandate_id}/order")
def get_mandate_order(mandate_id: str):

    db = SessionLocal()

    try:

        # Find the mandate
        mandate = (
            db.query(Mandate)
            .filter(Mandate.mandate_id == mandate_id)
            .first()
        )

        if mandate is None:
            raise HTTPException(
                status_code=404,
                detail="Mandate not found"
            )

        # Find the Razorpay transaction associated
        # with this mandate
        transaction = (
            db.query(RazorpayTransaction)
            .filter(
                RazorpayTransaction.mandate_id
                == mandate.mandate_id
            )
            .first()
        )

        if transaction is None:
            raise HTTPException(
                status_code=404,
                detail="Razorpay order not found for this mandate"
            )

        return {
            "key_id": RAZORPAY_KEY_ID,
            "order_id": transaction.razorpay_order_id,
            "currency": "INR",
            "mandate_id": str(mandate.mandate_id),
            "mandate_status": mandate.status
        }

    finally:

        db.close()


@app.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request
):

    # 1. Get raw body
    body = await request.body()


    # 2. Get Razorpay signature
    received_signature = request.headers.get(
        "X-Razorpay-Signature"
    )

    if received_signature is None:

        raise HTTPException(
            status_code=400,
            detail="Missing Razorpay signature"
        )


    # 3. Calculate expected signature
    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()


    # 4. Verify signature
    if not hmac.compare_digest(
        expected_signature,
        received_signature
    ):

        print(
            "❌ INVALID RAZORPAY WEBHOOK SIGNATURE"
        )

        print(
            "Received:",
            received_signature
        )

        print(
            "Expected:",
            expected_signature
        )

        raise HTTPException(
            status_code=400,
            detail="Invalid webhook signature"
        )


    print("✅ Webhook signature verified!")


    # 5. Parse JSON
    payload = await request.json()

    event = payload.get("event")

    print(
        "Webhook event:",
        event
    )


    # -----------------------------------------------------
    # PAYMENT CAPTURED
    # -----------------------------------------------------

    if event == "payment.captured":

        payment = (
            payload["payload"]
            ["payment"]
            ["entity"]
        )

        razorpay_payment_id = payment["id"]

        razorpay_order_id = payment["order_id"]

        print("💰 Payment captured!")

        print(
            "Payment ID:",
            razorpay_payment_id
        )

        print(
            "Order ID:",
            razorpay_order_id
        )


        db = SessionLocal()

        try:

            # 6. Find transaction
            transaction = (
                db.query(RazorpayTransaction)
                .filter(
                    RazorpayTransaction.razorpay_order_id
                    == razorpay_order_id
                )
                .first()
            )


            if transaction is None:

                raise HTTPException(
                    status_code=404,
                    detail="Razorpay transaction not found"
                )


            # 7. Prevent duplicate processing
            if transaction.status == "captured":

                print(
                    "ℹ️ Payment already processed"
                )

                return {
                    "status": "already_processed"
                }


            # 8. Update Razorpay transaction
            transaction.razorpay_payment_id = (
                razorpay_payment_id
            )

            transaction.status = "captured"


            # 9. Find associated mandate
            mandate = (
                db.query(Mandate)
                .filter(
                    Mandate.mandate_id
                    == transaction.mandate_id
                )
                .first()
            )


            if mandate is None:

                raise HTTPException(
                    status_code=404,
                    detail="Mandate not found"
                )


            # 10. Execute mandate
            mandate.status = "executed"


            # 11. Log successful payment
            log_audit_event(
                db,
                mandate.mandate_id,
                "payment_captured",
                {
                    "razorpay_payment_id":
                        razorpay_payment_id,

                    "razorpay_order_id":
                        razorpay_order_id,

                    "amount":
                        payment.get("amount"),

                    "currency":
                        payment.get("currency")
                }
            )


            # 12. Commit
            db.commit()


            print(
                "✅ Mandate marked as executed!"
            )

            print(
                "📝 Payment captured event logged!"
            )


        except Exception:

            db.rollback()

            raise

        finally:

            db.close()


    # -----------------------------------------------------
    # PAYMENT FAILED
    # -----------------------------------------------------

    elif event == "payment.failed":

        payment = (
            payload["payload"]
            ["payment"]
            ["entity"]
        )

        razorpay_payment_id = payment["id"]

        razorpay_order_id = payment["order_id"]


        print("❌ Payment failed!")

        print(
            "Payment ID:",
            razorpay_payment_id
        )

        print(
            "Order ID:",
            razorpay_order_id
        )


        db = SessionLocal()

        try:

            # Find transaction
            transaction = (
                db.query(RazorpayTransaction)
                .filter(
                    RazorpayTransaction.razorpay_order_id
                    == razorpay_order_id
                )
                .first()
            )


            if transaction is None:

                raise HTTPException(
                    status_code=404,
                    detail="Razorpay transaction not found"
                )


            # Update transaction
            transaction.razorpay_payment_id = (
                razorpay_payment_id
            )

            transaction.status = "failed"


            # Find associated mandate
            mandate = (
                db.query(Mandate)
                .filter(
                    Mandate.mandate_id
                    == transaction.mandate_id
                )
                .first()
            )


            if mandate is None:

                raise HTTPException(
                    status_code=404,
                    detail="Mandate not found"
                )


            # Decline mandate
            mandate.status = "declined"


            # Log failed payment
            log_audit_event(
                db,
                mandate.mandate_id,
                "payment_failed",
                {
                    "razorpay_payment_id":
                        razorpay_payment_id,

                    "razorpay_order_id":
                        razorpay_order_id,

                    "reason":
                        payment.get(
                            "error_description"
                        )
                }
            )


            db.commit()


            print(
                "❌ Mandate marked as declined!"
            )

            print(
                "📝 Payment failure logged!"
            )


        except Exception:

            db.rollback()

            raise

        finally:

            db.close()


    return {
        "status": "received"
    }


# ---------------------------------------------------------
# LEGACY TEST ENDPOINT
# ---------------------------------------------------------

@app.post("/create-test-order")
def create_test_order():

    # 1. Create a test mandate
    mandate = create_mandate(
        buyer_id="test-buyer",
        product_id=3,
        quantity=1,
        agreed_price=850000
    )

    print("✅ Test mandate created!")

    print(
        "Mandate ID:",
        mandate.mandate_id
    )


    # 2. Validate mandate
    is_valid, reason = validate_mandate(
        mandate.mandate_id
    )

    if not is_valid:

        raise HTTPException(
            status_code=400,
            detail=f"Mandate validation failed: {reason}"
        )


    print(
        "✅ Test mandate validated!"
    )


    # 3. Create Razorpay order
    return create_order_for_mandate(mandate)