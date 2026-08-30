"""
AdatTracker Pro - Razorpay Subscriptions & UPI AutoPay Engine
Handles Razorpay subscription creation, cancellation, webhook verification, and lifecycle state management.
"""

import hmac
import hashlib
import json
import base64
import urllib.request
import urllib.error
import datetime
from typing import Optional, Dict, Any, Tuple

from config import (
    BILLING_ENABLED,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET,
    RAZORPAY_PLAN_ID,
    HOSTED_PRICE,
    HOSTED_CURRENCY
)
import database as db

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"

def is_billing_enabled() -> bool:
    """Returns True if hosted billing is active."""
    return BILLING_ENABLED

def get_billing_config(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Returns public billing metadata and user's current subscription status."""
    if not BILLING_ENABLED:
        return {
            "billing_enabled": False,
            "plan": "self_hosted_free",
            "status": "active",
            "price": 0,
            "currency": "INR",
            "is_hosted": False
        }

    sub = db.get_subscription_by_user_id(user_id) if user_id else None
    status = sub["status"] if sub else "inactive"

    return {
        "billing_enabled": True,
        "plan": sub["plan"] if sub else "hosted_monthly",
        "status": status,
        "price": HOSTED_PRICE,
        "currency": HOSTED_CURRENCY,
        "is_hosted": True,
        "razorpay_key_id": RAZORPAY_KEY_ID,
        "current_period_start": sub.get("current_period_start") if sub else None,
        "current_period_end": sub.get("current_period_end") if sub else None,
        "cancelled_at": sub.get("cancelled_at") if sub else None
    }

def _razorpay_auth_header() -> str:
    """Generates HTTP Basic Auth header for Razorpay API."""
    creds = f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}"
    b64_creds = base64.b64encode(creds.encode("utf-8")).decode("utf-8")
    return f"Basic {b64_creds}"

def create_razorpay_subscription(user: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Creates a recurring subscription on Razorpay for ₹21/month with UPI AutoPay support.
    Returns: (success: bool, checkout_data: dict, error_message: str)
    """
    if not BILLING_ENABLED:
        return False, None, "Billing is not enabled on this installation."

    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET or not RAZORPAY_PLAN_ID:
        return False, None, "Razorpay credentials or plan ID not configured."

    user_id = user["id"]
    email = user.get("email", "")
    username = user.get("username", "")
    phone = user.get("phone", "")

    # Check if user already has an active subscription
    existing_sub = db.get_subscription_by_user_id(user_id)
    if existing_sub and existing_sub["status"] == "active":
        return True, {
            "already_active": True,
            "subscription_id": existing_sub["razorpay_subscription_id"],
            "status": "active"
        }, "Subscription is already active."

    # Build Razorpay API payload
    payload = {
        "plan_id": RAZORPAY_PLAN_ID,
        "total_count": 120,  # 120 cycles (10 years)
        "quantity": 1,
        "customer_notify": 1,
        "notes": {
            "user_id": user_id,
            "email": email,
            "username": username
        }
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{RAZORPAY_API_BASE}/subscriptions",
        data=req_data,
        headers={
            "Authorization": _razorpay_auth_header(),
            "Content-Type": "application/json",
            "User-Agent": "AdatTracker-Pro/2.5"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=12.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            rzp_sub_id = data.get("id")

            if not rzp_sub_id:
                return False, None, "Failed to obtain subscription ID from Razorpay."

            # Upsert local subscription state as 'pending'
            db.upsert_subscription(
                user_id=user_id,
                razorpay_sub_id=rzp_sub_id,
                plan="hosted_monthly",
                status="pending"
            )

            checkout_params = {
                "subscription_id": rzp_sub_id,
                "key_id": RAZORPAY_KEY_ID,
                "name": "AdatTracker Pro",
                "description": f"Hosted Monthly Subscription ({HOSTED_CURRENCY} {HOSTED_PRICE}/mo)",
                "amount": HOSTED_PRICE * 100,  # in paise
                "currency": HOSTED_CURRENCY,
                "prefill": {
                    "name": username,
                    "email": email,
                    "contact": phone or ""
                },
                "theme": {
                    "color": "#7c3aed"
                }
            }
            return True, checkout_params, "Subscription created successfully."

    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        print(f"❌ Razorpay create_subscription HTTP {e.code}: {err_msg}")
        return False, None, f"Payment gateway error ({e.code}). Please try again."
    except Exception as e:
        print(f"❌ Razorpay create_subscription error: {str(e)}")
        return False, None, "Failed to initialize payment gateway."

def cancel_razorpay_subscription(user_id: str) -> Tuple[bool, str]:
    """
    Cancels an active subscription on Razorpay and updates local state.
    Returns: (success: bool, message: str)
    """
    if not BILLING_ENABLED:
        return False, "Billing is not enabled on this installation."

    sub = db.get_subscription_by_user_id(user_id)
    if not sub:
        return False, "No subscription found."

    rzp_sub_id = sub.get("razorpay_subscription_id")
    if not rzp_sub_id:
        return False, "Subscription ID missing."

    # Call Razorpay API to cancel
    payload = json.dumps({"cancel_at_cycle_end": 0}).encode("utf-8")
    req = urllib.request.Request(
        f"{RAZORPAY_API_BASE}/subscriptions/{rzp_sub_id}/cancel",
        data=payload,
        headers={
            "Authorization": _razorpay_auth_header(),
            "Content-Type": "application/json",
            "User-Agent": "AdatTracker-Pro/2.5"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=12.0) as resp:
            pass
    except Exception as e:
        print(f"⚠️ Razorpay cancel API returned error (continuing local cancellation): {str(e)}")

    now_iso = datetime.datetime.utcnow().isoformat()
    db.update_subscription_status(rzp_sub_id, status="cancelled", cancelled_at=now_iso)
    return True, "Subscription cancelled successfully."

def verify_webhook_signature(body_bytes: bytes, signature_header: Optional[str]) -> bool:
    """
    Cryptographically verifies Razorpay webhook HMAC-SHA256 signature.
    Prevents unauthorized or forged webhook payloads.
    """
    if not signature_header or not RAZORPAY_WEBHOOK_SECRET:
        return False

    expected_sig = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        body_bytes,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_sig, signature_header.strip())

def process_razorpay_webhook(event_payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Processes verified Razorpay webhook events with idempotency and state mapping.
    Supported events:
      - subscription.authenticated (UPI AutoPay mandate approved)
      - subscription.activated
      - subscription.charged (successful recurring billing cycle)
      - subscription.pending (payment retry grace period)
      - subscription.halted (all retries failed, access suspended)
      - subscription.cancelled
      - subscription.resumed
    """
    event_id = event_payload.get("id") or event_payload.get("event_id")
    event_type = event_payload.get("event", "")

    # Idempotency check: Ignore duplicate deliveries
    if event_id and db.is_webhook_event_processed(event_id):
        return True, "Event already processed."

    sub_entity = event_payload.get("payload", {}).get("subscription", {}).get("entity", {})
    payment_entity = event_payload.get("payload", {}).get("payment", {}).get("entity", {})

    rzp_sub_id = sub_entity.get("id") or payment_entity.get("subscription_id")
    if not rzp_sub_id:
        # Fallback: check if subscription ID is in event notes
        notes = sub_entity.get("notes") or payment_entity.get("notes") or {}
        user_id = notes.get("user_id")
        if user_id:
            sub = db.get_subscription_by_user_id(user_id)
            if sub:
                rzp_sub_id = sub["razorpay_subscription_id"]

    if not rzp_sub_id:
        return False, "No subscription ID identified in webhook payload."

    # Parse period start/end timestamps
    period_start_iso = None
    period_end_iso = None
    if sub_entity.get("current_start"):
        try:
            period_start_iso = datetime.datetime.utcfromtimestamp(sub_entity["current_start"]).isoformat()
        except Exception:
            pass
    if sub_entity.get("current_end"):
        try:
            period_end_iso = datetime.datetime.utcfromtimestamp(sub_entity["current_end"]).isoformat()
        except Exception:
            pass

    # Map Razorpay lifecycle events to internal AdatTracker statuses
    now_iso = datetime.datetime.utcnow().isoformat()

    if event_type in ("subscription.authenticated", "subscription.activated", "subscription.resumed"):
        db.update_subscription_status(
            rzp_sub_id,
            status="active",
            period_start=period_start_iso,
            period_end=period_end_iso
        )
    elif event_type == "subscription.charged":
        # Recurring payment successful
        db.update_subscription_status(
            rzp_sub_id,
            status="active",
            period_start=period_start_iso,
            period_end=period_end_iso
        )
    elif event_type == "subscription.pending":
        # Payment failed; Razorpay will retry. Grace period active.
        db.update_subscription_status(
            rzp_sub_id,
            status="pending",
            period_start=period_start_iso,
            period_end=period_end_iso
        )
    elif event_type == "subscription.halted":
        # Retries exhausted; restrict application access
        db.update_subscription_status(
            rzp_sub_id,
            status="halted",
            period_start=period_start_iso,
            period_end=period_end_iso
        )
    elif event_type == "subscription.cancelled":
        db.update_subscription_status(
            rzp_sub_id,
            status="cancelled",
            period_start=period_start_iso,
            period_end=period_end_iso,
            cancelled_at=now_iso
        )

    # Record event in idempotency table
    if event_id:
        db.record_webhook_event(event_id, event_type)

    return True, f"Handled {event_type} for {rzp_sub_id}."
