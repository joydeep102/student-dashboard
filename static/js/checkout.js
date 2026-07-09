/*
 * Razorpay online checkout for the recorded-course payment page.
 *
 * Flow: click → ask our server to create an order (+ pending Payment) → open
 * Razorpay Checkout → on success, POST the signature back to our server, which
 * verifies it and unlocks the course. The webhook is the authoritative confirm;
 * this just gives the student instant feedback.
 */
(function () {
    const btn = document.getElementById("rzp-btn");
    if (!btn || !window.Razorpay) return;

    const msg = document.getElementById("rzp-msg");
    const csrf = btn.dataset.csrf;
    const orderUrl = btn.dataset.orderUrl;
    const verifyUrl = btn.dataset.verifyUrl;
    const plan = btn.dataset.plan;

    function post(url, data) {
        return fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrf || "",
                "X-Requested-With": "fetch",
            },
            body: new URLSearchParams(data).toString(),
        }).then((r) => r.json());
    }

    function say(text) { if (msg) msg.textContent = text; }

    btn.addEventListener("click", async () => {
        btn.disabled = true;
        say("Starting secure checkout…");
        try {
            const order = await post(orderUrl, { plan: plan });
            if (!order || order.error) {
                say((order && order.error) || "Could not start payment.");
                btn.disabled = false;
                return;
            }
            const rzp = new window.Razorpay({
                key: order.key_id,
                amount: order.amount,
                currency: order.currency,
                name: order.name,
                description: order.description,
                order_id: order.order_id,
                prefill: order.prefill,
                theme: { color: "#16a34a" },
                handler: async (resp) => {
                    say("Verifying payment…");
                    const v = await post(verifyUrl, {
                        razorpay_order_id: resp.razorpay_order_id,
                        razorpay_payment_id: resp.razorpay_payment_id,
                        razorpay_signature: resp.razorpay_signature,
                    });
                    if (v && v.ok) {
                        say("Payment successful! Redirecting…");
                        window.location = v.redirect;
                    } else {
                        say((v && v.error) || "Verification failed. Please contact support.");
                        btn.disabled = false;
                    }
                },
                modal: {
                    ondismiss: () => { say("Payment cancelled."); btn.disabled = false; },
                },
            });
            rzp.on("payment.failed", () => {
                say("Payment failed. Please try again.");
                btn.disabled = false;
            });
            rzp.open();
        } catch (e) {
            say("Something went wrong. Please try again.");
            btn.disabled = false;
        }
    });
})();
