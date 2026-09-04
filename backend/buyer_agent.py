import asyncio
import json
import requests

from datetime import datetime, timezone
from typing import Literal

from dotenv import load_dotenv

from mcp import Client


from pydantic import BaseModel, Field

from database import SessionLocal

from models import AuditLog

from mandate import (
    create_mandate,
    validate_mandate,
)


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()


MCP_SERVER_URL = "http://127.0.0.1:8001/mcp"

BACKEND_URL = "http://127.0.0.1:8000"


# =========================================================
# AUDIT LOGGING
# =========================================================

def log_audit_event(
    event_type,
    detail,
    session_id=None,
    mandate_id=None,
):
    """
    Write an agent execution event to PostgreSQL.

    session_id:
        Identifies the current shopping-agent run.

    mandate_id:
        Associates the event with the financial mandate
        once one has been created.
    """

    db = SessionLocal()

    try:

        event = AuditLog(
            session_id=session_id,
            mandate_id=mandate_id,
            event_type=event_type,
            detail=detail,
            created_at=datetime.now(timezone.utc),
        )

        db.add(event)

        db.commit()

    except Exception:

        db.rollback()

        raise

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
        "request_alternative",
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
# AI CLIENT
# =========================================================

from ai_client import generate


# =========================================================
# MCP: GET MERCHANT CATALOG
# =========================================================

async def get_catalog(
    session_id=None,
):

    print(
        "\n🔌 Connecting to Merchant MCP server..."
    )

    log_audit_event(
        "catalog_discovery_started",
        {
            "server": MCP_SERVER_URL,
            "method": "MCP",
        },
        session_id=session_id,
    )

    async with Client(MCP_SERVER_URL) as mcp_client:

        print(
            "✅ Connected to Merchant MCP server"
        )

        tools_result = await mcp_client.list_tools()

        print("\n🛠️ Available MCP tools:")

        available_tools = []

        for tool in tools_result.tools:

            print(
                f"  - {tool.name}"
            )

            available_tools.append(
                tool.name
            )

        result = await mcp_client.call_tool(
            "list_products",
            {},
        )

        products = []

        for content in result.content:

            if content.type == "text":

                products.append(
                    json.loads(content.text)
                )

        log_audit_event(
            "catalog_discovered",
            {
                "protocol": "MCP",
                "tool": "list_products",
                "product_count": len(products),
                "available_tools": available_tools,
            },
            session_id=session_id,
        )

        return products


# =========================================================
# LLM #1: INITIAL PRODUCT SELECTION
# =========================================================

def choose_product(
    products,
    shopping_brief,
):

    catalog_text = json.dumps(
        products,
        indent=2,
        ensure_ascii=False,
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

    response_text = generate(
        contents=prompt,
        response_schema=ShoppingProposal,
    )

    proposal = ShoppingProposal.model_validate_json(
        response_text
    )

    print(
        "✅ Buyer Agent product selection completed"
    )

    return proposal


# =========================================================
# PRODUCT LOOKUP
# =========================================================

def find_product(
    products,
    product_id,
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
    budget_ceiling,
    session_id=None,
):

    print(
        "\n📨 Sending proposal to Merchant Agent..."
    )

    log_audit_event(
        "merchant_negotiation_started",
        {
            "product_id": product_id,
            "quantity": quantity,
            "budget_ceiling": budget_ceiling,
        },
        session_id=session_id,
    )

    async with Client(MCP_SERVER_URL) as mcp_client:

        result = await mcp_client.call_tool(
            "negotiate_proposal",
            {
                "product_id": product_id,
                "quantity": quantity,
                "budget_ceiling": budget_ceiling,
            },
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
                    ensure_ascii=False,
                )
            )

            log_audit_event(
                "merchant_negotiation_response",
                {
                    "request": {
                        "product_id": product_id,
                        "quantity": quantity,
                        "budget_ceiling": budget_ceiling,
                    },
                    "response": merchant_response,
                },
                session_id=session_id,
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
    merchant_response,
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
    ensure_ascii=False,
)}

MERCHANT RESPONSE:
{json.dumps(
    merchant_response,
    indent=2,
    ensure_ascii=False,
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

    response_text = generate(
        contents=prompt,
        response_schema=NegotiationDecision,
    )

    decision = NegotiationDecision.model_validate_json(
        response_text
    )

    print(
        "✅ Buyer Agent negotiation reasoning completed"
    )

    print(
        "\n🤝 Buyer Agent negotiation decision:"
    )

    print(
        json.dumps(
            decision.model_dump(),
            indent=2,
            ensure_ascii=False,
        )
    )

    return decision


# =========================================================
# DETERMINISTIC NEGOTIATION SAFETY GATE
# =========================================================

def validate_accepted_counter(
    proposal,
    merchant_response,
    products,
):

    if merchant_response.get("decision") != "counter":

        raise ValueError(
            "Expected a merchant counter-offer."
        )

    counter = merchant_response.get(
        "counter"
    )

    if counter is None:

        raise ValueError(
            "Merchant counter-offer is missing."
        )

    product_id = counter.get(
        "product_id"
    )

    quantity = counter.get(
        "quantity"
    )

    price = counter.get(
        "price"
    )


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
        product_id,
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
        10,
    )

    minimum_allowed_price = (
        normal_price
        * (100 - max_discount_pct)
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
    products,
):

    if merchant_response.get("decision") != "accept":

        raise ValueError(
            "Expected merchant acceptance."
        )

    accepted = merchant_response.get(
        "accepted"
    )

    if accepted is None:

        raise ValueError(
            "Merchant accepted proposal but "
            "returned no accepted offer."
        )

    product_id = accepted.get(
        "product_id"
    )

    quantity = accepted.get(
        "quantity"
    )

    price = accepted.get(
        "price"
    )

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
        product_id,
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
    mandate_id,
    session_id=None,
):

    print(
        "\n💳 Creating Razorpay order..."
    )

    log_audit_event(
        "razorpay_order_creation_started",
        {
            "mandate_id": str(
                mandate_id
            ),
        },
        session_id=session_id,
        mandate_id=mandate_id,
    )

    response = requests.post(
        f"{BACKEND_URL}/create-order-for-mandate/{mandate_id}",
        timeout=30,
    )

    if response.status_code != 200:

        log_audit_event(
            "razorpay_order_creation_failed",
            {
                "mandate_id": str(
                    mandate_id
                ),
                "status_code": response.status_code,
                "response": response.text,
            },
            session_id=session_id,
            mandate_id=mandate_id,
        )

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
            indent=2,
        )
    )

    log_audit_event(
        "razorpay_order_created",
        {
            "order_id": order_data["order_id"],
            "amount": order_data["amount"],
            "currency": order_data["currency"],
        },
        session_id=session_id,
        mandate_id=mandate_id,
    )

    return order_data


# =========================================================
# BUYER AGENT WORKFLOW
# =========================================================

async def main(
    shopping_brief=None,
    session_id=None,
):

    # -----------------------------------------------------
    # Customer request
    # -----------------------------------------------------

    if shopping_brief is None:

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

    log_audit_event(
        "shopping_request_received",
        {
            "shopping_brief": shopping_brief,
            "buyer_agent_id": buyer_id,
        },
        session_id=session_id,
    )


    # =====================================================
    # STEP 1
    # Discover merchant catalog through MCP
    # =====================================================

    print(
        "\n🔎 STEP 1 — Catalog discovery"
    )

    products = await get_catalog(
        session_id=session_id
    )


    # =====================================================
    # STEP 2
    # Buyer LLM #1 chooses product
    # =====================================================

    print(
        "\n🤖 STEP 2 — Buyer Agent product selection"
    )

    proposal = choose_product(
        products,
        shopping_brief,
    )

    print(
        "\n💡 Buyer Agent proposal:"
    )

    print(
        json.dumps(
            proposal.model_dump(),
            indent=2,
            ensure_ascii=False,
        )
    )

    selected_product = find_product(
        products,
        proposal.product_id,
    )

    log_audit_event(
        "buyer_product_selected",
        {
            "product_id": proposal.product_id,
            "product_name": (
                selected_product["name"]
                if selected_product
                else None
            ),
            "quantity": proposal.quantity,
            "budget_ceiling": proposal.budget_ceiling,
            "reason": proposal.reason,
        },
        session_id=session_id,
    )


    # =====================================================
    # STEP 3
    # Send proposal to Merchant Agent
    # =====================================================

    print(
        "\n🤝 STEP 3 — Merchant negotiation"
    )

    merchant_response = (
        await negotiate_with_merchant(
            product_id=proposal.product_id,
            quantity=proposal.quantity,
            budget_ceiling=proposal.budget_ceiling,
            session_id=session_id,
        )
    )


    # =====================================================
    # STEP 4
    # Merchant accepts immediately
    # =====================================================

    if merchant_response.get(
        "decision"
    ) == "accept":

        print(
            "\n✅ Merchant accepted "
            "the original proposal."
        )

        log_audit_event(
            "buyer_decision",
            {
                "decision": "accept",
                "reasoning": (
                    "Merchant accepted the "
                    "original proposal."
                ),
            },
            session_id=session_id,
        )

        accepted_data = (
            validate_accepted_offer(
                proposal=proposal,
                merchant_response=merchant_response,
                products=products,
            )
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


    # =====================================================
    # STEP 5
    # Merchant countered
    # =====================================================

    elif merchant_response.get(
        "decision"
    ) == "counter":

        print(
            "\n🔄 Merchant Agent made a counter-offer."
        )

        buyer_decision = (
            reason_about_counter(
                customer_request=shopping_brief,
                original_proposal=proposal,
                merchant_response=merchant_response,
            )
        )


        # -------------------------------------------------
        # BUYER DECLINES
        # -------------------------------------------------

        if buyer_decision.decision == "decline":

            log_audit_event(
                "buyer_decision",
                {
                    "decision": "decline",
                    "reasoning": (
                        buyer_decision.reasoning
                    ),
                    "proposed_product_id": (
                        buyer_decision.proposed_product_id
                    ),
                    "proposed_quantity": (
                        buyer_decision.proposed_quantity
                    ),
                },
                session_id=session_id,
            )

            print(
                "\n❌ Buyer Agent declined "
                "the merchant counter."
            )

            print(
                f"Reason: "
                f"{buyer_decision.reasoning}"
            )

            return None


        # -------------------------------------------------
        # BUYER REQUESTS ALTERNATIVE
        # -------------------------------------------------

        if (
            buyer_decision.decision
            == "request_alternative"
        ):

            log_audit_event(
                "buyer_decision",
                {
                    "decision": "request_alternative",
                    "reasoning": (
                        buyer_decision.reasoning
                    ),
                    "proposed_product_id": (
                        buyer_decision.proposed_product_id
                    ),
                    "proposed_quantity": (
                        buyer_decision.proposed_quantity
                    ),
                },
                session_id=session_id,
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

            return None


        # -------------------------------------------------
        # BUYER ACCEPTS COUNTER
        # -------------------------------------------------

        if buyer_decision.decision == "accept":

            log_audit_event(
                "buyer_decision",
                {
                    "decision": "accept",
                    "reasoning": (
                        buyer_decision.reasoning
                    ),
                    "proposed_product_id": (
                        buyer_decision.proposed_product_id
                    ),
                    "proposed_quantity": (
                        buyer_decision.proposed_quantity
                    ),
                },
                session_id=session_id,
            )

            accepted_data = (
                validate_accepted_counter(
                    proposal=proposal,
                    merchant_response=merchant_response,
                    products=products,
                )
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
                "Unexpected Buyer Agent negotiation decision."
            )


    else:

        raise ValueError(
            "Unexpected merchant negotiation response."
        )


    # =====================================================
    # STEP 6
    # Create deterministic signed mandate
    # =====================================================

    print(
        "\n📝 STEP 6 — Creating mandate"
    )

    mandate = create_mandate(
        buyer_id=buyer_id,
        product_id=negotiated_product_id,
        quantity=negotiated_quantity,
        agreed_price=negotiated_price,
    )

    print(
        f"\n✅ Mandate created: "
        f"{mandate.mandate_id}"
    )

    log_audit_event(
        "mandate_created",
        {
            "mandate_id": str(
                mandate.mandate_id
            ),
            "buyer_agent_id": mandate.buyer_agent_id,
            "product_id": mandate.product_id,
            "quantity": mandate.quantity,
            "agreed_price": mandate.agreed_price,
            "currency": mandate.currency,
            "expires_at": (
                mandate.expires_at.isoformat()
                if mandate.expires_at
                else None
            ),
        },
        session_id=session_id,
        mandate_id=mandate.mandate_id,
    )


    # =====================================================
    # STEP 7
    # Validate mandate
    # =====================================================

    print(
        "\n🔐 STEP 7 — Validating mandate"
    )

    log_audit_event(
        "guardrails_started",
        {
            "mandate_id": str(
                mandate.mandate_id
            ),
            "checks": [
                "signature",
                "expiry",
                "replay",
                "stock",
                "budget",
            ],
        },
        session_id=session_id,
        mandate_id=mandate.mandate_id,
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

        log_audit_event(
            "guardrails_failed",
            {
                "mandate_id": str(
                    mandate.mandate_id
                ),
                "reason": reason,
            },
            session_id=session_id,
            mandate_id=mandate.mandate_id,
        )

        return None

    print(
        "\n✅ Mandate validation successful!"
    )

    log_audit_event(
        "guardrails_passed",
        {
            "mandate_id": str(
                mandate.mandate_id
            ),
            "checks": [
                "signature",
                "expiry",
                "replay",
                "stock",
                "budget",
            ],
        },
        session_id=session_id,
        mandate_id=mandate.mandate_id,
    )


    # =====================================================
    # STEP 8
    # Display validated mandate
    # =====================================================

    print(
        "\n📋 STEP 8 — Validated mandate:"
    )

    mandate_json = {
        "mandate_id": str(
            mandate.mandate_id
        ),
        "buyer_agent_id": (
            mandate.buyer_agent_id
        ),
        "merchant_id": (
            mandate.merchant_id
        ),
        "product_id": (
            mandate.product_id
        ),
        "quantity": (
            mandate.quantity
        ),
        "agreed_price": (
            mandate.agreed_price
        ),
        "currency": (
            mandate.currency
        ),
        "status": (
            mandate.status
        ),
        "signature": (
            mandate.signature
        ),
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

    print(
        json.dumps(
            mandate_json,
            indent=2,
            ensure_ascii=False,
        )
    )


    # =====================================================
    # STEP 9
    # Create Razorpay order
    # =====================================================

    print(
        "\n💳 STEP 9 — Creating Razorpay order"
    )

    order_data = (
        create_razorpay_order_for_mandate(
            mandate.mandate_id,
            session_id=session_id,
        )
    )


    # =====================================================
    # STEP 10
    # Human authorization required
    # =====================================================

    log_audit_event(
        "human_authorization_required",
        {
            "mandate_id": str(
                mandate.mandate_id
            ),
            "order_id": order_data["order_id"],
            "amount": order_data["amount"],
            "currency": order_data["currency"],
        },
        session_id=session_id,
        mandate_id=mandate.mandate_id,
    )

    print(
        "\n👤 HUMAN AUTHORIZATION REQUIRED"
    )

    print(
        "The Buyer Agent has completed "
        "its autonomous work."
    )

    print(
        "The customer must now authorize "
        "the Razorpay payment."
    )


    # =====================================================
    # STEP 11
    # Report transaction
    # =====================================================

    print(
        "\n🎉 Buyer Agent transaction flow "
        "reached Razorpay!"
    )

    print(
        "Razorpay Order ID:",
        order_data["order_id"],
    )

    print(
        "Amount:",
        order_data["amount"],
        "paise",
    )

    print(
        "Currency:",
        order_data["currency"],
    )

    print(
        "Mandate ID:",
        order_data["mandate_id"],
    )


    # =====================================================
    # RETURN MANDATE ID
    # =====================================================

    return mandate.mandate_id


# =========================================================
# PUBLIC AGENT RUNNER
# =========================================================

def run_buyer_agent(
    shopping_brief: str,
    session_id: str,
):
    """
    Synchronous entry point used by FastAPI BackgroundTasks.

    The actual Buyer Agent workflow is asynchronous because
    MCP communication uses async I/O.

    asyncio.run() bridges the synchronous FastAPI background
    task and the asynchronous Buyer Agent workflow.
    """

    if not shopping_brief or not shopping_brief.strip():

        raise ValueError(
            "shopping_brief cannot be empty."
        )

    if not session_id:

        raise ValueError(
            "session_id is required."
        )

    print(
        "\n"
        + "=" * 70
    )

    print(
        "🚀 STARTING BUYER AGENT"
    )

    print(
        f"Session ID: {session_id}"
    )

    print(
        "=" * 70
    )

    try:

        mandate_id = asyncio.run(
            main(
                shopping_brief=shopping_brief,
                session_id=session_id,
            )
        )

        print(
            "\n"
            + "=" * 70
        )

        print(
            "✅ BUYER AGENT FINISHED"
        )

        print(
            f"Session ID: {session_id}"
        )

        if mandate_id:

            print(
                f"Mandate ID: {mandate_id}"
            )

        print(
            "=" * 70
        )

        return mandate_id

    except Exception as e:

        log_audit_event(
            "agent_failed",
            {
                "error": str(e),
                "error_type": type(e).__name__,
            },
            session_id=session_id,
        )

        print(
            "\n"
            + "=" * 70
        )

        print(
            "❌ BUYER AGENT FAILED"
        )

        print(
            f"Session ID: {session_id}"
        )

        print(
            f"Error: {e}"
        )

        print(
            "=" * 70
        )

        raise


# =========================================================
# CLI ENTRY POINT
# =========================================================

if __name__ == "__main__":

    # Generate a local session ID for CLI testing.
    # The FastAPI frontend will supply its own session ID.

    import uuid

    cli_session_id = str(
        uuid.uuid4()
    )

    asyncio.run(
        main(
            shopping_brief=(
                "I need 2 fitness gifts for someone, "
                "with a total budget of ₹3,600."
            ),
            session_id=cli_session_id,
        )
    )