import hmac
import hashlib

import razorpay
from fastapi import APIRouter, Depends, Request, HTTPException, status
from firebase_admin import firestore

from app.config import settings
from app.database import db
from app.auth import get_verified_uid

router = APIRouter(prefix="/api/payments", tags=["Payments"])
razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


@router.post("/create-order")
async def create_order(uid: str = Depends(get_verified_uid)):
    """Step 5: called when the user hits 'Pay ₹345'. Creates a Razorpay order AND
    records it in Firestore so the webhook can be verified against something real,
    instead of trusting whatever userId shows up in the webhook notes."""
    try:
        order = razorpay_client.order.create(
            data={
                "amount": settings.PLATFORM_FEE * 100,  # paise
                "currency": "INR",
                "receipt": f"receipt_pro_{uid}",
                "notes": {"userId": uid},
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    db.collection("orders").document(order["id"]).set(
        {
            "userId": uid,
            "status": "CREATED",
            "amount": settings.PLATFORM_FEE,
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
    )
    return order


@router.post("/webhook")
async def razorpay_webhook(request: Request):
    """Razorpay calls this directly — no auth header, so it's secured entirely by
    signature verification. Must be registered as a public HTTPS URL in the
    Razorpay Dashboard (Accounts & Settings -> Webhooks), with its own Secret
    (NOT your API key secret) matching RAZORPAY_WEBHOOK_SECRET below.

    Idempotent: Razorpay retries on any non-2xx / timeout for up to 24h, so the
    same event can arrive more than once. The webhookEvents collection guards
    against double-processing a payment."""
    signature = request.headers.get("X-Razorpay-Signature", "")
    raw_body = await request.body()

    expected_signature = hmac.new(
        bytes(settings.RAZORPAY_WEBHOOK_SECRET, "utf-8"), raw_body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature mismatch")

    event = await request.json()
    event_type = event.get("event")
    payment_entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    event_id = payment_entity.get("id")

    if not event_id:
        return {"status": "ignored", "reason": "no payment entity"}

    event_ref = db.collection("webhookEvents").document(event_id)
    if event_ref.get().exists:
        return {"status": "duplicate_ignored"}

    order_id = payment_entity.get("order_id")
    order_doc = db.collection("orders").document(order_id).get() if order_id else None

    if event_type == "payment.captured" and order_doc and order_doc.exists:
        user_id = order_doc.to_dict()["userId"]
        db.collection("users").document(user_id).set(
            {
                "isPro": True,
                "payment": {
                    "status": "COMPLETED",
                    "paymentId": payment_entity.get("id"),
                    "orderId": order_id,
                },
                "journey": {"completedSteps": firestore.ArrayUnion(["PAYMENT_COMPLETED"])},
            },
            merge=True,
        )
        db.collection("orders").document(order_id).update({"status": "PAID"})

    elif event_type == "payment.failed" and order_doc and order_doc.exists:
        db.collection("orders").document(order_id).update({"status": "FAILED"})

    event_ref.set({"type": event_type, "processedAt": firestore.SERVER_TIMESTAMP})
    return {"status": "processed"}


@router.post("/dev-grant-pro")
async def dev_grant_pro(uid: str = Depends(get_verified_uid)):
    """Testing-only shortcut that skips Razorpay entirely and marks the
    calling user Pro directly — same end state as a real successful payment,
    none of the checkout flow.

    Safe by construction, not just by convention:
    - Requires a valid Firebase token (get_verified_uid) — can only ever act
      on the caller's own account, never anyone else's.
    - Hard-disabled unless ALLOW_DEV_BYPASS=true is explicitly set as an env
      var. Defaults False. If you're reading this in production logs and
      didn't expect this endpoint to work, check that env var first.

    Turn ALLOW_DEV_BYPASS off (or just delete the env var) before any real
    user could reach this build — while it's on, anyone with a Firebase
    account can get Pro for free by calling this endpoint directly.
    """
    if not settings.ALLOW_DEV_BYPASS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev bypass is disabled. Set ALLOW_DEV_BYPASS=true in Cloud Run env vars to enable for testing.",
        )

    db.collection("users").document(uid).set(
        {
            "isPro": True,
            "payment": {"status": "COMPLETED", "paymentId": "dev-bypass", "orderId": "dev-bypass"},
            "journey": {"completedSteps": firestore.ArrayUnion(["PAYMENT_COMPLETED"])},
        },
        merge=True,
    )
    return {"status": "granted", "warning": "This was a dev bypass, not a real payment."}
