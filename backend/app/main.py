import os
import sys
import time
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# Load credentials securely from backend/.env
env_path = os.path.join(os.path.dirname(__file__), "../.env")
load_dotenv(dotenv_path=env_path)

from app.services.risk_manager import RiskManager, RiskViolationError
from app.services.ict_engine import ICTEngine
from app.services.projectx_client import ProjectXClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("topstepx_bot")

app = FastAPI(
    title="TopstepX Trading Bot API",
    description="Backend Engine & Terminal for TopstepX ProjectX Gateway Integration",
    version="1.0.0"
)

# Enable CORS for Frontend Dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

risk_manager = RiskManager(max_daily_loss=1000.0, max_contracts=5)
ict_engine = ICTEngine(use_kill_zones=True)

# Initialize ProjectX Gateway Client with environment credentials
api_key = os.getenv("TOPSTEPX_API_KEY", "")
username = os.getenv("TOPSTEPX_USERNAME", "hick3129")
base_url = os.getenv("PROJECTX_BASE_URL", "https://api.topstepx.com")

projectx_client = ProjectXClient(base_url=base_url)

@app.on_event("startup")
async def startup_event():
    """Non-blocking background startup task."""
    logger.info("TopstepX Hybrid Engine STARTED & Listening on http://127.0.0.1:8000")
    if api_key and username:
        asyncio.create_task(projectx_client.authenticate(username=username, api_key=api_key))

class WebhookSignal(BaseModel):
    account_id: str
    ticker: str
    action: str  # BUY / SELL
    contracts: int = 1
    stop_loss: float
    take_profit: Optional[float] = None
    passcode: Optional[str] = None

class RiskConfigUpdate(BaseModel):
    max_daily_loss: float
    max_contracts: int

class ManualOverrideUpdate(BaseModel):
    enabled: bool

# Locate frontend directory robustly
possible_frontend_paths = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend")),
    r"c:\Users\CYC\Desktop\Antigravity工作區\topstepx-trading-app\frontend"
]

frontend_path = None
for path in possible_frontend_paths:
    if os.path.exists(os.path.join(path, "index.html")):
        frontend_path = path
        break

if frontend_path:
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

@app.get("/")
def read_root():
    if frontend_path:
        index_file = os.path.join(frontend_path, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
    return {"status": "ONLINE", "message": "TopstepX Terminal Frontend"}

@app.get("/api/v1/health")
def get_health():
    return {
        "status": "ONLINE",
        "system": "TopstepX Hybrid Trading Engine",
        "api_connected": projectx_client.is_connected,
        "is_locked": risk_manager.is_locked,
        "manual_override": risk_manager.manual_override
    }

@app.get("/api/v1/accounts")
async def get_user_accounts(only_active: bool = Query(True, description="Filter only active trading accounts vs all historical accounts")):
    """Fetch REAL TopstepX trading accounts owned by user directly from ProjectX API."""
    if not projectx_client.jwt_token and username and api_key:
        await projectx_client.authenticate(username=username, api_key=api_key)
    accounts = await projectx_client.fetch_user_accounts(only_active=only_active)
    return accounts

@app.post("/api/v1/accounts/refresh")
async def refresh_user_accounts(only_active: bool = Query(True, description="Filter only active trading accounts vs all historical accounts")):
    """Trigger real re-authentication and fetch fresh real accounts from TopstepX."""
    success = await projectx_client.authenticate(username=username, api_key=api_key)
    accounts = await projectx_client.fetch_user_accounts(only_active=only_active)
    return {"status": "SUCCESS" if success else "FAILED", "accounts": accounts}

@app.get("/api/v1/market/bars")
async def get_projectx_market_bars(
    symbol: str = Query("NQ", description="Futures Symbol e.g. NQ, MNQ, ES"),
    timeframe: str = Query("1m", description="Timeframe e.g. 1m, 5m, 1h"),
    limit: int = Query(100, description="Number of bars")
) -> List[Dict[str, Any]]:
    raw_bars = await projectx_client.get_market_bars(symbol=symbol, timeframe=timeframe, limit=limit)
    
    if not raw_bars:
        now = int(time.time())
        step = 60 if timeframe == "1m" else 300
        base_price = 19500.0
        mock_bars = []
        for i in range(limit, 0, -1):
            t = now - i * step
            o = base_price + (i % 7 - 3.5) * 1.5
            h = o + (i % 5) * 2.0
            l = o - (i % 4) * 1.8
            c = (o + h + l) / 3
            mock_bars.append({
                "time": t,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": 120 + (i % 30) * 5
            })
        return mock_bars
    
    return raw_bars

@app.get("/api/v1/risk/status")
def get_risk_status():
    return {
        "max_daily_loss": risk_manager.max_daily_loss,
        "max_contracts": risk_manager.max_contracts,
        "is_locked": risk_manager.is_locked,
        "manual_override": risk_manager.manual_override
    }

@app.post("/api/v1/risk/config")
def update_risk_config(config: RiskConfigUpdate):
    risk_manager.max_daily_loss = config.max_daily_loss
    risk_manager.max_contracts = config.max_contracts
    return {"status": "SUCCESS", "message": "Risk limits updated successfully."}

@app.post("/api/v1/risk/manual-override")
def toggle_manual_override(update: ManualOverrideUpdate):
    risk_manager.set_manual_override(update.enabled)
    return {"status": "SUCCESS", "manual_override": risk_manager.manual_override}

@app.post("/api/v1/webhook")
async def receive_tradingview_webhook(signal: WebhookSignal):
    """Receive TradingView Webhook Signal and execute Server-side OCO protected trade."""
    if risk_manager.manual_override:
        return {"status": "SKIPPED", "reason": "Manual Priority Mode is active. Bot trade skipped."}

    try:
        # 1. Risk Manager Pre-trade Validation
        risk_manager.validate_order(
            contracts=signal.contracts,
            side=signal.action,
            stop_loss_price=signal.stop_loss
        )

        target_acc = signal.account_id

        # 2. Send OCO Order to TopstepX Gateway
        result = await projectx_client.place_order_with_oco(
            account_id=target_acc,
            contract_symbol=signal.ticker,
            side=signal.action,
            quantity=signal.contracts,
            order_type="MARKET",
            stop_loss_price=signal.stop_loss,
            take_profit_price=signal.take_profit
        )

        return {"status": "EXECUTED", "trade": result}

    except RiskViolationError as rve:
        raise HTTPException(status_code=400, detail=str(rve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Order execution error: {e}")
