import asyncio
import json
import os
import requests
from datetime import datetime, timezone
from typing import Literal

from dotenv import load_dotenv
from mcp import Client
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from database import SessionLocal
from models import AuditLog

from mandate import create_mandate, validate_mandate


load_dotenv()


MCP_SERVER_URL = "http://127.0.0.1:8001/mcp"
BACKEND_URL = "http://127.0.0.1:8000"


# =========================================================
# AUDIT LOGGING
# =========================================================

def log_audit_event(event_type, detail):

    db = SessionLocal()

    try:

        event = AuditLog(
            mandate_id=None,
            event_type=event_type,
            detail=detail,
            created_at=datetime.now(timezone.utc)
        )

        db.add(event)
        db.commit()

    finally:

        db.close()


# =========================================================
# LLM OUTPUT SCHEMAS
# =========================================================

class ShoppingProposal(BaseModel):

    product_id: int = Field(
        description=(
            "The ID of the product selected from "
            "the merchant catalog."
        )
    )

    quantity: int = Field(
        description=(
            "Number of units the buyer wants "
            "to purchase."
        )
    )

    budget_ceiling: int = Field(
        description=(
            "Maximum amount the buyer is willing "
            "to spend, expressed in paise."
        )
    )

    reason: str = Field(
        description=(
            "Short explanation for why this product "
            "matches the request."
        )
    )


class NegotiationDecision(BaseModel):

    decision: Literal[
        "accept",
        "decline",
        "request_alternative"
    ] = Field(
        description=(
            "The buyer agent's decision after "
            "evaluating the merchant's response."
        )
    )

    reasoning: str = Field(
        description=(
            "Explain why the merchant response does "
            "or does not satisfy the customer's request."
        )
    )

    proposed_product_id: int | None = Field(
        default=None,
        description=(
            "Optional product ID if requesting "
            "an alternative."
        )
    )

    proposed_quantity: int | None = Field(
        default=None,
        description=(
            "Optional quantity if requesting "
            "an alternative."
        )
    )


# =========================================================
# GEMINI CLIENT
# =========================================================

gemini = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


# =========================================================
# MCP: GET MERCHANT CATALOG
# =========================================================

async def get_catalog():

    print(
        "\n🔌 Connecting to Merchant MCP server..."
    )

    async with Client(MCP_SERVER_URL) as mcp_client:

        print(
            "✅ Connected to Merchant MCP server"
        )

        tools_result = await mcp_client.list_tools()

        print("\n🛠️ Available MCP tools:")

        for tool in tools_result.tools:
            print(f"  - {tool.name}")

        result = await mcp_client.call_tool(
            "list_products",
            {}
        )

        products = []

        for content in result.content:

            if content.type == "text":

                products.append(
                    json.loads(content.text)
                )

        return products


# =========================================================
# LLM #1: INITIAL PRODUCT SELECTION
# =========================================================

def choose_product(
    products,
    shopping_brief
):

    catalog_text = json.dumps(
        products,
        indent=2,
        ensure_ascii=False
    )

    prompt = f"""
You are the Buyer Agent in an agentic commerce system.

Your job is to understand the customer's request and create the
best possible purchase proposal using the merchant catalog.

CUSTOMER REQUEST:
{shopping_brief}

MERCHANT CATALOG:
{catalog_text}

IMPORTANT CUSTOMER-CONSTRAINT RULES:

1. Preserve explicit customer requirements.

2. If the customer explicitly specifies a quantity, that quantity
   is a HARD CONSTRAINT.

   Example:
   Customer says "I need 2 yoga mats."

   You MUST propose:
   quantity = 2

   You MUST NOT reduce the quantity to 1 simply because 1 unit
   fits the customer's budget.

3. If the requested quantity makes the purchase exceed the customer's
   budget, DO NOT silently reduce the quantity.

   Instead:
   - Preserve the requested quantity.
   - Create the proposal using that quantity.
   - Let the merchant negotiation stage handle the budget conflict.

4. The buyer agent represents the customer's intent.
   Never silently change the customer's requested quantity,
   budget, or other explicit requirements.

5. The customer's budget is also a HARD CONSTRAINT.

   Never increase the budget_ceiling above the amount specified
   by the customer.

6. If the customer specifies a total budget, budget_ceiling must
   represent that total maximum amount.

7. If the customer specifies a rupee budget, convert it to paise.

   Example:
   ₹2,000 = 200000 paise.

8. Select only a product that actually exists in the merchant catalog.

9. Use the exact product ID provided by the merchant.

10. Consider:
    - product category
    - product description
    - price
    - stock
    - relevance to the customer's request

11. Never invent:
    - products
    - product IDs
    - prices
    - stock
    - categories

12. The requested quantity must not exceed the product's available stock.

13. If no product can satisfy the request perfectly, select the
    closest valid product from the catalog while preserving all
    explicit customer constraints that can legally be preserved.

14. A proposal does NOT have to already satisfy the budget if the
    customer's explicit quantity makes that impossible.

    Example:
    Customer:
    "I need 2 fitness gifts under ₹2,000."

    If the best matching product costs ₹1,999 each:

    quantity = 2
    budget_ceiling = 200000

    Total catalog price = ₹3,998.

    This is still the correct buyer proposal because the buyer
    must preserve the customer's requested quantity.

    The merchant negotiation stage should then determine whether
    the merchant can make a counter-offer.

15. Your reason should explain why the selected product matches
    the customer's request.

16. Return ONLY the structured ShoppingProposal.
"""

    models = [
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
    ]

    for model in models:

        print(
            f"\n🧠 Trying model: {model}"
        )

        try:

            response = gemini.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ShoppingProposal,
                )
            )

            proposal = ShoppingProposal.model_validate_json(
                response.text
            )

            print(
                f"✅ {model} responded successfully"
            )

            return proposal

        except Exception as e:

            print(
                f"⚠️ {model} failed: {e}"
            )

    raise RuntimeError(
        "All configured Gemini models are currently unavailable."
    )


# =========================================================
# PRODUCT LOOKUP
# =========================================================

def find_product(
    products,
    product_id
):

    for product in products:

        if product["id"] == product_id:
            return product

    return None


# =========================================================
# MCP: NEGOTIATE WITH MERCHANT AGENT
# =========================================================

async def negotiate_with_merchant(
    product_id,
    quantity,
    budget_ceiling
):

    print(
        "\n📨 Sending proposal to Merchant Agent..."
    )

    async with Client(MCP_SERVER_URL) as mcp_client:

        result = await mcp_client.call_tool(
            "negotiate_proposal",
            {
                "product_id": product_id,
                "quantity": quantity,
                "budget_ceiling": budget_ceiling,
            }
        )

    for content in result.content:

        if content.type == "text":

            merchant_response = json.loads(
                content.text
            )

            print(
                "\n🏪 Merchant Agent response:"
            )

            print(
                json.dumps(
                    merchant_response,
                    indent=2,
                    ensure_ascii=False
                )
            )

            return merchant_response

    raise RuntimeError(
        "Merchant Agent returned no response."
    )


# =========================================================
# LLM #2: REASON ABOUT MERCHANT COUNTER
# =========================================================

def reason_about_counter(
    customer_request,
    original_proposal,
    merchant_response
):

    print(
        "\n🧠 Buyer Agent is reasoning "
        "about the merchant response..."
    )

    prompt = f"""
You are the Buyer Agent in an agentic commerce system.

The customer gave you an original shopping request.

You previously selected a product from the merchant catalog.

The merchant has now responded to your proposal.

Your job is to reason about the merchant's response and decide
what the buyer should do next.

CUSTOMER'S ORIGINAL REQUEST:
{customer_request}

ORIGINAL BUYER PROPOSAL:
{json.dumps(
    original_proposal.model_dump(),
    indent=2,
    ensure_ascii=False
)}

MERCHANT RESPONSE:
{json.dumps(
    merchant_response,
    indent=2,
    ensure_ascii=False
)}

You may choose exactly ONE action:

1. ACCEPT

Accept the merchant's response if:
- It still satisfies the customer's original intent.
- The merchant's offer is within the customer's budget.
- The offer is commercially reasonable.

2. DECLINE

Decline if:
- The merchant's response does not satisfy the customer's request.
- The price exceeds the customer's budget.
- The offer is otherwise unsuitable.

3. REQUEST_ALTERNATIVE

Request an alternative if:
- The current offer is unsuitable.
- Another product from the merchant catalog could reasonably
  satisfy the customer's original request.

IMPORTANT RULES:

- Never exceed the customer's budget ceiling.
- Never invent products.
- Never invent prices.
- Never invent stock.
- Never change the customer's original intent.
- If the customer explicitly requested a quantity, do not accept
  an offer that silently reduces that quantity unless the customer
  explicitly allowed flexibility.
- Carefully inspect the merchant's actual response.
- Your reasoning must explain the decision.
- Return ONLY the structured decision.

The deterministic system will independently verify any
financial agreement before creating a mandate.
"""

    models = [
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
    ]

    for model in models:

        print(
            f"\n🧠 Trying negotiation model: {model}"
        )

        try:

            response = gemini.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=NegotiationDecision,
                )
            )

            decision = NegotiationDecision.model_validate_json(
                response.text
            )

            print(
                f"✅ {model} negotiation reasoning completed"
            )

            print(
                "\n🤝 Buyer Agent negotiation decision:"
            )

            print(
                json.dumps(
                    decision.model_dump(),
                    indent=2,
                    ensure_ascii=False
                )
            )

            return decision

        except Exception as e:

            print(
                f"⚠️ {model} failed: {e}"
            )

    raise RuntimeError(
        "All configured Gemini negotiation models "
        "are currently unavailable."
    )


# =========================================================
# DETERMINISTIC NEGOTIATION SAFETY GATE
# =========================================================

def validate_accepted_counter(
    proposal,
    merchant_response,
    products
):

    if merchant_response.get("decision") != "counter":

        raise ValueError(
            "Expected a merchant counter-offer."
        )

    counter = merchant_response.get("counter")

    if counter is None:

        raise ValueError(
            "Merchant counter-offer is missing."
        )

    product_id = counter.get("product_id")
    quantity = counter.get("quantity")
    price = counter.get("price")

    # -----------------------------------------------------
    # Validate required fields
    # -----------------------------------------------------

    if product_id is None:

        raise ValueError(
            "Merchant counter is missing product_id."
        )

    if quantity is None or quantity <= 0:

        raise ValueError(
            "Merchant counter has invalid quantity."
        )

    if price is None or price < 0:

        raise ValueError(
            "Merchant counter has invalid price."
        )

    # -----------------------------------------------------
    # Verify product exists
    # -----------------------------------------------------

    product = find_product(
        products,
        product_id
    )

    if product is None:

        raise ValueError(
            "Merchant counter references "
            "a product that does not exist."
        )

    # -----------------------------------------------------
    # Verify stock
    # -----------------------------------------------------

    if product["stock"] < quantity:

        raise ValueError(
            "Merchant counter exceeds available stock."
        )

    # -----------------------------------------------------
    # Verify merchant discount policy
    # -----------------------------------------------------

    normal_price = (
        product["price"] * quantity
    )

    max_discount_pct = min(
        product.get("max_discount_pct", 0) or 0,
        10
    )

    minimum_allowed_price = (
        normal_price * (100 - max_discount_pct)
    ) // 100

    if price < minimum_allowed_price:

        raise ValueError(
            "Merchant counter exceeds the "
            "maximum allowed discount."
        )

    # -----------------------------------------------------
    # Verify buyer budget
    # -----------------------------------------------------

    if price > proposal.budget_ceiling:

        raise ValueError(
            "Merchant counter exceeds buyer budget."
        )

    print(
        "\n🛡️ Deterministic safety gate passed."
    )

    return {
        "product_id": product_id,
        "quantity": quantity,
        "agreed_price": price,
    }


# =========================================================
# VALIDATE DIRECT MERCHANT ACCEPTANCE
# =========================================================

def validate_accepted_offer(
    proposal,
    merchant_response,
    products
):

    if merchant_response.get("decision") != "accept":

        raise ValueError(
            "Expected merchant acceptance."
        )

    accepted = merchant_response.get("accepted")

    if accepted is None:

        raise ValueError(
            "Merchant accepted proposal but "
            "returned no accepted offer."
        )

    product_id = accepted.get("product_id")
    quantity = accepted.get("quantity")
    price = accepted.get("price")

    if product_id is None:

        raise ValueError(
            "Accepted offer is missing product_id."
        )

    if quantity is None or quantity <= 0:

        raise ValueError(
            "Accepted offer has invalid quantity."
        )

    if price is None or price < 0:

        raise ValueError(
            "Accepted offer has invalid price."
        )

    product = find_product(
        products,
        product_id
    )

    if product is None:

        raise ValueError(
            "Accepted offer references "
            "a product that does not exist."
        )

    if product["stock"] < quantity:

        raise ValueError(
            "Accepted offer exceeds available stock."
        )

    expected_price = (
        product["price"] * quantity
    )

    if price != expected_price:

        raise ValueError(
            "Accepted offer price does not match "
            "the merchant's live catalog price."
        )

    if price > proposal.budget_ceiling:

        raise ValueError(
            "Merchant accepted an offer that exceeds "
            "the buyer budget."
        )

    print(
        "\n🛡️ Deterministic acceptance gate passed."
    )

    return {
        "product_id": product_id,
        "quantity": quantity,
        "agreed_price": price,
    }


# =========================================================
# CREATE RAZORPAY ORDER
# =========================================================

def create_razorpay_order_for_mandate(
    mandate_id
):

    print(
        "\n💳 Creating Razorpay order..."
    )

    response = requests.post(
        f"{BACKEND_URL}/create-order-for-mandate/{mandate_id}"
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Failed to create Razorpay order: "
            f"{response.text}"
        )

    order_data = response.json()

    print(
        "\n✅ Razorpay order created!"
    )

    print(
        json.dumps(
            order_data,
            indent=2
        )
    )

    return order_data


# =========================================================
# MAIN
# =========================================================

async def main():

    # -----------------------------------------------------
    # Customer request
    # -----------------------------------------------------

    shopping_brief = (
        "I need 2 fitness gifts for someone, "
        "with a total budget of ₹3,600."
    )

    buyer_id = "buyer-agent-demo"

    print(
        "\n🛒 Customer request:"
    )

    print(
        shopping_brief
    )

    # -----------------------------------------------------
    # STEP 1
    # Discover merchant catalog through MCP
    # -----------------------------------------------------

    products = await get_catalog()

    # -----------------------------------------------------
    # STEP 2
    # Buyer LLM #1 chooses product
    # -----------------------------------------------------

    print(
        "\n🤖 Asking Gemini to choose the best product..."
    )

    proposal = choose_product(
        products,
        shopping_brief
    )

    print(
        "\n💡 Buyer Agent proposal:"
    )

    print(
        json.dumps(
            proposal.model_dump(),
            indent=2,
            ensure_ascii=False
        )
    )

    # -----------------------------------------------------
    # STEP 3
    # Send proposal to Merchant Agent
    # -----------------------------------------------------

    merchant_response = await negotiate_with_merchant(
        product_id=proposal.product_id,
        quantity=proposal.quantity,
        budget_ceiling=proposal.budget_ceiling
    )

    # -----------------------------------------------------
    # STEP 4
    # Merchant accepts immediately
    # -----------------------------------------------------

    if merchant_response.get("decision") == "accept":

        print(
            "\n✅ Merchant accepted "
            "the original proposal."
        )

        # Log buyer decision.
        log_audit_event(
            "buyer_decision",
            {
                "decision": "accept",
                "reasoning": (
                    "Merchant accepted the "
                    "original proposal."
                )
            }
        )

        accepted_data = validate_accepted_offer(
            proposal=proposal,
            merchant_response=merchant_response,
            products=products
        )

        negotiated_product_id = (
            accepted_data["product_id"]
        )

        negotiated_quantity = (
            accepted_data["quantity"]
        )

        negotiated_price = (
            accepted_data["agreed_price"]
        )

    # -----------------------------------------------------
    # STEP 5
    # Merchant countered
    # -----------------------------------------------------

    elif merchant_response.get("decision") == "counter":

        buyer_decision = reason_about_counter(
            customer_request=shopping_brief,
            original_proposal=proposal,
            merchant_response=merchant_response
        )

        # -------------------------------------------------
        # BUYER DECLINES
        # -------------------------------------------------

        if buyer_decision.decision == "decline":

            log_audit_event(
                "buyer_decision",
                {
                    "decision": "decline",
                    "reasoning": buyer_decision.reasoning,
                    "proposed_product_id": (
                        buyer_decision.proposed_product_id
                    ),
                    "proposed_quantity": (
                        buyer_decision.proposed_quantity
                    )
                }
            )

            print(
                "\n❌ Buyer Agent declined "
                "the merchant counter."
            )

            print(
                f"Reason: "
                f"{buyer_decision.reasoning}"
            )

            return

        # -------------------------------------------------
        # BUYER REQUESTS ALTERNATIVE
        # -------------------------------------------------

        if buyer_decision.decision == "request_alternative":

            log_audit_event(
                "buyer_decision",
                {
                    "decision": "request_alternative",
                    "reasoning": buyer_decision.reasoning,
                    "proposed_product_id": (
                        buyer_decision.proposed_product_id
                    ),
                    "proposed_quantity": (
                        buyer_decision.proposed_quantity
                    )
                }
            )

            print(
                "\n🔄 Buyer Agent requested "
                "an alternative."
            )

            print(
                f"Reason: "
                f"{buyer_decision.reasoning}"
            )

            print(
                "\n⚠️ Alternative-product negotiation "
                "will be implemented in the next iteration."
            )

            return

        # -------------------------------------------------
        # BUYER ACCEPTS COUNTER
        # -------------------------------------------------

        if buyer_decision.decision == "accept":

            log_audit_event(
                "buyer_decision",
                {
                    "decision": "accept",
                    "reasoning": buyer_decision.reasoning,
                    "proposed_product_id": (
                        buyer_decision.proposed_product_id
                    ),
                    "proposed_quantity": (
                        buyer_decision.proposed_quantity
                    )
                }
            )

            accepted_data = validate_accepted_counter(
                proposal=proposal,
                merchant_response=merchant_response,
                products=products
            )

            negotiated_product_id = (
                accepted_data["product_id"]
            )

            negotiated_quantity = (
                accepted_data["quantity"]
            )

            negotiated_price = (
                accepted_data["agreed_price"]
            )

    else:

        raise ValueError(
            "Unexpected merchant negotiation response."
        )

    # -----------------------------------------------------
    # STEP 6
    # Create deterministic signed mandate
    # -----------------------------------------------------

    print(
        "\n📝 Creating mandate from "
        "negotiated agreement..."
    )

    mandate = create_mandate(
        buyer_id=buyer_id,
        product_id=negotiated_product_id,
        quantity=negotiated_quantity,
        agreed_price=negotiated_price
    )

    print(
        f"\n✅ Mandate created: "
        f"{mandate.mandate_id}"
    )

    # -----------------------------------------------------
    # STEP 7
    # Validate mandate
    # -----------------------------------------------------

    print(
        "\n🔐 Validating mandate..."
    )

    is_valid, reason = validate_mandate(
        mandate.mandate_id
    )

    if not is_valid:

        print(
            "\n❌ Mandate validation failed!"
        )

        print(
            f"Reason: {reason}"
        )

        return

    print(
        "\n✅ Mandate validation successful!"
    )

    # -----------------------------------------------------
    # STEP 8
    # Display validated mandate
    # -----------------------------------------------------

    print(
        "\n📋 Validated mandate:"
    )

    print(
        json.dumps(
            {
                "mandate_id": str(
                    mandate.mandate_id
                ),
                "buyer_agent_id": (
                    mandate.buyer_agent_id
                ),
                "product_id": mandate.product_id,
                "quantity": mandate.quantity,
                "agreed_price": mandate.agreed_price,
                "status": mandate.status,
                "expires_at": (
                    mandate.expires_at.isoformat()
                ),
            },
            indent=2
        )
    )

    # -----------------------------------------------------
    # STEP 9
    # Create Razorpay order
    # -----------------------------------------------------

    order_data = (
        create_razorpay_order_for_mandate(
            mandate.mandate_id
        )
    )

    # -----------------------------------------------------
    # STEP 10
    # Report transaction
    # -----------------------------------------------------

    print(
        "\n🎉 Buyer Agent transaction flow "
        "reached Razorpay!"
    )

    print(
        "Razorpay Order ID:",
        order_data["order_id"]
    )

    print(
        "Amount:",
        order_data["amount"],
        "paise"
    )

    print(
        "Currency:",
        order_data["currency"]
    )

    print(
        "Mandate ID:",
        order_data["mandate_id"]
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    asyncio.run(main())