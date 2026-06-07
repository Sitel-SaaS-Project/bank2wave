from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth import router as auth_router
from sync import router as sync_router
from billing import router as billing_router

app = FastAPI(title="bank2wave API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(sync_router, prefix="/sync", tags=["Sync"])
app.include_router(billing_router, prefix="/billing", tags=["Billing"])

@app.get("/health")
def health():
    return {"status": "ok", "service": "bank2wave"}
