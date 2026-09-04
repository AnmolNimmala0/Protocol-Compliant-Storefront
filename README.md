# Agentic Shop

**Making a merchant transactable by AI buyers**

Agentic Shop turns a normal merchant,into a system that an AI buyer can discover, negotiate with, pay, and transact with — end to end.

> The model can reason. The software controls the money.

Built for the **Razorpay AI Growth & Agentic Commerce track**: making a merchant sellable to AI buyers.

---

## Table of Contents

- [The Problem](#the-problem)
- [What We Built](#what-we-built)
- [A Real Interaction](#a-real-interaction)
- [Architecture](#architecture)
- [Agent-to-Agent Negotiation](#agent-to-agent-negotiation)
- [Why MCP Instead of a Prompt-Embedded Catalog?](#why-mcp-instead-of-a-prompt-embedded-catalog)
- [The Financial Boundary](#the-financial-boundary)
- [Audit Trail](#audit-trail)
- [AI Reliability](#ai-reliability)
- [Multi-Turn Agent State](#multi-turn-agent-state)
- [Engineering Decisions](#engineering-decisions)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Run Locally](#run-locally)
- [Project Status](#project-status)

---

## The Problem

Most commerce software assumes the buyer is a person.

A person can open a store, understand the catalog, choose a product, negotiate a price, pay, and receive an order. An AI agent can understand the same request — but understanding the request is only the easy part. The hard part is making the **merchant itself** capable of transacting with that agent.

The next interface to commerce may not be a website. It may be an agent. Instead of manually working through:

```
Browse → Select → Negotiate → Checkout → Pay → Order
```

a user could simply tell an agent:

> "I need two yoga mats. I'd like to stay around ₹3,600. Get me the best deal."

For that to work, the merchant needs more than a product page. It needs a machine-readable interface through which an AI buyer can:

- discover what the merchant sells
- retrieve product information
- check availability
- understand merchant terms
- submit a purchase proposal
- negotiate
- receive an agreed transaction
- complete payment
- create an actual merchant order

Agentic Shop is a working prototype of that complete loop.

---

## What We Built

FitStore is a conventional ecommerce merchant with an additional interface for AI buyers. We built **both sides** of the transaction.

### The Buyer Side

The **Buyer Agent** understands a natural-language shopping request, discovers the merchant's catalog, selects products, reasons about quantity and budget, and makes a structured proposal.

### The Merchant Side

The merchant exposes its capabilities through **MCP**. A **Merchant Agent** receives the buyer's proposal and can accept it, counter it, or decline it.

That means the merchant isn't just being queried by an AI — **the merchant is participating in the transaction.**

```
                 AI Buyer
                    │
              purchase proposal
                    │
                    ▼
             Merchant Agent
                    │
          ┌─────────┼─────────┐
          │         │         │
        ACCEPT    COUNTER   DECLINE
          │         │
          └────┬────┘
               ▼
        Agreed transaction
               │
               ▼
            Payment
               │
               ▼
         Merchant Order
```

---

## A Real Interaction

A user can have a normal conversation with the shopping agent:

| Turn | Actor | Action |
|---|---|---|
| 1 | User | "What products do you sell?" |
| 2 | Agent | Discovers the catalog through MCP |
| 3 | User | "Do you have yoga mats?" |
| 4 | Agent | Checks the merchant catalog |
| 5 | User | "Can I buy two?" |
| 6 | Agent | Resolves "two" from the conversation |
| 7 | User | "I'd like to stay around ₹3,600. Can you get me the best deal?" |
| 8 | Agent | Creates a purchase proposal |
| 9 | Merchant Agent | Evaluates the proposal |
| 10 | Merchant Agent | Accepts or counters |
| 11 | Buyer Agent | Accepts or declines the response |

Once the commercial terms are agreed, the system moves out of the probabilistic part of the stack and into **deterministic transaction execution**:

```
Agreed terms
    ↓
Purchase Mandate
    ↓
Guardrails
    ↓
Razorpay Test Order
    ↓
Human Authorization
    ↓
Webhook Verification
    ↓
FitStore Order
    ↓
Stock + Audit Trail
```

The important distinction: the final result is **not** an AI-generated sentence saying "your order is complete." It is an actual order created in the merchant system, after the payment has been verified.

---

## Architecture

The system has three distinct layers.

### 1. Reasoning

The LLM is used where the problem is inherently ambiguous:

- intent classification
- conversation understanding
- product selection
- purchase planning
- negotiation
- resolving references across turns

We do not ask the model to own financial state.

### 2. Merchant Interface

MCP gives the buyer a stable, machine-readable interface to the merchant. FitStore exposes capabilities such as:

```
list_products
get_product
check_availability
get_terms
negotiate_proposal
```

The Buyer Agent therefore does not need to know how the merchant's database or application is implemented:

```
Buyer Agent
     ↓
    MCP
     ↓
Merchant capabilities
```

### 3. Transaction Execution

Once the agents agree, deterministic application code takes over. It handles:

- purchase mandates
- transaction boundaries
- price and quantity validation
- payment order creation
- webhook signature verification
- payment state
- order creation
- stock updates
- audit logging

This separation is deliberate: **AI decides what it wants to do. The application decides what it is allowed to do.**

```
User
  ↓
AI Buyer
  ↓
Merchant MCP
  ↓
Merchant Agent
  ↓
Negotiation
  ↓
Purchase Mandate
  ↓
Deterministic Guardrails
  ↓
Razorpay
  ↓
Merchant Order
```

---

## Agent-to-Agent Negotiation

Negotiation is not simulated in the UI — it is part of the application flow.

The Buyer Agent produces a structured proposal. The Merchant Agent evaluates it against merchant-side information and policy. The merchant can:

- **ACCEPT**
- **COUNTER**
- **DECLINE**

The Buyer Agent then evaluates the merchant's response.

**Example:**

```
Buyer
  Yoga Mat × 2
  Target budget: ₹3,600
        ↓
Merchant
  Normal total: ₹3,998
  Counter: 10% bundle discount
        ↓
Buyer
  Accept counter
```

The exchange is persisted in the execution trace, so a reviewer can inspect what happened instead of relying on a final chat message.

---

## Why MCP Instead of a Prompt-Embedded Catalog?

A static catalog in a prompt is enough for a demo chatbot. It is not a useful merchant interface.

The merchant needs to expose **capabilities**, not just text. With MCP, the buyer can ask the merchant for current information and invoke explicit tools. That gives us a clean boundary between:

- **How the buyer reasons**, and
- **What the merchant can actually do**

This is the part that makes the system extensible toward a world where many merchants expose agent-readable interfaces.

---

## The Financial Boundary

The most important architectural decision is what we **didn't** let the model do.

We do not take an LLM response and directly charge a payment method. Instead:

```
LLM
 ↓
structured proposal / decision
 ↓
application validation
 ↓
purchase mandate
 ↓
deterministic guardrails
 ↓
Razorpay order
 ↓
human authorization
 ↓
webhook verification
 ↓
order execution
```

The model is useful because commerce requests are messy. Money movement is different — the application owns the final state transition.

---

## Audit Trail

Every important transaction step is recorded. A purchase produces a trace similar to:

```
Shopping request received
        ↓
Intent classified
        ↓
Catalog discovery
        ↓
Buyer product selected
        ↓
Merchant negotiation started
        ↓
Merchant negotiation response
        ↓
Buyer decision
        ↓
Mandate created
        ↓
Guardrails passed
        ↓
Razorpay order created
        ↓
Payment captured
        ↓
Mandate executed
        ↓
Order created
```

The UI exposes these events and makes the negotiation exchange inspectable. This matters because the requirement for an agentic payment system is not simply:

> "Can the agent pay?"

It is:

> "Can we understand exactly what the agent did before money moved?"

---

## AI Reliability

The AI layer is designed around the fact that model providers fail. During development, Gemini returned temporary `503` high-demand errors.

Rather than coupling the entire transaction pipeline to one provider, AI calls are centralized in `ai_client.py`:

```
Gemini
  ↓
retry transient failures
  ↓
Groq fallback
```

Structured outputs are validated with **Pydantic** before they enter the application. The fallback protects the reasoning layer — it does not bypass the deterministic financial controls.

---

## Multi-Turn Agent State

Shopping conversations are rarely one-shot. A user may say:

- "Do you have yoga mats?"
- "Can I buy two?"
- "Actually, I'd like to stay under ₹3,600."

The agent needs to understand that all three messages belong to the same shopping context. Agentic Shop keeps session state and conversation history so the router and Buyer Agent can resolve references such as:

- "that one"
- "two of those"
- "the cheaper one"
- "yes, buy it"

This makes the interface behave like an actual shopping agent, rather than a sequence of independent prompts.

---

## Engineering Decisions

**Reasoning is probabilistic; transaction state is not.**
LLMs are excellent at interpreting intent and negotiating ambiguous requests. They are not the right place to maintain authoritative financial state — so we keep those concerns separate.

**Merchant capabilities are explicit.**
The Buyer Agent does not get privileged access to FitStore's database. It interacts only through the merchant's exposed capabilities.

**Structured model output.**
Agent decisions are represented as structured data and validated before downstream code uses them.

**Centralized model access.**
All production model calls go through one AI client, giving the system a single place for retries, provider fallback, and structured-output handling.

**Human authorization.**
The AI can prepare and negotiate a transaction, but the payment still crosses an explicit human authorization step in the demo.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js, React, TypeScript |
| Backend | Python, FastAPI, Pydantic |
| Database | PostgreSQL |
| AI | Gemini + Groq fallback |
| Agent interface | Model Context Protocol (MCP) |
| Payments | Razorpay Test Mode |
| Webhooks | Razorpay webhook verification |
| Local tunneling | ngrok |

---

## Repository Structure

```
agentic-shop/
├── backend/
│   ├── main.py
│   ├── agent_router.py
│   ├── agent_session.py
│   ├── buyer_agent.py
│   ├── merchant_mcp.py
│   ├── ai_client.py
│   └── ...
├── frontend/
│   └── app/
│       └── page.tsx
├── docs/
│   └── architecture.png
├── README.md
└── .env.example
```

---

## Run Locally

### Requirements

- Python 3.11+
- Node.js
- PostgreSQL
- Gemini API key
- Groq API key
- Razorpay Test Mode credentials
- ngrok (for local webhook delivery)

### Environment

```bash
cp .env.example .env
```

Add your credentials to `.env`. **Never commit `.env`.**

### Backend

Install dependencies:

```bash
cd backend
pip install -r requirements.txt
```

Start the merchant MCP server:

```bash
python merchant_mcp.py
```

Start FastAPI in another terminal:

```bash
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Razorpay Webhook

For local development:

```bash
ngrok http 8000
```

Configure the Razorpay Test Mode webhook as:

```
https://<YOUR_NGROK_DOMAIN>/webhooks/razorpay
```

---

## Project Status

**Working end to end in Razorpay Test Mode.**

The current prototype demonstrates:

- [x] AI-powered conversational shopping
- [x] Multi-turn context
- [x] Merchant catalog discovery through MCP
- [x] Buyer Agent
- [x] Merchant Agent
- [x] Agent-to-agent negotiation
- [x] Purchase mandates
- [x] Deterministic guardrails
- [x] Razorpay payment authorization
- [x] Webhook verification
- [x] Merchant order creation
- [x] Stock updates
- [x] Audit trail
- [x] Gemini retry + Groq fallback