from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Enum, Text, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./bank2wave.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class PlanTier(str, PyEnum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"

class SyncFrequency(str, PyEnum):
    MONTHLY = "monthly"
    WEEKLY = "weekly"
    DAILY = "daily"
    REALTIME = "realtime"

PLAN_CONFIG = {
    PlanTier.FREE: {"price_monthly": 0.00, "sync_frequency": SyncFrequency.MONTHLY, "max_accounts": 1, "label": "Free"},
    PlanTier.STARTER: {"price_monthly": 5.99, "sync_frequency": SyncFrequency.WEEKLY, "max_accounts": 3, "label": "Starter"},
    PlanTier.PRO: {"price_monthly": 19.99, "sync_frequency": SyncFrequency.DAILY, "max_accounts": 10, "label": "Pro"},
    PlanTier.BUSINESS: {"price_monthly": 39.99, "sync_frequency": SyncFrequency.REALTIME, "max_accounts": 999, "label": "Business"},
}

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    plan = Column(Enum(PlanTier), default=PlanTier.FREE)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    bank_accounts = relationship("BankAccount", back_populates="user", cascade="all, delete")
    sync_logs = relationship("SyncLog", back_populates="user", cascade="all, delete")

class BankAccount(Base):
    __tablename__ = "bank_accounts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    connector_id = Column(String, nullable=False)
    plaid_access_token_enc = Column(Text, nullable=False)
    plaid_account_id = Column(String, nullable=False)
    account_label = Column(String, nullable=True)
    wave_account_name = Column(String, default="Bank")
    is_active = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="bank_accounts")
    sync_logs = relationship("SyncLog", back_populates="bank_account", cascade="all, delete")

class SyncLog(Base):
    __tablename__ = "sync_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False)
    status = Column(String, default="pending")
    transactions_synced = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    user = relationship("User", back_populates="sync_logs")
    bank_account = relationship("BankAccount", back_populates="sync_logs")

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
