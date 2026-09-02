"use client";

import { useState } from "react";

declare global {
  interface Window {
    Razorpay: any;
  }
}

export default function Home() {
  const [loading, setLoading] = useState(false);

  const startPayment = async () => {
    try {
      setLoading(true);

      // 1. Ask our backend to create a mandate + Razorpay order
      const response = await fetch(
        "http://127.0.0.1:8000/create-test-order",
        {
          method: "POST",
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to create order");
      }

      // 2. Load Razorpay Checkout
      const script = document.createElement("script");

      script.src = "https://checkout.razorpay.com/v1/checkout.js";

      script.onload = () => {
        // 3. Configure Checkout using OUR order
        const options = {
          key: data.key_id,
          amount: data.amount,
          currency: data.currency,
          name: "Agentic Shop",
          description: "Test Mandate Payment",

          order_id: data.order_id,

          handler: function (response: any) {
            console.log("Payment successful!");
            console.log("Payment ID:", response.razorpay_payment_id);
            console.log("Order ID:", response.razorpay_order_id);
            console.log(
              "Signature:",
              response.razorpay_signature
            );
          },

          theme: {
            color: "#000000",
          },
        };

        const razorpay = new window.Razorpay(options);

        razorpay.open();
        setLoading(false);
      };

      script.onerror = () => {
        throw new Error("Failed to load Razorpay Checkout");
      };

      document.body.appendChild(script);

    } catch (error) {
      console.error(error);
      alert("Failed to start payment");
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center bg-zinc-100">
      <div className="bg-white p-10 rounded-2xl shadow-md text-center">
        <h1 className="text-3xl font-bold mb-4">
          Agentic Shop
        </h1>

        <p className="text-zinc-600 mb-6">
          Test Mandate Payment
        </p>

        <button
          onClick={startPayment}
          disabled={loading}
          className="px-6 py-3 rounded-lg bg-black text-white disabled:opacity-50"
        >
          {loading ? "Creating Order..." : "Pay ₹8,500"}
        </button>
      </div>
    </main>
  );
}