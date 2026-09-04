"use client";

import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    Razorpay: any;
  }
}

const API_BASE = "http://127.0.0.1:8000";

type Product = {
  id: number;
  name: string;
  category?: string | null;
  price: number;
  stock: number;
  description?: string | null;
  max_discount_pct?: number;
};

type Order = {
  id: number;
  order_number: string;
  buyer_id?: string | null;
  mandate_id?: string | null;
  product_id: number;
  quantity: number;
  amount: number;
  currency: string;
  razorpay_order_id?: string | null;
  razorpay_payment_id?: string | null;
  status: string;
  created_at: string;
};

type EventItem = {
  id: number;
  session_id: string;
  mandate_id: string | null;
  event_type: string;
  detail: any;
  created_at: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type SessionState = {
  status: string;
  mandate_id: string | null;
  answer: string | null;
  messages: ChatMessage[];
};

const PRESETS = [
  "I need 2 fitness gifts for someone, with a total budget of ₹3,600.",
  "I need a workstation setup under ₹35,000.",
  "I need chargers for my devices under ₹5,000.",
];

function formatRupees(paise: number | undefined | null) {
  if (paise === undefined || paise === null) return "";
  return `₹${(paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

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
    merchant_order_confirmed: "FitStore order confirmed",
  };

  return names[event.event_type] || event.event_type;
}

function eventIcon(eventType: string) {
  if (
    eventType === "merchant_negotiation_started" ||
    eventType === "merchant_negotiation_response"
  )
    return "⇄";
  if (eventType === "human_authorization_required") return "🔐";
  if (eventType === "payment_captured") return "✓";
  if (eventType === "payment_failed" || eventType.includes("failed")) return "!";
  return "✓";
}

function categoryEmoji(category?: string | null) {
  const value = (category || "").toLowerCase();
  if (value.includes("yoga")) return "🧘";
  if (value.includes("fitness")) return "🏋️";
  if (value.includes("desk") || value.includes("work")) return "💻";
  if (value.includes("audio")) return "🎧";
  if (value.includes("mobile") || value.includes("charger")) return "🔌";
  return "📦";
}

function statusLabel(status: string) {
  return status
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function Home() {
  const [products, setProducts] = useState<Product[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [storeLoading, setStoreLoading] = useState(true);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [storeError, setStoreError] = useState<string | null>(null);

  const [aiOpen, setAiOpen] = useState(false);
  const [brief, setBrief] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [session, setSession] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(false);
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollingVersion, setPollingVersion] = useState(0);

  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  const latestEvent = events[events.length - 1];

  const loadStore = async () => {
    try {
      setStoreLoading(true);
      setStoreError(null);

      const response = await fetch(`${API_BASE}/products`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to load products");
      }

      setProducts(Array.isArray(data) ? data : data.products || []);
    } catch (err) {
      setStoreError(
        err instanceof Error ? err.message : "Failed to load FitStore"
      );
    } finally {
      setStoreLoading(false);
    }
  };

  const loadOrders = async () => {
    try {
      setOrdersLoading(true);
      const response = await fetch(`${API_BASE}/orders`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to load orders");
      }

      setOrders(Array.isArray(data) ? data : data.orders || []);
    } catch (err) {
      console.error(err);
    } finally {
      setOrdersLoading(false);
    }
  };

  useEffect(() => {
    loadStore();
    loadOrders();
  }, []);

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
          sessionData.status === "answered" ||
          sessionData.status === "completed" ||
          sessionData.status === "failed" ||
          sessionData.status === "payment_failed"
        ) {
          setLoading(false);
        }

        if (
          sessionData.status === "answered" ||
          sessionData.status === "completed" ||
          sessionData.status === "failed" ||
          sessionData.status === "payment_failed"
        ) {
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }

          if (sessionData.status === "completed") {
            await loadOrders();
            await loadStore();
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
        pollingRef.current = null;
      }
    };
  }, [sessionId, pollingVersion]);

  const openAIShop = () => {
    setAiOpen(true);
    setError(null);
  };

  const closeAIShop = () => {
    if (loading || paymentLoading) return;
    setAiOpen(false);
  };

  const resetAI = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }

    setBrief("");
    setSessionId(null);
    setEvents([]);
    setSession(null);
    setLoading(false);
    setPaymentLoading(false);
    setError(null);
  };

  const startShopping = async () => {
    const message = brief.trim();

    if (!message || loading || paymentLoading) return;

    try {
      setLoading(true);
      setError(null);

      const isNewSession = !sessionId;
      const endpoint = isNewSession
        ? `${API_BASE}/agent/shop`
        : `${API_BASE}/agent/sessions/${sessionId}/message`;

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          shopping_brief: message,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to send shopping message");
      }

      if (isNewSession) {
        setEvents([]);
        setSession(null);
        setSessionId(data.session_id);
      }

      setBrief("");

      // Restart polling even when the session_id stays the same.
      setPollingVersion((value) => value + 1);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to send shopping message"
      );
      setLoading(false);
    }
  };

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

      const openCheckout = () => {
        const options = {
          key: data.key_id,
          amount: data.amount,
          currency: data.currency,
          name: "FitStore",
          description: "Purchase authorized by Agentic Shop",
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

      if (window.Razorpay) {
        openCheckout();
        return;
      }

      const existingScript = document.querySelector(
        'script[src="https://checkout.razorpay.com/v1/checkout.js"]'
      ) as HTMLScriptElement | null;

      if (existingScript) {
        existingScript.addEventListener("load", openCheckout, { once: true });
        existingScript.addEventListener(
          "error",
          () => {
            setPaymentLoading(false);
            setError("Failed to load Razorpay Checkout");
          },
          { once: true }
        );
        return;
      }

      const script = document.createElement("script");
      script.src = "https://checkout.razorpay.com/v1/checkout.js";
      script.onload = openCheckout;
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

  const selectedProductId = events.find(
    (event) => event.event_type === "buyer_product_selected"
  )?.detail?.product_id;

  const selectedProduct = products.find(
    (product) => product.id === selectedProductId
  );

  return (
    <main className="min-h-screen bg-white text-zinc-950">
      {/* Store header */}
      <header className="sticky top-0 z-30 border-b border-zinc-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <button
            onClick={() =>
              window.scrollTo({
                top: 0,
                behavior: "smooth",
              })
            }
            className="flex items-center gap-3"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-zinc-950 text-lg font-bold text-white">
              F
            </div>
            <div className="text-left">
              <div className="text-lg font-semibold tracking-tight">
                FitStore
              </div>
              <div className="text-[11px] text-zinc-500">
                Fitness gear, intelligently bought
              </div>
            </div>
          </button>

          <nav className="hidden items-center gap-7 text-sm text-zinc-600 md:flex">
            <a href="#products" className="hover:text-black">
              Products
            </a>
            <a href="#orders" className="hover:text-black">
              My Orders
            </a>
            <button
              onClick={openAIShop}
              className="rounded-full bg-zinc-950 px-4 py-2 text-sm font-medium text-white transition hover:bg-zinc-800"
            >
              ✦ Use AI to Shop
            </button>
          </nav>

          <button
            onClick={openAIShop}
            className="rounded-full bg-zinc-950 px-4 py-2 text-sm font-medium text-white md:hidden"
          >
            ✦ AI Shop
          </button>
        </div>
      </header>

      {/* Hero */}
      <section className="border-b border-zinc-200 bg-zinc-50">
        <div className="mx-auto grid max-w-7xl gap-10 px-6 py-20 lg:grid-cols-[1.15fr_.85fr] lg:items-center lg:py-28">
          <div>
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-600 shadow-sm">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              Agentic commerce enabled
            </div>

            <h1 className="max-w-3xl text-5xl font-semibold tracking-[-0.04em] sm:text-6xl lg:text-7xl">
              Buy fitness gear.
              <br />
              <span className="text-zinc-400">Let AI handle the work.</span>
            </h1>

            <p className="mt-7 max-w-2xl text-lg leading-8 text-zinc-600">
              Browse FitStore normally, or give your shopping brief to an
              autonomous Buyer Agent. It finds products, negotiates with the
              merchant, checks guardrails, and asks you to authorize the final
              payment.
            </p>

            <div className="mt-9 flex flex-wrap gap-3">
              <button
                onClick={openAIShop}
                className="rounded-xl bg-zinc-950 px-6 py-3.5 text-sm font-medium text-white transition hover:bg-zinc-800"
              >
                ✦ Use AI to Shop
              </button>

              <a
                href="#products"
                className="rounded-xl border border-zinc-300 bg-white px-6 py-3.5 text-sm font-medium text-zinc-800 transition hover:border-zinc-500"
              >
                Browse products
              </a>
            </div>

            <div className="mt-9 flex flex-wrap gap-x-6 gap-y-2 text-xs text-zinc-500">
              <span>✓ MCP-powered catalog</span>
              <span>✓ Agent-to-agent negotiation</span>
              <span>✓ Human payment authorization</span>
            </div>
          </div>

          <div className="relative">
            <div className="overflow-hidden rounded-3xl border border-zinc-200 bg-white shadow-xl">
              <div className="border-b border-zinc-200 px-5 py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold">AI Shopping</div>
                    <div className="mt-0.5 text-xs text-zinc-500">
                      Autonomous purchasing agent
                    </div>
                  </div>
                  <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-medium text-emerald-700">
                    LIVE
                  </span>
                </div>
              </div>

              <div className="space-y-4 p-5">
                <div className="ml-auto max-w-[82%] rounded-2xl bg-zinc-100 px-4 py-3 text-sm">
                  I need 2 yoga mats under ₹3,600.
                </div>

                <div className="rounded-2xl border border-zinc-200 p-4">
                  <div className="flex items-center gap-2 text-xs font-semibold text-zinc-500">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-zinc-950 text-[10px] text-white">
                      A
                    </span>
                    BUYER AGENT
                  </div>
                  <div className="mt-4 text-sm font-medium">
                    Negotiating with FitStore...
                  </div>
                  <div className="mt-3 rounded-xl bg-zinc-50 p-3">
                    <div className="text-[11px] text-zinc-500">
                      Merchant counter offer
                    </div>
                    <div className="mt-1 text-lg font-semibold">
                      ₹3,598.20
                    </div>
                    <div className="text-xs text-zinc-500">
                      10% merchant discount
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                  <div className="text-xs font-semibold text-amber-700">
                    🔐 HUMAN AUTHORIZATION
                  </div>
                  <div className="mt-1 text-xs text-amber-800/70">
                    You approve the financial transaction.
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Products */}
      <section id="products" className="mx-auto max-w-7xl px-6 py-20">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-400">
              FitStore catalog
            </div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight">
              Shop the collection
            </h2>
            <p className="mt-2 text-sm text-zinc-500">
              Or let the Buyer Agent choose and negotiate for you.
            </p>
          </div>

          <button
            onClick={openAIShop}
            className="w-fit rounded-xl border border-zinc-300 px-4 py-2.5 text-sm font-medium hover:border-zinc-500"
          >
            ✦ Shop with AI
          </button>
        </div>

        {storeError && (
          <div className="mt-8 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {storeError}
          </div>
        )}

        {storeLoading ? (
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={index}
                className="h-80 animate-pulse rounded-2xl bg-zinc-100"
              />
            ))}
          </div>
        ) : products.length === 0 ? (
          <div className="mt-10 rounded-2xl border border-dashed border-zinc-300 p-12 text-center text-sm text-zinc-500">
            No products found in the FitStore catalog.
          </div>
        ) : (
          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {products.map((product) => (
              <article
                key={product.id}
                className="group overflow-hidden rounded-2xl border border-zinc-200 bg-white transition hover:-translate-y-1 hover:border-zinc-300 hover:shadow-lg"
              >
                <div className="flex h-48 items-center justify-center bg-zinc-100 text-6xl transition group-hover:bg-zinc-50">
                  {categoryEmoji(product.category)}
                </div>

                <div className="p-5">
                  <div className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                    {product.category || "Fitness"}
                  </div>

                  <h3 className="mt-2 text-lg font-semibold tracking-tight">
                    {product.name}
                  </h3>

                  <p className="mt-2 min-h-10 text-sm leading-5 text-zinc-500">
                    {product.description || "Quality fitness equipment from FitStore."}
                  </p>

                  <div className="mt-5 flex items-end justify-between gap-3">
                    <div>
                      <div className="text-xl font-semibold">
                        {formatRupees(product.price)}
                      </div>
                      <div
                        className={`mt-1 text-xs ${product.stock > 0
                            ? "text-emerald-600"
                            : "text-red-500"
                          }`}
                      >
                        {product.stock > 0
                          ? `${product.stock} in stock`
                          : "Out of stock"}
                      </div>
                    </div>

                    <button
                      onClick={openAIShop}
                      className="rounded-lg bg-zinc-950 px-3 py-2 text-xs font-medium text-white hover:bg-zinc-800"
                    >
                      Ask AI
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* How it works */}
      <section className="border-y border-zinc-200 bg-zinc-50">
        <div className="mx-auto max-w-7xl px-6 py-20">
          <div className="max-w-xl">
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-400">
              Agentic commerce
            </div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight">
              The store works with you, not just for you.
            </h2>
          </div>

          <div className="mt-10 grid gap-5 md:grid-cols-4">
            {[
              [
                "01",
                "Tell the agent",
                "Describe what you want, your quantity, and your budget.",
              ],
              [
                "02",
                "Agents negotiate",
                "The Buyer Agent discovers products over MCP and negotiates with FitStore.",
              ],
              [
                "03",
                "Guardrails",
                "The system validates budget, stock, mandate signature, expiry, and discount policy.",
              ],
              [
                "04",
                "You authorize",
                "Razorpay handles the final human-approved financial transaction.",
              ],
            ].map(([number, title, description]) => (
              <div
                key={number}
                className="rounded-2xl border border-zinc-200 bg-white p-5"
              >
                <div className="text-xs font-semibold text-zinc-400">
                  {number}
                </div>
                <h3 className="mt-8 text-base font-semibold">{title}</h3>
                <p className="mt-2 text-sm leading-6 text-zinc-500">
                  {description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Orders */}
      <section id="orders" className="mx-auto max-w-7xl px-6 py-20">
        <div className="flex items-end justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-400">
              Your account
            </div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight">
              My Orders
            </h2>
            <p className="mt-2 text-sm text-zinc-500">
              Orders created by completed FitStore purchases.
            </p>
          </div>

          <button
            onClick={loadOrders}
            className="rounded-lg border border-zinc-300 px-3 py-2 text-xs font-medium hover:border-zinc-500"
          >
            Refresh
          </button>
        </div>

        {ordersLoading ? (
          <div className="mt-8 h-24 animate-pulse rounded-2xl bg-zinc-100" />
        ) : orders.length === 0 ? (
          <div className="mt-8 rounded-2xl border border-dashed border-zinc-300 p-10 text-center">
            <div className="text-3xl">🛍️</div>
            <div className="mt-3 text-sm font-medium">No orders yet</div>
            <p className="mt-1 text-xs text-zinc-500">
              Your agentically purchased products will appear here.
            </p>
            <button
              onClick={openAIShop}
              className="mt-5 rounded-lg bg-zinc-950 px-4 py-2.5 text-xs font-medium text-white"
            >
              Make your first AI purchase
            </button>
          </div>
        ) : (
          <div className="mt-8 space-y-3">
            {orders.map((order) => {
              const product = products.find(
                (item) => item.id === order.product_id
              );

              return (
                <div
                  key={order.id}
                  className="flex flex-col gap-4 rounded-2xl border border-zinc-200 bg-white p-5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex items-center gap-4">
                    <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-zinc-100 text-2xl">
                      {categoryEmoji(product?.category)}
                    </div>

                    <div>
                      <div className="text-sm font-semibold">
                        {product?.name || `Product #${order.product_id}`}
                      </div>
                      <div className="mt-1 text-xs text-zinc-500">
                        {order.order_number} · Qty {order.quantity}
                      </div>
                      <div className="mt-1 text-xs text-zinc-400">
                        {new Date(order.created_at).toLocaleString()}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-6 sm:justify-end">
                    <div className="text-right">
                      <div className="text-base font-semibold">
                        {formatRupees(order.amount)}
                      </div>
                      <div className="mt-1 text-[11px] text-zinc-500">
                        {statusLabel(order.status)}
                      </div>
                    </div>

                    <span className="rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">
                      Confirmed
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Footer */}
      <footer className="border-t border-zinc-200 bg-zinc-950 text-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-10 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="font-semibold">FitStore</div>
            <div className="mt-1 text-xs text-zinc-500">
              Autonomous commerce with human authorization.
            </div>
          </div>
          <button
            onClick={openAIShop}
            className="w-fit rounded-lg border border-zinc-700 px-4 py-2.5 text-xs font-medium text-zinc-200 hover:border-zinc-500"
          >
            ✦ Use AI to Shop
          </button>
        </div>
      </footer>

      {/* AI Shopping modal */}
      {aiOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 p-0 backdrop-blur-sm sm:p-6">
          <div className="mx-auto flex h-full max-w-[1500px] flex-col overflow-hidden bg-zinc-950 text-white sm:rounded-2xl sm:border sm:border-zinc-800">
            <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
              <div>
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white text-sm font-bold text-black">
                    F
                  </div>
                  <div>
                    <h2 className="text-base font-semibold">Agentic Shop</h2>
                    <p className="text-[11px] text-zinc-500">
                      FitStore AI purchasing agent
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="hidden items-center gap-2 text-xs text-zinc-500 sm:flex">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" />
                  Agent system online
                </div>

                {sessionId && !loading && !paymentLoading && (
                  <button
                    onClick={resetAI}
                    className="rounded-lg border border-zinc-700 px-3 py-2 text-xs text-zinc-300 hover:border-zinc-500"
                  >
                    New request
                  </button>
                )}

                <button
                  onClick={closeAIShop}
                  disabled={loading || paymentLoading}
                  className="flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 hover:text-white disabled:opacity-30"
                  aria-label="Close"
                >
                  ×
                </button>
              </div>
            </header>

            <div className="grid min-h-0 flex-1 lg:grid-cols-[1fr_380px]">
              {/* AI chat */}
              <section className="min-h-0 overflow-y-auto border-r border-zinc-800">
                <div className="px-5 py-8 sm:px-10 lg:px-16">
                  {!sessionId ? (
                    <div className="mx-auto flex max-w-3xl flex-col justify-center pt-8 sm:pt-16">
                      <div className="mb-8 text-center">
                        <div className="mb-4 text-xs font-medium tracking-[0.2em] text-zinc-600">
                          BUYER AGENT
                        </div>

                        <h3 className="text-3xl font-semibold tracking-tight sm:text-4xl">
                          What can I buy for you?
                        </h3>

                        <p className="mt-4 text-sm leading-6 text-zinc-500">
                          Give the Buyer Agent a shopping brief. It will
                          discover products, negotiate with FitStore, enforce
                          your constraints, and prepare the purchase.
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
                          placeholder="e.g. I need 2 yoga mats for a total budget of ₹3,600..."
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
                      <div className="space-y-5">
                        {session?.messages?.map((message, index) => (
                          <div
                            key={`${index}-${message.role}-${message.content}`}
                            className={
                              message.role === "user"
                                ? "flex justify-end"
                                : "flex gap-4"
                            }
                          >
                            {message.role === "assistant" && (
                              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-sm font-bold text-black">
                                A
                              </div>
                            )}

                            <div
                              className={
                                message.role === "user"
                                  ? "max-w-xl rounded-2xl bg-zinc-800 px-5 py-4 text-sm text-zinc-100"
                                  : "min-w-0 max-w-2xl flex-1"
                              }
                            >
                              {message.role === "assistant" && (
                                <div className="mb-2 text-sm font-medium">
                                  Buyer Agent
                                </div>
                              )}
                              <div
                                className={
                                  message.role === "assistant"
                                    ? "rounded-2xl border border-zinc-800 bg-zinc-900 p-5 whitespace-pre-wrap text-sm leading-6 text-zinc-300"
                                    : "whitespace-pre-wrap"
                                }
                              >
                                {message.content}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>

                      {loading && (
                        <div className="mt-6 flex gap-4">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-sm font-bold text-black">
                            A
                          </div>
                          <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5 text-sm text-zinc-500">
                            Understanding your request...
                          </div>
                        </div>
                      )}

                      {!loading &&
                        session?.status === "answered" &&
                        (!session?.messages ||
                          !session.messages.some(
                            (message) => message.role === "assistant"
                          )) &&
                        (() => {
                          const responseEvents = events.filter(
                            (event) => event.event_type === "assistant_response"
                          );

                          const lastResponse =
                            responseEvents[responseEvents.length - 1];

                          if (!lastResponse) return null;

                          const answer =
                            typeof lastResponse.detail === "string"
                              ? lastResponse.detail
                              : lastResponse.detail?.answer;

                          if (!answer) return null;

                          return (
                            <div className="mt-6 flex gap-4">
                              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-sm font-bold text-black">
                                A
                              </div>
                              <div className="min-w-0 max-w-2xl flex-1">
                                <div className="mb-2 text-sm font-medium">
                                  Buyer Agent
                                </div>
                                <div className="whitespace-pre-wrap rounded-2xl border border-zinc-800 bg-zinc-900 p-5 text-sm leading-6 text-zinc-300">
                                  {answer}
                                </div>
                              </div>
                            </div>
                          );
                        })()}

                      {selectedProduct && (
                        <div className="mt-5 rounded-xl bg-zinc-950 p-4">
                          <div className="flex items-center gap-3">
                            <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-zinc-900 text-xl">
                              {categoryEmoji(selectedProduct.category)}
                            </div>
                            <div>
                              <div className="font-medium">
                                {selectedProduct.name}
                              </div>
                              <div className="mt-1 text-sm text-zinc-500">
                                Quantity: {events.find(
                                  (event) =>
                                    event.event_type ===
                                    "buyer_product_selected"
                                )?.detail?.quantity}
                              </div>
                            </div>
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
                                    negotiationEvent.detail.response.counter.price
                                  )}
                                </div>
                                <div className="text-xs text-zinc-500">
                                  {negotiationEvent.detail.response.counter.discount_pct}% merchant discount
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
                            The agents have completed the purchase decision. You
                            must authorize the financial transaction.
                          </div>

                          <div className="mt-5 flex items-end justify-between gap-4">
                            <div>
                              <div className="text-xs text-zinc-600">Amount</div>
                              <div className="text-2xl font-semibold">
                                {formatRupees(authorizationEvent.detail.amount)}
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
                            Payment was captured and your FitStore order was
                            created successfully.
                          </p>

                          <button
                            onClick={async () => {
                              await loadOrders();
                              await loadStore();
                              setAiOpen(false);
                            }}
                            className="mt-4 rounded-lg bg-white px-4 py-2.5 text-xs font-medium text-black"
                          >
                            Back to FitStore
                          </button>
                        </div>
                      )}

                      {session?.status === "failed" && (
                        <div className="mt-5 rounded-2xl border border-red-500/30 bg-red-500/5 p-5">
                          <div className="text-sm font-semibold text-red-400">
                            Purchase could not be completed
                          </div>
                          <p className="mt-2 text-sm text-zinc-500">
                            The agent stopped because a safety or execution
                            condition was not satisfied.
                          </p>
                        </div>
                      )}

                      {session?.status === "payment_failed" && (
                        <div className="mt-5 rounded-2xl border border-red-500/30 bg-red-500/5 p-5">
                          <div className="text-sm font-semibold text-red-400">
                            Payment failed
                          </div>
                          <p className="mt-2 text-sm text-zinc-500">
                            The payment was not captured. Your mandate was not
                            executed.
                          </p>
                        </div>
                      )}

                      {session?.status !== "awaiting_payment" &&
                        session?.status !== "completed" && (
                          <div className="mt-8 rounded-2xl border border-zinc-800 bg-zinc-900 p-3 shadow-2xl">
                            <textarea
                              value={brief}
                              onChange={(e) => setBrief(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && !e.shiftKey) {
                                  e.preventDefault();
                                  startShopping();
                                }
                              }}
                              placeholder="Ask a follow-up, e.g. Can I get two of those?"
                              disabled={loading}
                              className="min-h-24 w-full resize-none bg-transparent p-3 text-sm outline-none placeholder:text-zinc-600 disabled:opacity-50"
                            />

                            <div className="flex items-center justify-between border-t border-zinc-800 pt-3">
                              <span className="px-3 text-xs text-zinc-600">
                                Enter to send · Shift+Enter for a new line
                              </span>
                              <button
                                onClick={startShopping}
                                disabled={!brief.trim() || loading}
                                className="rounded-xl bg-white px-5 py-2.5 text-sm font-medium text-black transition hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
                              >
                                {loading ? "Agent working..." : "Send"}
                              </button>
                            </div>
                          </div>
                        )}
                    </div>
                  )}
                </div>
              </section>

              {/* Trace */}
              <aside className="hidden min-h-0 bg-zinc-950 lg:block">
                <div className="flex h-full flex-col">
                  <div className="border-b border-zinc-800 px-5 py-4">
                    <div className="text-xs font-semibold tracking-wider text-zinc-500">
                      EXECUTION TRACE
                    </div>
                    <div className="mt-1 text-sm text-zinc-300">
                      Live agent activity
                    </div>
                  </div>

                  <div className="min-h-0 flex-1 overflow-y-auto p-5">
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
          </div>
        </div>
      )}

      {error && (
        <div className="fixed bottom-5 left-1/2 z-[60] -translate-x-1/2 rounded-xl border border-red-500/30 bg-red-950 px-5 py-3 text-sm text-red-300 shadow-2xl">
          {error}
        </div>
      )}
    </main>
  );
}
