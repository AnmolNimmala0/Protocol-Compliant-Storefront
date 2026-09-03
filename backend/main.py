from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Request,
    BackgroundTasks,
)

from pydantic import BaseModel
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from fastapi.middleware.cors import CORSMiddleware

from datetime import datetime, timezone

import os
import hmac
import hashlib
import uuid

from database import SessionLocal

from models import (
    Mandate,
    Product,
    AuditLog,
    RazorpayTransaction,
    Order,
)

from mandate import (
    create_mandate,
    validate_mandate,
    log_audit_event,
)

from razorpay_service import (
    create_razorpay_order,
    RAZORPAY_KEY_ID,
)

from agent_session import (
    create_session,
    update_session,
    get_session,
)


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


RAZORPAY_WEBHOOK_SECRET = os.getenv(
    "RAZORPAY_WEBHOOK_SECRET"
)

if RAZORPAY_WEBHOOK_SECRET is None:
    raise ValueError(
        "RAZORPAY_WEBHOOK_SECRET is not set in .env"
    )


# =========================================================
# FITSTORE IDENTITY
# =========================================================

MERCHANT_NAME = "FitStore"
MERCHANT_ID = "fitstore-demo"

DEFAULT_BUYER_ID = "buyer-agent-demo"


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="FitStore Agentic Commerce API",
    description=(
        "MCP-enabled ecommerce backend with "
        "Buyer Agent, Merchant Agent, mandates, "
        "guardrails and Razorpay."
    ),
    version="1.0.0",
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# DATABASE DEPENDENCY
# =========================================================

def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "merchant": MERCHANT_NAME,
    }


# =========================================================
# AGENT SESSION
# =========================================================

class ShoppingRequest(BaseModel):
    shopping_brief: str


def run_agent_background(
    shopping_brief: str,
    session_id: str,
):
    """
    Run the Buyer Agent in the background.

    The frontend receives the session ID immediately
    while the Buyer Agent continues executing.
    """

    try:

        from buyer_agent import run_buyer_agent

        mandate_id = run_buyer_agent(
            shopping_brief=shopping_brief,
            session_id=session_id,
        )

        update_session(
            session_id=session_id,
            status="awaiting_payment",
            mandate_id=(
                str(mandate_id)
                if mandate_id
                else None
            ),
        )

    except Exception as e:

        print(
            f"❌ Agent session {session_id} failed:"
        )

        print(str(e))

        update_session(
            session_id=session_id,
            status="failed",
        )


# =========================================================
# START AGENT SHOPPING SESSION
# =========================================================

@app.post("/agent/shop")
def start_agent_shop(
    request: ShoppingRequest,
    background_tasks: BackgroundTasks,
):

    if not request.shopping_brief.strip():

        raise HTTPException(
            status_code=400,
            detail="shopping_brief cannot be empty",
        )

    session_id = create_session()

    background_tasks.add_task(
        run_agent_background,
        request.shopping_brief,
        session_id,
    )

    return {
        "session_id": session_id,
        "status": "running",
    }


# =========================================================
# GET AGENT SESSION STATUS
# =========================================================

@app.get("/agent/sessions/{session_id}")
def get_agent_session(
    session_id: str,
):

    session = get_session(session_id)

    if session is None:

        raise HTTPException(
            status_code=404,
            detail="Agent session not found",
        )

    return session


# =========================================================
# GET AGENT EXECUTION EVENTS
# =========================================================

@app.get("/agent/sessions/{session_id}/events")
def get_agent_events(
    session_id: str,
    db: Session = Depends(get_db),
):

    session = get_session(session_id)

    if session is None:

        raise HTTPException(
            status_code=404,
            detail="Agent session not found",
        )

    events = (
        db.query(AuditLog)
        .filter(
            AuditLog.session_id == session_id
        )
        .order_by(
            AuditLog.id.asc()
        )
        .all()
    )

    return [
        {
            "id": event.id,

            "session_id": event.session_id,

            "mandate_id": (
                str(event.mandate_id)
                if event.mandate_id
                else None
            ),

            "event_type": event.event_type,

            "detail": event.detail,

            "created_at": (
                event.created_at.isoformat()
                if event.created_at
                else None
            ),
        }

        for event in events
    ]


# =========================================================
# PRODUCT ENDPOINTS
# =========================================================

@app.get("/products")
def get_products(
    db: Session = Depends(get_db),
):

    products = (
        db.query(Product)
        .order_by(Product.id.asc())
        .all()
    )

    return products


@app.get("/products/{product_id}")
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
):

    product = (
        db.query(Product)
        .filter(
            Product.id == product_id
        )
        .first()
    )

    if product is None:

        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    return product


@app.get("/products/{product_id}/availability")
def check_availability(
    product_id: int,
    qty: int,
    db: Session = Depends(get_db),
):

    if qty <= 0:

        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero",
        )

    product = (
        db.query(Product)
        .filter(
            Product.id == product_id
        )
        .first()
    )

    if product is None:

        return {
            "available": False,
            "reason": "Product not found",
        }

    if product.stock >= qty:

        return {
            "available": True,
            "product_id": product.id,
            "product_name": product.name,
            "requested_qty": qty,
            "stock": product.stock,
        }

    return {
        "available": False,
        "product_id": product.id,
        "product_name": product.name,
        "requested_qty": qty,
        "stock": product.stock,
        "reason": "Insufficient stock",
    }


# =========================================================
# MERCHANT INFORMATION
# =========================================================

@app.get("/merchant")
def get_merchant():

    return {
        "merchant_id": MERCHANT_ID,
        "name": MERCHANT_NAME,
        "description": (
            "MCP-enabled fitness ecommerce store"
        ),
        "currency": "INR",
        "agent_enabled": True,
        "mcp_enabled": True,
    }


# =========================================================
# MERCHANT TERMS
# =========================================================

@app.get("/terms")
def get_terms():

    return {
        "merchant_id": MERCHANT_ID,
        "merchant_name": MERCHANT_NAME,
        "currency": "INR",
        "max_discount_pct": 10,
        "mandate_expiry_minutes": 30,
    }


# =========================================================
# MANDATE DETAILS
# =========================================================

@app.get("/mandates/{mandate_id}")
def get_mandate(
    mandate_id: str,
    db: Session = Depends(get_db),
):

    mandate = (
        db.query(Mandate)
        .filter(
            Mandate.mandate_id == mandate_id
        )
        .first()
    )

    if mandate is None:

        raise HTTPException(
            status_code=404,
            detail="Mandate not found",
        )

    return {
        "mandate_id": str(
            mandate.mandate_id
        ),

        "buyer_agent_id":
            mandate.buyer_agent_id,

        "merchant_id":
            mandate.merchant_id,

        "product_id":
            mandate.product_id,

        "quantity":
            mandate.quantity,

        "agreed_price":
            mandate.agreed_price,

        "currency":
            mandate.currency,

        "status":
            mandate.status,

        "signature":
            mandate.signature,

        "created_at": (
            mandate.created_at.isoformat()
            if mandate.created_at
            else None
        ),

        "expires_at": (
            mandate.expires_at.isoformat()
            if mandate.expires_at
            else None
        ),
    }


# =========================================================
# FITSTORE ORDER CREATION
# =========================================================

def create_fitstore_order(
    db,
    mandate,
    transaction,
    razorpay_payment_id,
):
    """
    Convert a successfully paid mandate into
    a real FitStore order.

    This function is deterministic.

    No LLM is involved in order creation.

    A mandate represents authorization to purchase.

    An Order represents the actual completed
    commerce transaction.
    """

    # -----------------------------------------------------
    # 1. Check for an existing order
    # -----------------------------------------------------

    existing_order = (
        db.query(Order)
        .filter(
            Order.mandate_id
            == mandate.mandate_id
        )
        .first()
    )

    if existing_order is not None:

        print(
            "ℹ️ FitStore order already exists:"
        )

        print(
            existing_order.order_number
        )

        return existing_order

    # -----------------------------------------------------
    # 2. Find product
    # -----------------------------------------------------

    product = (
        db.query(Product)
        .filter(
            Product.id == mandate.product_id
        )
        .first()
    )

    if product is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Product not found while "
                "creating FitStore order"
            ),
        )

    # -----------------------------------------------------
    # 3. Verify stock
    # -----------------------------------------------------

    if product.stock < mandate.quantity:

        raise HTTPException(
            status_code=400,
            detail=(
                "Insufficient stock while "
                "creating FitStore order"
            ),
        )

    # -----------------------------------------------------
    # 4. Generate store order number
    # -----------------------------------------------------

    order_number = (
        f"FS-{uuid.uuid4().hex[:8].upper()}"
    )

    # -----------------------------------------------------
    # 5. Create order
    # -----------------------------------------------------

    order = Order(
        order_number=order_number,

        buyer_id=(
            mandate.buyer_agent_id
            or DEFAULT_BUYER_ID
        ),

        mandate_id=mandate.mandate_id,

        product_id=mandate.product_id,

        quantity=mandate.quantity,

        amount=mandate.agreed_price,

        currency=(
            mandate.currency
            or "INR"
        ),

        razorpay_order_id=(
            transaction.razorpay_order_id
        ),

        razorpay_payment_id=(
            razorpay_payment_id
        ),

        status="confirmed",

        created_at=datetime.now(
            timezone.utc
        ),
    )

    db.add(order)

    # -----------------------------------------------------
    # 6. Reduce inventory
    # -----------------------------------------------------

    product.stock -= mandate.quantity

    # -----------------------------------------------------
    # 7. Flush changes
    # -----------------------------------------------------

    db.flush()

    print(
        "🏪 FitStore order created!"
    )

    print(
        "Order number:",
        order.order_number,
    )

    print(
        "Product:",
        product.name,
    )

    print(
        "Quantity:",
        order.quantity,
    )

    print(
        "Amount:",
        order.amount,
    )

    print(
        "Remaining stock:",
        product.stock,
    )

    return order


# =========================================================
# ORDER ENDPOINTS
# =========================================================

@app.get("/orders")
def get_orders(
    buyer_id: str = DEFAULT_BUYER_ID,
    db: Session = Depends(get_db),
):

    orders = (
        db.query(Order)
        .filter(
            Order.buyer_id == buyer_id
        )
        .order_by(
            Order.id.desc()
        )
        .all()
    )

    result = []

    for order in orders:

        product = (
            db.query(Product)
            .filter(
                Product.id
                == order.product_id
            )
            .first()
        )

        result.append(
            {
                "id": order.id,

                "order_number":
                    order.order_number,

                "merchant":
                    MERCHANT_NAME,

                "merchant_id":
                    MERCHANT_ID,

                "buyer_id":
                    order.buyer_id,

                "mandate_id":
                    str(order.mandate_id),

                "product_id":
                    order.product_id,

                "product_name":
                    product.name
                    if product
                    else None,

                "quantity":
                    order.quantity,

                "amount":
                    order.amount,

                "currency":
                    order.currency,

                "razorpay_order_id":
                    order.razorpay_order_id,

                "razorpay_payment_id":
                    order.razorpay_payment_id,

                "status":
                    order.status,

                "created_at": (
                    order.created_at.isoformat()
                    if order.created_at
                    else None
                ),
            }
        )

    return result


@app.get("/orders/{order_number}")
def get_order(
    order_number: str,
    db: Session = Depends(get_db),
):

    order = (
        db.query(Order)
        .filter(
            Order.order_number
            == order_number
        )
        .first()
    )

    if order is None:

        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    product = (
        db.query(Product)
        .filter(
            Product.id
            == order.product_id
        )
        .first()
    )

    return {
        "id": order.id,

        "order_number":
            order.order_number,

        "merchant":
            MERCHANT_NAME,

        "merchant_id":
            MERCHANT_ID,

        "buyer_id":
            order.buyer_id,

        "mandate_id":
            str(order.mandate_id),

        "product_id":
            order.product_id,

        "product_name":
            product.name
            if product
            else None,

        "quantity":
            order.quantity,

        "amount":
            order.amount,

        "currency":
            order.currency,

        "razorpay_order_id":
            order.razorpay_order_id,

        "razorpay_payment_id":
            order.razorpay_payment_id,

        "status":
            order.status,

        "created_at": (
            order.created_at.isoformat()
            if order.created_at
            else None
        ),
    }


# =========================================================
# RAZORPAY ORDER CREATION
# =========================================================

def create_order_for_mandate(
    mandate,
):
    """
    Create a Razorpay order for an existing
    validated mandate and save the transaction
    in PostgreSQL.
    """

    # -----------------------------------------------------
    # 1. Create Razorpay order
    # -----------------------------------------------------

    order = create_razorpay_order(
        amount=mandate.agreed_price,
        mandate_id=mandate.mandate_id,
    )

    print(
        "✅ Razorpay order created!"
    )

    print(
        "Razorpay Order ID:",
        order["id"],
    )

    # -----------------------------------------------------
    # 2. Save Razorpay transaction
    # -----------------------------------------------------

    db = SessionLocal()

    try:

        transaction = RazorpayTransaction(
            mandate_id=mandate.mandate_id,

            razorpay_order_id=order["id"],

            status="created",

            created_at=datetime.now(
                timezone.utc
            ),
        )

        db.add(transaction)

        db.commit()

        db.refresh(transaction)

        print(
            "✅ Razorpay transaction saved!"
        )

        print(
            "Transaction ID:",
            transaction.id,
        )

    except Exception:

        db.rollback()

        raise

    finally:

        db.close()

    # -----------------------------------------------------
    # 3. Return order information
    # -----------------------------------------------------

    return {
        "key_id":
            RAZORPAY_KEY_ID,

        "order_id":
            order["id"],

        "amount":
            order["amount"],

        "currency":
            order["currency"],

        "mandate_id":
            str(mandate.mandate_id),
    }


# =========================================================
# CREATE RAZORPAY ORDER FOR EXISTING MANDATE
# =========================================================

@app.post(
    "/create-order-for-mandate/{mandate_id}"
)
def create_order_for_mandate_endpoint(
    mandate_id: str,
):

    db = SessionLocal()

    try:

        mandate = (
            db.query(Mandate)
            .filter(
                Mandate.mandate_id
                == mandate_id
            )
            .first()
        )

        if mandate is None:

            raise HTTPException(
                status_code=404,
                detail="Mandate not found",
            )

    finally:

        db.close()

    # -----------------------------------------------------
    # Validate mandate again
    # -----------------------------------------------------

    is_valid, reason = validate_mandate(
        mandate.mandate_id
    )

    if not is_valid:

        raise HTTPException(
            status_code=400,
            detail=(
                "Mandate validation failed: "
                f"{reason}"
            ),
        )

    print(
        "✅ Mandate validated before "
        "Razorpay order creation!"
    )

    # -----------------------------------------------------
    # Create Razorpay order
    # -----------------------------------------------------

    return create_order_for_mandate(
        mandate
    )


# =========================================================
# GET RAZORPAY ORDER FOR MANDATE
# =========================================================

@app.get(
    "/mandates/{mandate_id}/order"
)
def get_mandate_order(
    mandate_id: str,
):

    db = SessionLocal()

    try:

        mandate = (
            db.query(Mandate)
            .filter(
                Mandate.mandate_id
                == mandate_id
            )
            .first()
        )

        if mandate is None:

            raise HTTPException(
                status_code=404,
                detail="Mandate not found",
            )

        transaction = (
            db.query(
                RazorpayTransaction
            )
            .filter(
                RazorpayTransaction.mandate_id
                == mandate.mandate_id
            )
            .order_by(
                RazorpayTransaction.id.desc()
            )
            .first()
        )

        if transaction is None:

            raise HTTPException(
                status_code=404,
                detail=(
                    "Razorpay order not found "
                    "for this mandate"
                ),
            )

        return {
            "key_id":
                RAZORPAY_KEY_ID,

            "order_id":
                transaction.razorpay_order_id,

            "currency":
                mandate.currency
                or "INR",

            "mandate_id":
                str(mandate.mandate_id),

            "mandate_status":
                mandate.status,

            "amount":
                mandate.agreed_price,
        }

    finally:

        db.close()


# =========================================================
# RAZORPAY WEBHOOK
# =========================================================

@app.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
):

    # -----------------------------------------------------
    # 1. Read raw request body
    # -----------------------------------------------------

    body = await request.body()

    # -----------------------------------------------------
    # 2. Read Razorpay signature
    # -----------------------------------------------------

    received_signature = (
        request.headers.get(
            "X-Razorpay-Signature"
        )
    )

    if received_signature is None:

        raise HTTPException(
            status_code=400,
            detail="Missing Razorpay signature",
        )

    # -----------------------------------------------------
    # 3. Calculate expected signature
    # -----------------------------------------------------

    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    # -----------------------------------------------------
    # 4. Verify webhook authenticity
    # -----------------------------------------------------

    if not hmac.compare_digest(
        expected_signature,
        received_signature,
    ):

        print(
            "❌ INVALID RAZORPAY WEBHOOK SIGNATURE"
        )

        raise HTTPException(
            status_code=400,
            detail="Invalid webhook signature",
        )

    print(
        "✅ Webhook signature verified!"
    )

    # -----------------------------------------------------
    # 5. Parse webhook JSON
    # -----------------------------------------------------

    payload = await request.json()

    event = payload.get("event")

    print(
        "Webhook event:",
        event,
    )

    # =====================================================
    # PAYMENT CAPTURED
    # =====================================================

    if event == "payment.captured":

        payment = (
            payload["payload"]
            ["payment"]
            ["entity"]
        )

        razorpay_payment_id = payment["id"]

        razorpay_order_id = payment["order_id"]

        print(
            "💰 Payment captured!"
        )

        print(
            "Payment ID:",
            razorpay_payment_id,
        )

        print(
            "Order ID:",
            razorpay_order_id,
        )

        db = SessionLocal()

        try:

            # -------------------------------------------------
            # 1. Find Razorpay transaction
            # -------------------------------------------------

            transaction = (
                db.query(
                    RazorpayTransaction
                )
                .filter(
                    RazorpayTransaction
                    .razorpay_order_id
                    == razorpay_order_id
                )
                .first()
            )

            if transaction is None:

                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Razorpay transaction "
                        "not found"
                    ),
                )

            # -------------------------------------------------
            # 2. Prevent duplicate processing
            # -------------------------------------------------

            if transaction.status == "captured":

                print(
                    "ℹ️ Payment already processed"
                )

                return {
                    "status":
                        "already_processed"
                }

            # -------------------------------------------------
            # 3. Find mandate
            # -------------------------------------------------

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
                    detail="Mandate not found",
                )

            # -------------------------------------------------
            # 4. Find session ID
            # -------------------------------------------------

            session_id = None

            session_event = (
                db.query(AuditLog)
                .filter(
                    AuditLog.mandate_id
                    == mandate.mandate_id
                )
                .filter(
                    AuditLog.session_id.isnot(None)
                )
                .order_by(
                    AuditLog.id.desc()
                )
                .first()
            )

            if session_event is not None:

                session_id = (
                    session_event.session_id
                )

            # -------------------------------------------------
            # 5. Create FitStore order
            # -------------------------------------------------

            fitstore_order = (
                create_fitstore_order(
                    db=db,
                    mandate=mandate,
                    transaction=transaction,
                    razorpay_payment_id=(
                        razorpay_payment_id
                    ),
                )
            )

            # -------------------------------------------------
            # 6. Execute mandate
            # -------------------------------------------------

            mandate.status = "executed"

            # -------------------------------------------------
            # 7. Update Razorpay transaction
            # -------------------------------------------------

            transaction.razorpay_payment_id = (
                razorpay_payment_id
            )

            transaction.status = "captured"

            # -------------------------------------------------
            # 8. Log payment captured
            # -------------------------------------------------

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
                        payment.get("currency"),
                },
                session_id=session_id,
            )

            # -------------------------------------------------
            # 9. Log merchant order confirmation
            # -------------------------------------------------

            log_audit_event(
                db,
                mandate.mandate_id,
                "merchant_order_confirmed",
                {
                    "merchant":
                        MERCHANT_NAME,

                    "merchant_id":
                        MERCHANT_ID,

                    "order_number":
                        fitstore_order.order_number,

                    "product_id":
                        fitstore_order.product_id,

                    "quantity":
                        fitstore_order.quantity,

                    "amount":
                        fitstore_order.amount,

                    "currency":
                        fitstore_order.currency,

                    "status":
                        fitstore_order.status,

                    "razorpay_payment_id":
                        razorpay_payment_id,
                },
                session_id=session_id,
            )

            # -------------------------------------------------
            # 10. Commit entire commerce transaction
            # -------------------------------------------------

            db.commit()

            print(
                "🏪 FitStore order confirmed!"
            )

            print(
                "Order:",
                fitstore_order.order_number,
            )

            print(
                "✅ Mandate marked as executed!"
            )

            print(
                "📝 Payment captured event logged!"
            )

            print(
                "📝 Merchant order confirmation logged!"
            )

            # -------------------------------------------------
            # 11. Update frontend session
            # -------------------------------------------------

            if session_id is not None:

                update_session(
                    session_id=session_id,
                    status="completed",
                    mandate_id=str(
                        mandate.mandate_id
                    ),
                )

        except Exception:

            db.rollback()

            raise

        finally:

            db.close()

    # =====================================================
    # PAYMENT FAILED
    # =====================================================

    elif event == "payment.failed":

        payment = (
            payload["payload"]
            ["payment"]
            ["entity"]
        )

        razorpay_payment_id = payment["id"]

        razorpay_order_id = payment["order_id"]

        print(
            "❌ Payment failed!"
        )

        print(
            "Payment ID:",
            razorpay_payment_id,
        )

        print(
            "Order ID:",
            razorpay_order_id,
        )

        db = SessionLocal()

        try:

            # -------------------------------------------------
            # Find transaction
            # -------------------------------------------------

            transaction = (
                db.query(
                    RazorpayTransaction
                )
                .filter(
                    RazorpayTransaction
                    .razorpay_order_id
                    == razorpay_order_id
                )
                .first()
            )

            if transaction is None:

                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Razorpay transaction "
                        "not found"
                    ),
                )

            # -------------------------------------------------
            # Find mandate
            # -------------------------------------------------

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
                    detail="Mandate not found",
                )

            # -------------------------------------------------
            # Find session ID
            # -------------------------------------------------

            session_id = None

            session_event = (
                db.query(AuditLog)
                .filter(
                    AuditLog.mandate_id
                    == mandate.mandate_id
                )
                .filter(
                    AuditLog.session_id.isnot(None)
                )
                .order_by(
                    AuditLog.id.desc()
                )
                .first()
            )

            if session_event is not None:

                session_id = (
                    session_event.session_id
                )

            # -------------------------------------------------
            # Update transaction
            # -------------------------------------------------

            transaction.razorpay_payment_id = (
                razorpay_payment_id
            )

            transaction.status = "failed"

            # -------------------------------------------------
            # Decline mandate
            # -------------------------------------------------

            mandate.status = "declined"

            # -------------------------------------------------
            # Log failed payment
            # -------------------------------------------------

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
                        ),
                },
                session_id=session_id,
            )

            db.commit()

            print(
                "❌ Mandate marked as declined!"
            )

            print(
                "📝 Payment failure logged!"
            )

            # -------------------------------------------------
            # Update frontend session
            # -------------------------------------------------

            if session_id is not None:

                update_session(
                    session_id=session_id,
                    status="payment_failed",
                    mandate_id=str(
                        mandate.mandate_id
                    ),
                )

        except Exception:

            db.rollback()

            raise

        finally:

            db.close()

    # =====================================================
    # UNKNOWN / OTHER WEBHOOK
    # =====================================================

    return {
        "status": "received"
    }


# =========================================================
# LEGACY TEST ENDPOINT
# =========================================================

@app.post("/create-test-order")
def create_test_order():

    # -----------------------------------------------------
    # 1. Create test mandate
    # -----------------------------------------------------

    mandate = create_mandate(
        buyer_id="test-buyer",
        product_id=3,
        quantity=1,
        agreed_price=850000,
    )

    print(
        "✅ Test mandate created!"
    )

    print(
        "Mandate ID:",
        mandate.mandate_id,
    )

    # -----------------------------------------------------
    # 2. Validate mandate
    # -----------------------------------------------------

    is_valid, reason = validate_mandate(
        mandate.mandate_id
    )

    if not is_valid:

        raise HTTPException(
            status_code=400,
            detail=(
                "Mandate validation failed: "
                f"{reason}"
            ),
        )

    print(
        "✅ Test mandate validated!"
    )

    # -----------------------------------------------------
    # 3. Create Razorpay order
    # -----------------------------------------------------

    return create_order_for_mandate(
        mandate
    )