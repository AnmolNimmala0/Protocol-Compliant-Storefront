import json

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import Literal

from mcp.server.mcpserver import MCPServer
from database import SessionLocal
from models import Product, AuditLog


load_dotenv()


# =========================================================
# CONFIG
# =========================================================

mcp = MCPServer("Merchant Agent", version="1.0.0")

from ai_client import generate


# =========================================================
# MERCHANT LLM OUTPUT SCHEMA
# =========================================================

class MerchantReasoning(BaseModel):
    decision: Literal[
        "accept",
        "counter",
        "decline"
    ]

    reasoning: str = Field(
        description="Explain the merchant's reasoning."
    )

    counter_quantity: int | None = Field(
        default=None,
        description="Quantity to offer if making a counter."
    )

    discount_pct: int | None = Field(
        default=None,
        description="Discount percentage to offer if making a counter."
    )


# =========================================================
# AUDIT LOGGING
# =========================================================

def log_audit_event(event_type, detail):
    """
    Record an event in the audit trail.

    Negotiation happens before a mandate exists,
    so mandate_id is intentionally NULL here.
    """

    db = SessionLocal()

    try:
        event = AuditLog(
            mandate_id=None,
            event_type=event_type,
            detail=detail
        )

        db.add(event)
        db.commit()

    finally:
        db.close()


# =========================================================
# MCP TOOL: LIST PRODUCTS
# =========================================================

@mcp.tool()
def list_products():

    db = SessionLocal()

    try:

        products = db.query(Product).all()

        return [
            {
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "price": product.price,
                "stock": product.stock,
                "description": product.description,
                "max_discount_pct": product.max_discount_pct,
            }
            for product in products
        ]

    finally:
        db.close()


# =========================================================
# MCP TOOL: GET PRODUCT
# =========================================================

@mcp.tool()
def get_product(product_id: int):

    db = SessionLocal()

    try:

        product = (
            db.query(Product)
            .filter(Product.id == product_id)
            .first()
        )

        if product is None:

            return {
                "error": "Product not found",
                "product_id": product_id
            }

        return {
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "price": product.price,
            "stock": product.stock,
            "description": product.description,
            "max_discount_pct": product.max_discount_pct,
        }

    finally:
        db.close()


# =========================================================
# MCP TOOL: CHECK AVAILABILITY
# =========================================================

@mcp.tool()
def check_availability(
    product_id: int,
    quantity: int
):

    db = SessionLocal()

    try:

        product = (
            db.query(Product)
            .filter(Product.id == product_id)
            .first()
        )

        if product is None:

            return {
                "available": False,
                "reason": "Product not found",
                "product_id": product_id
            }

        if quantity <= 0:

            return {
                "available": False,
                "reason": "Quantity must be greater than zero",
                "product_id": product_id
            }

        if product.stock >= quantity:

            return {
                "available": True,
                "product_id": product.id,
                "requested_quantity": quantity,
                "stock": product.stock
            }

        return {
            "available": False,
            "product_id": product.id,
            "requested_quantity": quantity,
            "stock": product.stock,
            "reason": "Insufficient stock"
        }

    finally:
        db.close()


# =========================================================
# MCP TOOL: GET MERCHANT TERMS
# =========================================================

@mcp.tool()
def get_terms():

    return {
        "currency": "INR",
        "max_discount_pct": 10,
        "mandate_expiry_minutes": 30
    }


# =========================================================
# MCP TOOL: NEGOTIATE PROPOSAL
# =========================================================

@mcp.tool()
def negotiate_proposal(
    product_id: int,
    quantity: int,
    budget_ceiling: int
):
    """
    Merchant Agent evaluates a buyer proposal.

    Gemini provides the merchant's reasoning.

    Deterministic policy remains authoritative over:
    - product existence
    - stock
    - price
    - maximum discount
    - final financial offer
    """

    db = SessionLocal()

    try:

        # -------------------------------------------------
        # 1. Log buyer proposal
        # -------------------------------------------------

        buyer_proposal = {
            "product_id": product_id,
            "quantity": quantity,
            "budget_ceiling": budget_ceiling
        }

        log_audit_event(
            "buyer_proposal",
            buyer_proposal
        )

        # -------------------------------------------------
        # 2. Get live product
        # -------------------------------------------------

        product = (
            db.query(Product)
            .filter(Product.id == product_id)
            .first()
        )

        if product is None:

            merchant_response = {
                "decision": "decline",
                "reason": "Product not found.",
                "product_id": product_id
            }

            log_audit_event(
                "merchant_response",
                merchant_response
            )

            return merchant_response

        # -------------------------------------------------
        # 3. Validate quantity
        # -------------------------------------------------

        if quantity <= 0:

            merchant_response = {
                "decision": "decline",
                "reason": "Quantity must be greater than zero.",
                "product_id": product_id
            }

            log_audit_event(
                "merchant_response",
                merchant_response
            )

            return merchant_response

        # -------------------------------------------------
        # 4. Calculate normal price
        # -------------------------------------------------

        normal_total = product.price * quantity

        # -------------------------------------------------
        # 5. Ask Merchant LLM to reason
        # -------------------------------------------------

        merchant_context = {
            "product": {
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "price": product.price,
                "stock": product.stock,
                "description": product.description,
                "max_discount_pct": product.max_discount_pct,
            },
            "buyer_proposal": {
                "product_id": product_id,
                "quantity": quantity,
                "budget_ceiling": budget_ceiling,
            },
            "normal_total_price": normal_total
        }

        prompt = f"""
You are the Merchant Agent in an agent-to-agent commerce system.

A Buyer Agent has sent a purchase proposal.

Your task is to reason like the merchant and recommend one action:

- accept
- counter
- decline

MERCHANT DATA:

{json.dumps(merchant_context, indent=2, ensure_ascii=False)}

Think about:

1. Whether the requested product exists.
2. Whether enough stock exists.
3. Whether the buyer can afford the normal price.
4. Whether a commercially reasonable discount could help.
5. Whether reducing quantity would make sense because of stock.
6. Whether the transaction is commercially reasonable.

IMPORTANT:

- Never invent products.
- Never invent stock.
- Never invent prices.
- Never exceed the product's maximum discount.
- Never offer more units than available stock.
- Never increase the buyer's budget.
- The final financial offer will be independently calculated
  and verified by deterministic merchant policy.

Your reasoning should explain WHY the merchant chooses
accept, counter, or decline.

Return ONLY the structured response.
"""

        response_text = generate(
            contents=prompt,
            response_schema=MerchantReasoning,
        )

        merchant_reasoning = MerchantReasoning.model_validate_json(
            response_text
        )

        print("\n🤖 Merchant Agent reasoning:")

        print(
            json.dumps(
                merchant_reasoning.model_dump(),
                indent=2,
                ensure_ascii=False
            )
        )

        # -------------------------------------------------
        # 6. Deterministic business policy
        # -------------------------------------------------

        max_discount_pct = min(
            product.max_discount_pct or 0,
            10
        )

        # -------------------------------------------------
        # CASE A: OUT OF STOCK
        # -------------------------------------------------

        if product.stock <= 0:

            merchant_response = {
                "decision": "decline",
                "reason": (
                    "Product is out of stock."
                )
            }

        # -------------------------------------------------
        # CASE B: NOT ENOUGH STOCK
        # -------------------------------------------------

        elif quantity > product.stock:

            counter_quantity = product.stock

            counter_price = (
                product.price * counter_quantity
            )

            merchant_response = {
                "decision": "counter",
                "reason": (
                    "Requested quantity exceeds "
                    "available stock."
                ),
                "counter": {
                    "product_id": product.id,
                    "quantity": counter_quantity,
                    "price": counter_price,
                    "discount_pct": 0,
                    "message": (
                        f"Merchant can provide only "
                        f"{counter_quantity} units."
                    )
                }
            }

        # -------------------------------------------------
        # CASE C: NORMAL PRICE FITS BUDGET
        # -------------------------------------------------

        elif normal_total <= budget_ceiling:

            merchant_response = {
                "decision": "accept",
                "reason": merchant_reasoning.reasoning,
                "accepted": {
                    "product_id": product.id,
                    "quantity": quantity,
                    "price": normal_total,
                    "discount_pct": 0,
                    "message": (
                        f"Merchant accepts {quantity} "
                        f"unit(s) at "
                        f"₹{normal_total / 100:,.2f} total."
                    )
                }
            }

        # -------------------------------------------------
        # CASE D: PRICE EXCEEDS BUDGET
        # -------------------------------------------------

        elif max_discount_pct > 0:

            discount_amount = (
                normal_total * max_discount_pct
            ) // 100

            counter_price = (
                normal_total - discount_amount
            )

            merchant_response = {
                "decision": "counter",
                "reason": merchant_reasoning.reasoning,
                "counter": {
                    "product_id": product.id,
                    "quantity": quantity,
                    "price": counter_price,
                    "discount_pct": max_discount_pct,
                    "message": (
                        f"Merchant counters with "
                        f"{max_discount_pct}% discount: "
                        f"₹{counter_price / 100:,.2f} total."
                    )
                }
            }

        # -------------------------------------------------
        # CASE E: NO DISCOUNT AVAILABLE
        # -------------------------------------------------

        else:

            merchant_response = {
                "decision": "counter",
                "reason": (
                    "The requested quantity is available, "
                    "but the buyer's budget is below the "
                    "merchant's minimum allowed price."
                ),
                "counter": {
                    "product_id": product.id,
                    "quantity": quantity,
                    "price": normal_total,
                    "discount_pct": 0,
                    "message": (
                        f"Merchant can fulfill "
                        f"{quantity} unit(s), but the "
                        f"total price is "
                        f"₹{normal_total / 100:,.2f}."
                    )
                }
            }

        # -------------------------------------------------
        # 7. Log merchant response
        # -------------------------------------------------

        log_audit_event(
            "merchant_response",
            merchant_response
        )

        return merchant_response

    finally:
        db.close()


# =========================================================
# START MCP SERVER
# =========================================================

if __name__ == "__main__":

    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8001
    )