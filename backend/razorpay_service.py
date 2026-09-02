from dotenv import load_dotenv
import os
import razorpay


load_dotenv()

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    raise ValueError("Razorpay credentials are not set in .env")


client = razorpay.Client(
    auth=(
        RAZORPAY_KEY_ID,
        RAZORPAY_KEY_SECRET
    )
)


def create_razorpay_order(
    amount,
    mandate_id
):
    order_data = {
        "amount": amount,
        "currency": "INR",
        "receipt": str(mandate_id)
    }

    order = client.order.create(
        data=order_data
    )

    return order

def create_payment_link(
    amount,
    mandate_id,
    order_id
):
    payment_link_data = {
        "amount": amount,
        "currency": "INR",
        "reference_id": str(mandate_id),
        "description": f"Payment for mandate {mandate_id}",
        "order_id": order_id,
    }

    payment_link = client.payment_link.create(
        data=payment_link_data
    )

    return payment_link