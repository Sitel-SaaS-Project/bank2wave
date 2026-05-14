import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from models import User, PlanTier, PLAN_CONFIG, get_db
from auth import get_current_user

router = APIRouter()

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_IDS = {
    PlanTier.STARTER: os.environ.get("STRIPE_PRICE_STARTER", ""),
    PlanTier.PRO: os.environ.get("STRIPE_PRICE_PRO", ""),
    PlanTier.BUSINESS: os.environ.get("STRIPE_PRICE_BUSINESS", ""),
}

def get_stripe():
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe

class PlanResponse(BaseModel):
    current_plan: str
    price_monthly: float
    max_accounts: int
    sync_frequency: str
    available_plans: list

class CheckoutRequest(BaseModel):
    plan: PlanTier
    success_url: str
    cancel_url: str

class CheckoutResponse(BaseModel):
    checkout_url: str

@router.get("/plans")
def get_plans():
    return [
        {"tier": tier, "label": config["label"], "price_monthly": config["price_monthly"], "max_accounts": config["max_accounts"], "sync_frequency": config["sync_frequency"]}
        for tier, config in PLAN_CONFIG.items()
    ]

@router.get("/my-plan", response_model=PlanResponse)
def my_plan(current_user: User = Depends(get_current_user)):
    config = PLAN_CONFIG[current_user.plan]
    return PlanResponse(current_plan=current_user.plan, price_monthly=config["price_monthly"], max_accounts=config["max_accounts"], sync_frequency=config["sync_frequency"], available_plans=list(PLAN_CONFIG.keys()))

@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(req: CheckoutRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.plan == PlanTier.FREE:
        raise HTTPException(status_code=400, detail="Cannot checkout to free plan")
    price_id = STRIPE_PRICE_IDS.get(req.plan)
    if not price_id:
        raise HTTPException(status_code=500, detail=f"Stripe price not configured for {req.plan}")
    stripe = get_stripe()
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(email=current_user.email)
        current_user.stripe_customer_id = customer.id
        db.commit()
    session = stripe.checkout.Session.create(
        customer=current_user.stripe_customer_id,
        payment_method_types=["card"],
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=req.success_url,
        cancel_url=req.cancel_url,
        metadata={"user_id": str(current_user.id), "plan": req.plan},
    )
    return CheckoutResponse(checkout_url=session.url)

@router.post("/cancel")
def cancel_subscription(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.plan == PlanTier.FREE:
        raise HTTPException(status_code=400, detail="Already on free plan")
    stripe = get_stripe()
    if current_user.stripe_subscription_id:
        stripe.Subscription.modify(current_user.stripe_subscription_id, cancel_at_period_end=True)
    current_user.plan = PlanTier.FREE
    current_user.stripe_subscription_id = None
    db.commit()
    return {"message": "Subscription cancelled. You've been moved to the free plan."}

@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    stripe = get_stripe()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = int(session["metadata"]["user_id"])
        plan = session["metadata"]["plan"]
        subscription_id = session.get("subscription")
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.plan = PlanTier(plan)
            user.stripe_subscription_id = subscription_id
            db.commit()
    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        subscription = event["data"]["object"]
        user = db.query(User).filter(User.stripe_subscription_id == subscription["id"]).first()
        if user:
            user.plan = PlanTier.FREE
            user.stripe_subscription_id = None
            db.commit()
    return {"received": True}
