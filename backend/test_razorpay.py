from datetime import datetime, timezone

from database import SessionLocal
from models import RazorpayTransaction
from razorpay_service import create_razorpay_order, create_payment_link
from mandate import create_mandate


# 1. Create a test mandate
mandate = create_mandate(
    buyer_id="test-buyer",
    product_id=3,
    quantity=1,
    agreed_price=850000
)

print("✅ Mandate created!")
print("Mandate ID:", mandate.mandate_id)
print("Amount:", mandate.agreed_price)


# 2. Create Razorpay order
order = create_razorpay_order(
    amount=mandate.agreed_price,
    mandate_id=mandate.mandate_id
)

print("✅ Razorpay order created!")
print("Razorpay Order ID:", order["id"])
print("Amount:", order["amount"])
print("Currency:", order["currency"])
print("Status:", order["status"])


# 3. Store Razorpay transaction in PostgreSQL
db = SessionLocal()

try:
    transaction = RazorpayTransaction(
        mandate_id=mandate.mandate_id,
        razorpay_order_id=order["id"],
        status=order["status"],
        created_at=datetime.now(timezone.utc)
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

# 4. Create payment link
payment_link = create_payment_link(
    amount=mandate.agreed_price,
    mandate_id=mandate.mandate_id,
    order_id=order["id"]
)

print("✅ Payment link created!")
print("Payment Link ID:", payment_link["id"])
print("Payment URL:", payment_link["short_url"])