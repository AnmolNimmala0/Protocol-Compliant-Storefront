import hmac
import hashlib
import json
import os

from dotenv import load_dotenv

load_dotenv()

RAZORPAY_WEBHOOK_SECRET = os.getenv(
    "RAZORPAY_WEBHOOK_SECRET"
)

payload = {
    "event":"payment.failed",
    "payload": {
        "payment": {
            "entity": {
                "id": "pay_test_456",
                "order_id": "order_TWjooJa743EdwQ"
            }
        }
    }
}

body = json.dumps(
    payload,
    separators=(",", ":")
).encode()

signature = hmac.new(
    RAZORPAY_WEBHOOK_SECRET.encode(),
    body,
    hashlib.sha256
).hexdigest()

print("Webhook body:")
print(body.decode())

print("\nGenerated signature:")
print(signature)