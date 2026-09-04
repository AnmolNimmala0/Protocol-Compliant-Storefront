import json
from datetime import datetime, timezone
from typing import Literal

from dotenv import load_dotenv
from mcp import Client
from pydantic import BaseModel, Field

from database import SessionLocal
from models import AuditLog

from agent_session import (
    get_messages,
    add_message,
)


load_dotenv()


MCP_SERVER_URL = "http://127.0.0.1:8001/mcp"


# =========================================================
# AI CLIENT
# =========================================================

from ai_client import generate


# =========================================================
# INTENT SCHEMA
# =========================================================

class RequestIntent(BaseModel):

    intent: Literal[
        "purchase",
        "catalog",
        "question",
        "recommendation",
        "unclear",
    ] = Field(
        description="The user's primary intent."
    )

    reason: str = Field(
        description="Short explanation of why this intent was selected."
    )


# =========================================================
# ANSWER SCHEMA
# =========================================================

class StoreAnswer(BaseModel):

    answer: str = Field(
        description=(
            "Natural language answer to the customer's "
            "question using only the merchant catalog."
        )
    )


# =========================================================
# CONVERSATION HISTORY
# =========================================================

def build_conversation_context(session_id: str) -> str:

    messages = get_messages(session_id)

    if not messages:
        return "No previous conversation."

    lines = []

    for message in messages:
        role = message["role"].upper()
        content = message["content"]

        lines.append(
            f"{role}: {content}"
        )

    return "\n".join(lines)


# =========================================================
# AUDIT LOGGING
# =========================================================

def log_event(
    session_id: str,
    event_type: str,
    detail: dict,
):

    db = SessionLocal()

    try:

        event = AuditLog(
            session_id=session_id,
            mandate_id=None,
            event_type=event_type,
            detail=detail,
            created_at=datetime.now(timezone.utc),
        )

        db.add(event)
        db.commit()

    finally:

        db.close()


# =========================================================
# CLASSIFY USER REQUEST
# =========================================================

def classify_request(
    shopping_brief: str,
    conversation_context: str,
) -> RequestIntent:

    prompt = f"""
You are the intent router for an agentic commerce system.

The system is an online store with an autonomous Buyer Agent.

Your job is to understand what the customer is trying to do.

You have access to the previous conversation because customers
may refer to products or information from earlier messages.

PREVIOUS CONVERSATION:
{conversation_context}

CURRENT CUSTOMER MESSAGE:
{shopping_brief}

Use BOTH the previous conversation and the current message
to understand the customer's intent.

Classify the current message into exactly ONE intent:

1. purchase

Use "purchase" when the customer is asking the system
to actually obtain, buy, order, get, or take a product.

A purchase can refer to something discussed earlier.

For example:

Previous:
USER: What keyboards do you sell?
ASSISTANT: We sell the Keychron K2.

Current:
USER: Okay, buy one.

This is a purchase.

Other examples:

"I need a monitor under ₹20,000."

"Buy me two yoga mats."

"I want to get a keyboard."

"Can you order the Samsung monitor?"

"I'll take the Logitech mouse."

"I'll take that one."

"Yes, buy it."

"Get me two of those."

2. catalog

Use "catalog" when the customer wants to know what
the store offers or wants to browse products.

Examples:

"What do you sell?"

"What products do you have?"

"Show me your monitors."

"Do you have keyboards?"

"What categories are available?"

3. question

Use "question" when the customer is asking about a product,
price, stock, specifications, availability, or another factual
aspect of the store/catalog, without clearly asking to purchase.

Examples:

"How much is the Samsung monitor?"

"Do you have the monitor in stock?"

"How many yoga mats are available?"

"What is the price of the keyboard?"

"Is it in stock?"

"Which one costs less?"

The last two examples may refer to a product from the
previous conversation.

4. recommendation

Use "recommendation" when the customer wants advice about
which product they should choose.

Examples:

"Which monitor would you recommend?"

"What's the best keyboard under ₹10,000?"

"What would be good for a home office?"

"Help me choose a monitor."

5. unclear

Use "unclear" when the request cannot reasonably be understood,
even after considering the previous conversation.

IMPORTANT:

- Use conversation history to resolve references such as
  "it", "that one", "this", "those", "the cheaper one",
  "the first one", or "buy one".
- A customer agreeing to purchase something previously discussed
  is a purchase intent.
- Information questions must NOT become purchases.
- Do NOT create a financial transaction for catalog/question/
  recommendation requests.
- A purchase should only happen when the customer clearly
  expresses shopping or purchasing intent, either directly
  or through a clear continuation of the conversation.
- Do not invent conversation history.

Return ONLY the structured intent.
"""

    response_text = generate(
        contents=prompt,
        response_schema=RequestIntent,
    )

    return RequestIntent.model_validate_json(
        response_text
    )


# =========================================================
# MCP: GET MERCHANT CATALOG
# =========================================================

async def get_catalog():

    print(
        "\n🔌 Router connecting to Merchant MCP..."
    )

    async with Client(MCP_SERVER_URL) as mcp_client:

        tools_result = await mcp_client.list_tools()

        print("\n🛠️ Router discovered MCP tools:")

        for tool in tools_result.tools:

            print(
                f"  - {tool.name}"
            )

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
# ANSWER INFORMATION REQUEST
# =========================================================

def answer_from_catalog(
    shopping_brief: str,
    conversation_context: str,
    products,
) -> StoreAnswer:

    catalog_text = json.dumps(
        products,
        indent=2,
        ensure_ascii=False,
    )

    prompt = f"""
You are the shopping assistant for an online store.

The merchant catalog below is the ONLY source of truth
for product information.

The customer is having a multi-turn conversation with you.

PREVIOUS CONVERSATION:
{conversation_context}

CURRENT CUSTOMER MESSAGE:
{shopping_brief}

MERCHANT CATALOG:
{catalog_text}

Answer the customer's CURRENT message naturally and
conversationally.

Use the previous conversation only to understand references
and context.

Rules:

1. Only mention products that exist in the catalog.

2. Never invent:
   - products
   - prices
   - stock
   - specifications
   - categories

3. Prices in the catalog are stored in paise.
   Convert them to Indian rupees when answering.

4. If the customer asks what the store sells,
   summarize the available products and categories.

5. If the customer asks about a specific product,
   answer using its actual catalog information.

6. If the customer asks for recommendations,
   recommend products that genuinely match their request.

7. If the customer refers to something using words such as
   "it", "that one", "this", "those", "the cheaper one",
   or similar language, resolve the reference using the
   previous conversation.

8. If several products are relevant, mention the most relevant
   few rather than dumping unnecessary information.

9. Do NOT ask the customer to use a special prompt format.

10. Do NOT initiate a purchase.

11. Do NOT claim that an order has been created.

12. Keep the response concise but useful.

13. If the requested product does not exist, clearly say that
    it was not found and, where useful, mention a similar
    available product.

14. If the customer asks whether a product is available,
    use the catalog's stock information.

15. If the customer asks a follow-up question about a product
    mentioned earlier, answer the follow-up directly instead
    of asking them to repeat the product name.

Return ONLY the structured answer.
"""

    response_text = generate(
        contents=prompt,
        response_schema=StoreAnswer,
    )

    return StoreAnswer.model_validate_json(
        response_text
    )


# =========================================================
# HANDLE NON-PURCHASE REQUEST
# =========================================================

async def handle_information_request(
    shopping_brief: str,
    session_id: str,
    intent: RequestIntent,
    conversation_context: str,
):

    log_event(
        session_id,
        "shopping_request_received",
        {
            "shopping_brief": shopping_brief
        },
    )

    log_event(
        session_id,
        "intent_classified",
        {
            "intent": intent.intent,
            "reason": intent.reason,
        },
    )

    # -----------------------------------------------------
    # UNCLEAR
    # -----------------------------------------------------

    if intent.intent == "unclear":

        answer = (
            "I can help you browse the store, find products, "
            "compare options, or purchase something for you. "
            "What are you looking for?"
        )

        log_event(
            session_id,
            "assistant_response",
            {
                "answer": answer,
                "intent": "unclear",
            },
        )

        add_message(
            session_id,
            "assistant",
            answer,
        )

        return answer

    # -----------------------------------------------------
    # CATALOG / QUESTION / RECOMMENDATION
    # -----------------------------------------------------

    log_event(
        session_id,
        "catalog_discovery_started",
        {
            "source": "merchant_mcp"
        },
    )

    products = await get_catalog()

    log_event(
        session_id,
        "catalog_discovered",
        {
            "source": "MCP",
            "product_count": len(products),
        },
    )

    answer = answer_from_catalog(
        shopping_brief=shopping_brief,
        conversation_context=conversation_context,
        products=products,
    )

    log_event(
        session_id,
        "assistant_response",
        {
            "answer": answer.answer,
            "intent": intent.intent,
        },
    )

    add_message(
        session_id,
        "assistant",
        answer.answer,
    )

    print(
        "\n💬 Assistant response:"
    )

    print(
        answer.answer
    )

    return answer.answer


# =========================================================
# MAIN ROUTER
# =========================================================

async def route_request(
    shopping_brief: str,
    session_id: str,
):

    print(
        "\n🧭 Classifying customer request..."
    )

    # -----------------------------------------------------
    # SAVE CURRENT USER MESSAGE
    # -----------------------------------------------------

    add_message(
        session_id,
        "user",
        shopping_brief,
    )

    # -----------------------------------------------------
    # BUILD CONTEXT
    #
    # IMPORTANT:
    # Build this AFTER adding the current message so the
    # purchase agent can later receive the complete context.
    # -----------------------------------------------------

    conversation_context = build_conversation_context(
        session_id
    )

    print(
        "\n🧠 Conversation context:"
    )

    print(
        conversation_context
    )

    # -----------------------------------------------------
    # CLASSIFY
    # -----------------------------------------------------

    intent = classify_request(
        shopping_brief=shopping_brief,
        conversation_context=conversation_context,
    )

    print(
        f"\n🎯 Intent: {intent.intent}"
    )

    print(
        f"Reason: {intent.reason}"
    )

    # -----------------------------------------------------
    # PURCHASE
    # -----------------------------------------------------

    if intent.intent == "purchase":

        return {
            "intent": "purchase",
            "answer": None,
            "conversation_context": conversation_context,
        }

    # -----------------------------------------------------
    # INFORMATION REQUEST
    # -----------------------------------------------------

    answer = await handle_information_request(
        shopping_brief=shopping_brief,
        session_id=session_id,
        intent=intent,
        conversation_context=conversation_context,
    )

    return {
        "intent": intent.intent,
        "answer": answer,
        "conversation_context": conversation_context,
    }