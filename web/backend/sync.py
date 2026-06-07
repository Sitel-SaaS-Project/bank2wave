import os
import sys
sys.path.insert(0, "C:/Users/Maro/OneDrive/Desktop/Marouane file/Projet wave/bank2wave/core")

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet
from models import User, BankAccount, SyncLog, PlanTier, PLAN_CONFIG, get_db
from auth import get_current_user


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


def mock_fetch_transactions_full_sync(
    access_token: str,
    *,
    account_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    # Retourne des transactions fictives pour le développement et les tests locaux.
    # Format compatible avec `to_wave_rows` dans core/bank2wave.py
    sample = [
        {"amount": 1500.0, "date": "2026-05-01", "name": "Mock Salary", "category": ["Income"]},
        {"amount": 42.5, "date": "2026-05-03", "name": "Mock Coffee", "category": ["Food"]},
        {"amount": 120.0, "date": "2026-05-05", "name": "Mock Grocery", "category": ["Groceries"]},
    ]
    if account_id:
        return sample
    return sample

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
    # En mode mock, on retourne un link_token factice (pas d'appel réseau).
    from uuid import uuid4
    return PlaidLinkTokenResponse(link_token=f"mock-link-{connector_id}-{uuid4()}")

@router.post("/link-account", response_model=BankAccountResponse, status_code=201)
def link_account(req: LinkAccountRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_account_limit(current_user, db)
    # En mode mock, on utilise le `plaid_public_token` fourni comme access token factice.
    access_token = req.plaid_public_token
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
        import sys
        sys.path.insert(0, "C:/Users/Maro/OneDrive/Desktop/Marouane file/Projet wave/bank2wave/core")
        from bank2wave import to_wave_rows
        access_token = decrypt_token(account.plaid_access_token_enc)
        # Utilise des données mock locales au lieu d'appels Plaid
        transactions = mock_fetch_transactions_full_sync(access_token, account_id=account.plaid_account_id)
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
