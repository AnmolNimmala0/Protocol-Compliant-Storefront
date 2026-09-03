"use client";

import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    Razorpay: any;
  }
}

const API_BASE = "http://127.0.0.1:8000";

type EventItem = {
  id: number;
  session_id: string;
  mandate_id: string | null;
  event_type: string;
  detail: any;
  created_at: string;
};

type SessionState = {
  status: string;
  mandate_id: string | null;
};

const PRESETS = [
  "I need 2 fitness gifts for someone, with a total budget of ₹3,600.",
  "I need a workstation setup under ₹35,000.",
  "I need chargers for my devices under ₹5,000.",
];

function formatEvent(event: EventItem) {
  const names: Record<string, string> = {
    shopping_request_received: "Shopping request received",
    catalog_discovery_started: "Catalog discovery started",
    catalog_discovered: "Catalog discovered via MCP",
    buyer_product_selected: "Buyer selected product",
    merchant_negotiation_started: "Merchant negotiation started",
    merchant_negotiation_response: "Merchant responded",
    buyer_decision: "Buyer made decision",
    mandate_created: "Mandate created and signed",
    guardrails_started: "Guardrails started",
    guardrails_passed: "Guardrails passed",
    guardrails_failed: "Guardrails failed",
    razorpay_order_creation_started: "Creating Razorpay order",
    razorpay_order_created: "Razorpay order created",
    human_authorization_required: "Human authorization required",
    payment_captured: "Payment captured",
    payment_failed: "Payment failed",
  };

  return names[event.event_type] || event.event_type;
}

function eventIcon(eventType: string) {
  if (eventType === "merchant_negotiation_started") return "⇄";
  if (eventType === "merchant_negotiation_response") return "⇄";
  if (eventType === "human_authorization_required") return "🔐";
  if (eventType === "payment_captured") return "✓";
  if (eventType === "payment_failed") return "!";
  if (eventType.includes("failed")) return "!";
  return "✓";
}

function formatRupees(paise: number | undefined) {
  if (paise === undefined || paise === null) return "";
  return `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export default function Home() {
  const [brief, setBrief] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [session, setSession] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(false);
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  const latestEvent = events[events.length - 1];

  const startShopping = async () => {
    if (!brief.trim() || loading) return;

    try {
      setLoading(true);
      setError(null);
      setEvents([]);
      setSession(null);
      setSessionId(null);

      const response = await fetch(`${API_BASE}/agent/shop`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          shopping_brief: brief.trim(),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to start shopping agent");
      }

      setSessionId(data.session_id);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start shopping agent"
      );
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!sessionId) return;

    const poll = async () => {
      try {
        const [eventsResponse, sessionResponse] = await Promise.all([
          fetch(`${API_BASE}/agent/sessions/${sessionId}/events`),
          fetch(`${API_BASE}/agent/sessions/${sessionId}`),
        ]);

        if (!eventsResponse.ok || !sessionResponse.ok) {
          throw new Error("Failed to fetch agent session");
        }

        const eventsData = await eventsResponse.json();
        const sessionData = await sessionResponse.json();

        setEvents(eventsData);
        setSession(sessionData);

        if (
          sessionData.status === "awaiting_payment" ||
          sessionData.status === "completed" ||
          sessionData.status === "failed" ||
          sessionData.status === "payment_failed"
        ) {
          setLoading(false);
        }

        if (
          sessionData.status === "completed" ||
          sessionData.status === "failed" ||
          sessionData.status === "payment_failed"
        ) {
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
          }
        }
      } catch (err) {
        console.error(err);
      }
    };

    poll();

    pollingRef.current = setInterval(poll, 1000);

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, [sessionId]);

  const startPayment = async () => {
    if (!session?.mandate_id || paymentLoading) return;

    try {
      setPaymentLoading(true);
      setError(null);

      const response = await fetch(
        `${API_BASE}/mandates/${session.mandate_id}/order`
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to retrieve Razorpay order");
      }

      const script = document.createElement("script");
      script.src = "https://checkout.razorpay.com/v1/checkout.js";

      script.onload = () => {
        const options = {
          key: data.key_id,
          amount: data.amount,
          currency: data.currency,
          name: "Agentic Shop",
          description: "Agentic commerce purchase",
          order_id: data.order_id,

          handler: function (response: any) {
            console.log("Payment authorized:", response);
            setPaymentLoading(false);
          },

          modal: {
            ondismiss: function () {
              setPaymentLoading(false);
            },
          },

          theme: {
            color: "#111111",
          },
        };

        const razorpay = new window.Razorpay(options);
        razorpay.open();
      };

      script.onerror = () => {
        setPaymentLoading(false);
        setError("Failed to load Razorpay Checkout");
      };

      document.body.appendChild(script);
    } catch (err) {
      setPaymentLoading(false);
      setError(
        err instanceof Error ? err.message : "Failed to start payment"
      );
    }
  };

  const negotiationEvent = events.find(
    (event) => event.event_type === "merchant_negotiation_response"
  );

  const authorizationEvent = events.find(
    (event) => event.event_type === "human_authorization_required"
  );

  const isAwaitingPayment = session?.status === "awaiting_payment";
  const isCompleted = session?.status === "completed";

  return (
    <main className="min-h-screen bg-zinc-950 text-white">
      <div className="mx-auto flex min-h-screen max-w-[1500px] flex-col">
        {/* Header */}
        <header className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              Agentic Shop
            </h1>
            <p className="text-xs text-zinc-500">
              Autonomous commerce with human authorization
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs text-zinc-400">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            Agent system online
          </div>
        </header>

        <div className="grid flex-1 lg:grid-cols-[1fr_380px]">
          {/* Main chat */}
          <section className="flex flex-col border-r border-zinc-800">
            <div className="flex-1 px-6 py-10 lg:px-16">
              {!sessionId ? (
                <div className="mx-auto flex max-w-3xl flex-col justify-center pt-20">
                  <div className="mb-10 text-center">
                    <div className="mb-4 text-sm text-zinc-500">
                      BUYER AGENT
                    </div>

                    <h2 className="text-4xl font-semibold tracking-tight">
                      What can I buy for you?
                    </h2>

                    <p className="mt-4 text-zinc-500">
                      Tell the Buyer Agent what you need. It will discover
                      products, negotiate with merchants, enforce your
                      constraints, and prepare the purchase.
                    </p>
                  </div>

                  <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-3 shadow-2xl">
                    <textarea
                      value={brief}
                      onChange={(e) => setBrief(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          startShopping();
                        }
                      }}
                      placeholder="e.g. I need 2 fitness gifts under ₹3,600..."
                      className="min-h-28 w-full resize-none bg-transparent p-3 text-sm outline-none placeholder:text-zinc-600"
                    />

                    <div className="flex items-center justify-between border-t border-zinc-800 pt-3">
                      <span className="px-3 text-xs text-zinc-600">
                        Enter to send
                      </span>

                      <button
                        onClick={startShopping}
                        disabled={!brief.trim() || loading}
                        className="rounded-xl bg-white px-5 py-2.5 text-sm font-medium text-black transition hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {loading ? "Agent working..." : "Start shopping"}
                      </button>
                    </div>
                  </div>

                  <div className="mt-5 flex flex-wrap justify-center gap-2">
                    {PRESETS.map((preset) => (
                      <button
                        key={preset}
                        onClick={() => setBrief(preset)}
                        className="rounded-full border border-zinc-800 px-3 py-2 text-xs text-zinc-400 transition hover:border-zinc-600 hover:text-white"
                      >
                        {preset}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="mx-auto max-w-3xl">
                  {/* User message */}
                  <div className="mb-10 flex justify-end">
                    <div className="max-w-xl rounded-2xl bg-zinc-800 px-5 py-4 text-sm">
                      {brief}
                    </div>
                  </div>

                  {/* Agent response */}
                  <div className="flex gap-4">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-sm font-bold text-black">
                      A
                    </div>

                    <div className="flex-1">
                      <div className="mb-2 text-sm font-medium">
                        Buyer Agent
                      </div>

                      {loading && !latestEvent && (
                        <div className="text-sm text-zinc-500">
                          Understanding your request...
                        </div>
                      )}

                      {latestEvent && (
                        <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
                          <p className="text-sm text-zinc-300">
                            {formatEvent(latestEvent)}
                          </p>

                          {latestEvent.event_type ===
                            "buyer_product_selected" && (
                              <div className="mt-4 rounded-xl bg-zinc-950 p-4">
                                <div className="font-medium">
                                  {latestEvent.detail.product_name}
                                </div>
                                <div className="mt-1 text-sm text-zinc-500">
                                  Quantity: {latestEvent.detail.quantity}
                                </div>
                              </div>
                            )}

                          {negotiationEvent && (
                            <div className="mt-4 rounded-xl border border-zinc-700 bg-zinc-950 p-4">
                              <div className="mb-3 flex items-center gap-2 text-xs font-medium text-zinc-400">
                                <span>⇄</span>
                                AGENT-TO-AGENT NEGOTIATION
                              </div>

                              <div className="space-y-3 text-sm">
                                <div>
                                  <span className="text-zinc-600">
                                    Merchant:
                                  </span>{" "}
                                  {negotiationEvent.detail.response?.counter
                                    ?.message ||
                                    negotiationEvent.detail.response?.reason}
                                </div>

                                {negotiationEvent.detail.response?.counter && (
                                  <div className="rounded-lg bg-zinc-900 p-3">
                                    <div className="text-xs text-zinc-500">
                                      Counter offer
                                    </div>
                                    <div className="mt-1 text-lg font-semibold">
                                      {formatRupees(
                                        negotiationEvent.detail.response
                                          .counter.price
                                      )}
                                    </div>
                                    <div className="text-xs text-zinc-500">
                                      {
                                        negotiationEvent.detail.response
                                          .counter.discount_pct
                                      }
                                      % merchant discount
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}

                          {isAwaitingPayment && authorizationEvent && (
                            <div className="mt-5 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-5">
                              <div className="text-xs font-semibold tracking-wide text-amber-400">
                                🔐 HUMAN AUTHORIZATION REQUIRED
                              </div>

                              <div className="mt-2 text-sm text-zinc-400">
                                The agents have completed the purchase decision.
                                You must authorize the financial transaction.
                              </div>

                              <div className="mt-5 flex items-end justify-between">
                                <div>
                                  <div className="text-xs text-zinc-600">
                                    Amount
                                  </div>
                                  <div className="text-2xl font-semibold">
                                    {formatRupees(
                                      authorizationEvent.detail.amount
                                    )}
                                  </div>
                                </div>

                                <button
                                  onClick={startPayment}
                                  disabled={paymentLoading}
                                  className="rounded-xl bg-white px-5 py-3 text-sm font-medium text-black hover:bg-zinc-200 disabled:opacity-50"
                                >
                                  {paymentLoading
                                    ? "Opening Checkout..."
                                    : "Review & Pay"}
                                </button>
                              </div>
                            </div>
                          )}

                          {isCompleted && (
                            <div className="mt-5 rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-5">
                              <div className="text-sm font-semibold text-emerald-400">
                                ✓ Purchase completed
                              </div>
                              <p className="mt-2 text-sm text-zinc-400">
                                Payment was captured and the mandate was
                                executed successfully.
                              </p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Execution trace */}
          <aside className="bg-zinc-950">
            <div className="sticky top-0">
              <div className="border-b border-zinc-800 px-5 py-4">
                <div className="text-xs font-semibold tracking-wider text-zinc-500">
                  EXECUTION TRACE
                </div>
                <div className="mt-1 text-sm text-zinc-300">
                  Live agent activity
                </div>
              </div>

              <div className="max-h-[calc(100vh-100px)] overflow-y-auto p-5">
                {!sessionId ? (
                  <div className="py-10 text-center text-xs text-zinc-600">
                    Agent activity will appear here.
                  </div>
                ) : (
                  <div className="space-y-1">
                    {events.map((event) => {
                      const isNegotiation =
                        event.event_type ===
                        "merchant_negotiation_started" ||
                        event.event_type ===
                        "merchant_negotiation_response";

                      const isImportant =
                        event.event_type ===
                        "human_authorization_required" ||
                        event.event_type === "payment_captured";

                      return (
                        <div
                          key={event.id}
                          className={`rounded-xl p-3 ${isImportant
                              ? "bg-zinc-900"
                              : "hover:bg-zinc-900/50"
                            }`}
                        >
                          <div className="flex gap-3">
                            <div
                              className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs ${isNegotiation
                                  ? "bg-purple-500/10 text-purple-400"
                                  : isImportant
                                    ? "bg-amber-500/10 text-amber-400"
                                    : "bg-emerald-500/10 text-emerald-400"
                                }`}
                            >
                              {eventIcon(event.event_type)}
                            </div>

                            <div className="min-w-0 flex-1">
                              <div className="text-xs text-zinc-300">
                                {formatEvent(event)}
                              </div>

                              <div className="mt-1 text-[10px] text-zinc-600">
                                {new Date(
                                  event.created_at
                                ).toLocaleTimeString()}
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {sessionId && (
                  <div className="mt-6 border-t border-zinc-800 pt-5">
                    <div className="text-[10px] tracking-wider text-zinc-600">
                      SESSION
                    </div>

                    <div className="mt-1 break-all font-mono text-[10px] text-zinc-500">
                      {sessionId}
                    </div>

                    {session?.mandate_id && (
                      <>
                        <div className="mt-4 text-[10px] tracking-wider text-zinc-600">
                          MANDATE
                        </div>

                        <div className="mt-1 break-all font-mono text-[10px] text-zinc-500">
                          {session.mandate_id}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </aside>
        </div>

        {error && (
          <div className="fixed bottom-5 left-1/2 -translate-x-1/2 rounded-xl border border-red-500/30 bg-red-950 px-5 py-3 text-sm text-red-300 shadow-2xl">
            {error}
          </div>
        )}
      </div>
    </main>
  );
}