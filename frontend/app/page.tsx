"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

declare global {
  interface Window {
    Razorpay: any;
  }
}

export default function Home() {
  const searchParams = useSearchParams();

  const mandateId = searchParams.get("mandate_id");

  const [loading, setLoading] = useState(false);

  const startPayment = async () => {
    try {
      setLoading(true);

      // -------------------------------------------------
      // 1. Make sure a Buyer Agent mandate was supplied
      // -------------------------------------------------

      if (!mandateId) {
        throw new Error(
          "No mandate_id found in the URL."
        );
      }

      console.log(
        "Using Buyer Agent mandate:",
        mandateId
      );

      // -------------------------------------------------
      // 2. Get the Razorpay order created by Buyer Agent
      // -------------------------------------------------

      const response = await fetch(
        `http://127.0.0.1:8000/mandates/${mandateId}/order`
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Failed to retrieve order"
        );
      }

      console.log(
        "Razorpay order:",
        data.order_id
      );

      // -------------------------------------------------
      // 3. Load Razorpay Checkout
      // -------------------------------------------------

      const script = document.createElement("script");

      script.src =
        "https://checkout.razorpay.com/v1/checkout.js";

      script.onload = () => {

        // -------------------------------------------------
        // 4. Configure Razorpay Checkout
        // -------------------------------------------------

        const options = {
          key: data.key_id,

          currency: data.currency,

          name: "Agentic Shop",

          description:
            "Buyer Agent Purchase",

          order_id: data.order_id,

          handler: function (response: any) {

            console.log(
              "Payment successful!"
            );

            console.log(
              "Payment ID:",
              response.razorpay_payment_id
            );

            console.log(
              "Order ID:",
              response.razorpay_order_id
            );

            console.log(
              "Signature:",
              response.razorpay_signature
            );

            alert(
              "Payment successful! Waiting for webhook confirmation."
            );
          },

          theme: {
            color: "#000000",
          },
        };

        const razorpay =
          new window.Razorpay(options);

        razorpay.open();

        setLoading(false);
      };

      script.onerror = () => {
        throw new Error(
          "Failed to load Razorpay Checkout"
        );
      };

      document.body.appendChild(script);

    } catch (error) {

      console.error(error);

      alert(
        error instanceof Error
          ? error.message
          : "Failed to start payment"
      );

      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center bg-zinc-100">

      <div className="bg-white p-10 rounded-2xl shadow-md text-center">

        <h1 className="text-3xl font-bold mb-4">
          Agentic Shop
        </h1>

        <p className="text-zinc-600 mb-2">
          Buyer Agent Purchase
        </p>

        {mandateId ? (
          <p className="text-xs text-zinc-400 mb-6 break-all">
            Mandate: {mandateId}
          </p>
        ) : (
          <p className="text-red-500 mb-6">
            No Buyer Agent mandate provided.
          </p>
        )}

        <button
          onClick={startPayment}
          disabled={loading || !mandateId}
          className="px-6 py-3 rounded-lg bg-black text-white disabled:opacity-50"
        >
          {loading
            ? "Loading Checkout..."
            : "Pay with Razorpay"}
        </button>

      </div>

    </main>
  );
}