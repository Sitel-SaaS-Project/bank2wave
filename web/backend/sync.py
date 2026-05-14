import os
import sys
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet
from models import User, BankAccount, SyncLog, PlanTier, PLAN_CONFIG, get_db
from auth import get_current_user

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../core"))
router = APIRouter()

_raw_key = os.environ.get("ENCRYPTION_KEY", "")
if _raw_key:
    FERNET = Fernet(_raw_key.encode())
else:
    FERNET = Fernet(Fernet.generate_key())

def encrypt_token(token: str) -> str:
    return FERNET.encrypt(token.encode()).decode()

def decrypt_token(encrypted: str) -> str:
    return FERNET.decrypt(encrypted.encode()).decode()

def enforce_account_limit(user: User, db: Session):
    config = PLAN_CONFIG[user.plan]
    count = db.query(BankAccount).filter(BankAccount.user_id == user.id, BankAccount.is_active == True).count()
    if count >= config["max_accounts"]:
        raise HTTPException(status_code=403, detail=f"Your {user.plan} plan allows max {config['max_accounts']} account(s). Upgrade to add more.")

class LinkAccountRequest(BaseModel):
    connector_id: str
    plaid_public_token: str
    plaid_account_id: str
    account_label: Optional[str] = None
    wave_account_name: Optional[str] = "Bank"

class BankAccountResponse(BaseModel):
    id: int
    connector_id: str
    account_label: Optional[str]
    wave_account_name: str
    is_active: bool
    last_synced_at: Optional[datetime]
    created_at: datetime
    class Config:
        from_attributes = True

class SyncLogResponse(BaseModel):
    id: int
    bank_account_id: int
    status: str
    transactions_synced: int
    error_message: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
    class Config:
        from_attributes = True

class PlaidLinkTokenResponse(BaseModel):
    link_token: str

@router.get("/plaid-link-token/{connector_id}", response_model=PlaidLinkTokenResponse)
def get_plaid_link_token(connector_id: str, current_user: User = Depends(get_current_user)):
    try:
        from bank_connectors import CONNECTORS_META, _plaid_client
        from plaid.model.country_code import CountryCode
        from plaid.model.link_token_create_request import LinkTokenCreateRequest
        from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
        from plaid.model.products import Products
        from uuid import uuid4
        if connector_id not in CONNECTORS_META:
            raise HTTPException(status_code=400, detail=f"Unknown connector: {connector_id}")
        client = _plaid_client()
        req = LinkTokenCreateRequest(
            client_name="bank2wave",
            language="en",
            country_codes=[CountryCode("CA")],
            user=LinkTokenCreateRequestUser(client_user_id=str(current_user.id)),
            products=[Products("transactions")],
        )
        resp = client.link_token_create(req)
        return PlaidLinkTokenResponse(link_token=resp.to_dict()["link_token"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/link-account", response_model=BankAccountResponse, status_code=201)
def link_account(req: LinkAccountRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_account_limit(current_user, db)
    try:
        from bank_connectors import _plaid_client, _resp_to_dict
        from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
        client = _plaid_client()
        exchange = client.item_public_token_exchange(ItemPublicTokenExchangeRequest(public_token=req.plaid_public_token))
        access_token = _resp_to_dict(exchange)["access_token"]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Plaid token exchange failed: {e}")
    account = BankAccount(
        user_id=current_user.id,
        connector_id=req.connector_id,
        plaid_access_token_enc=encrypt_token(access_token),
        plaid_account_id=req.plaid_account_id,
        account_label=req.account_label,
        wave_account_name=req.wave_account_name or "Bank",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account

@router.get("/accounts", response_model=List[BankAccountResponse])
def list_accounts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(BankAccount).filter(BankAccount.user_id == current_user.id, BankAccount.is_active == True).all()

@router.delete("/accounts/{account_id}")
def remove_account(account_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.user_id == current_user.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.is_active = False
    db.commit()
    return {"message": "Account removed"}

@router.post("/run/{account_id}", response_model=SyncLogResponse)
def run_sync(account_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = db.query(BankAccount).filter(BankAccount.id == account_id, BankAccount.user_id == current_user.id, BankAccount.is_active == True).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    log = SyncLog(user_id=current_user.id, bank_account_id=account.id, status="pending", started_at=datetime.utcnow())
    db.add(log)
    db.commit()
    db.refresh(log)
    try:
        from bank_connectors import plaid_fetch_transactions_full_sync
        from bank2wave import to_wave_rows
        access_token = decrypt_token(account.plaid_access_token_enc)
        transactions = plaid_fetch_transactions_full_sync(access_token, account_id=account.plaid_account_id)
        rows = to_wave_rows(transactions, account_name=account.wave_account_name)
        log.status = "success"
        log.transactions_synced = len(rows)
        log.completed_at = datetime.utcnow()
        account.last_synced_at = datetime.utcnow()
    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)
        log.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(log)
    return log

@router.get("/history", response_model=List[SyncLogResponse])
def sync_history(limit: int = 20, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(SyncLog).filter(SyncLog.user_id == current_user.id).order_by(SyncLog.started_at.desc()).limit(limit).all()
