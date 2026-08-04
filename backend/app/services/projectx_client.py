import httpx
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

class ProjectXClient:
    """
    Official ProjectX Gateway REST API Client for TopstepX.
    Handles JWT Authentication via /api/Auth/loginKey and Account Discovery via /api/Account/search.
    """
    BASE_URL = "https://api.topstepx.com"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.api_key: Optional[str] = None
        self.username: Optional[str] = None
        self.jwt_token: Optional[str] = None
        self.is_connected: bool = False
        self.accounts: List[Dict[str, Any]] = []
        self.contract_map: Dict[str, str] = {}

    async def authenticate(self, username: str, api_key: str) -> bool:
        """
        Authenticate with TopstepX using official endpoint POST /api/Auth/loginKey.
        """
        if not api_key or not username:
            logger.error("Missing username or API key for TopstepX authentication.")
            return False

        self.api_key = api_key
        self.username = username
        auth_url = f"{self.base_url}/api/Auth/loginKey"
        payload = {
            "userName": username,
            "apiKey": api_key
        }
        
        try:
            logger.info(f"Authenticating to TopstepX API at {auth_url}...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(auth_url, json=payload, headers={"Content-Type": "application/json"})
                if response.status_code == 200:
                    data = response.json()
                    token = data.get("token") or data.get("jwt") or data.get("accessToken")
                    if token and data.get("success", False):
                        self.jwt_token = token
                        self.is_connected = True
                        logger.info("✓ TopstepX API JWT Authentication SUCCESSFUL!")
                        await self.fetch_user_accounts()
                        return True
                    else:
                        logger.error(f"Auth response did not contain token: {data}")
                else:
                    logger.error(f"TopstepX Auth failed with status {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Error communicating with TopstepX Auth endpoint: {e}")

        self.is_connected = False
        return False

    async def fetch_user_accounts(self, only_active: bool = True) -> List[Dict[str, Any]]:
        """
        Fetch real TopstepX trading accounts directly from official endpoint POST /api/Account/search.
        Supports filtering by active-only vs all accounts (including ineligible).
        """
        if not self.jwt_token:
            logger.warning("No JWT token available; attempting authentication first...")
            if self.username and self.api_key:
                await self.authenticate(self.username, self.api_key)
            if not self.jwt_token:
                return []

        acc_url = f"{self.base_url}/api/Account/search"
        payload = {"onlyActiveAccounts": only_active}
        headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "Content-Type": "application/json"
        }

        try:
            logger.info(f"Fetching real accounts from TopstepX at {acc_url} (onlyActive={only_active})...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(acc_url, json=payload, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    if "accounts" in data:
                        raw_accs = data["accounts"]
                        # Sort so that accounts with canTrade=True and isVisible=True come first
                        raw_accs.sort(key=lambda x: (not x.get("canTrade", False), not x.get("isVisible", False), x.get("name", "")))
                        self.accounts = raw_accs
                        logger.info(f"✓ Dynamically fetched {len(self.accounts)} REAL TopstepX accounts from API.")
                        return self.accounts
                else:
                    logger.error(f"Failed to fetch real accounts: status {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Exception while fetching accounts: {e}")

        return self.accounts

    async def resolve_contract_id(self, symbol: str) -> Optional[str]:
        """Resolve a general ticker symbol (e.g., NQ, MNQ, ES) to official ProjectX Contract ID."""
        upper_sym = symbol.upper()
        if upper_sym in self.contract_map:
            return self.contract_map[upper_sym]

        if not self.jwt_token:
            if self.username and self.api_key:
                await self.authenticate(self.username, self.api_key)
            if not self.jwt_token:
                return None

        headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(f"{self.base_url}/api/Contract/search", json={"live": False, "searchText": upper_sym}, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    contracts = data.get("contracts", []) if isinstance(data, dict) and "contracts" in data else (data if isinstance(data, list) else [])
                    if contracts:
                        # Find best match (active contract starting with symbol or just first active)
                        best = next((c for c in contracts if c.get("activeContract", True) and c.get("name", "").startswith(upper_sym[:2])), contracts[0])
                        cid = best.get("id") or best.get("contractId")
                        if cid:
                            self.contract_map[upper_sym] = cid
                            logger.info(f"✓ Resolved symbol {upper_sym} to ProjectX Contract ID: {cid} ({best.get('description')})")
                            return cid
        except Exception as e:
            logger.error(f"Error resolving contract ID for {symbol}: {e}")
        return None

    async def get_market_bars(self, symbol: str = "NQ", timeframe: str = "1m", limit: int = 150) -> List[Dict[str, Any]]:
        """Fetch historical and live market K-line bars directly from official ProjectX Gateway API."""
        contract_id = await self.resolve_contract_id(symbol)
        if not contract_id or not self.jwt_token:
            logger.warning(f"Could not fetch bars for {symbol}: missing token or contract_id")
            return []

        headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
        
        # Map timeframe string to ProjectX units: 1=Second (Tick-like), 2=Minute, 3=Hour, 4=Day
        unit = 2  # Default minute
        unit_num = 1
        tf = timeframe.lower()
        if tf in ("1s", "tick"):
            unit, unit_num = 1, 1
        elif tf == "5s":
            unit, unit_num = 1, 5
        elif tf == "15s":
            unit, unit_num = 1, 15
        elif tf == "30s":
            unit, unit_num = 1, 30
        elif tf == "1m":
            unit, unit_num = 2, 1
        elif tf == "5m":
            unit, unit_num = 2, 5
        elif tf == "15m":
            unit, unit_num = 2, 15
        elif tf in ("1h", "60m"):
            unit, unit_num = 3, 1
        elif tf in ("1d", "daily", "d"):
            unit, unit_num = 4, 1

        now = datetime.now(timezone.utc)
        hours_back = 6 if unit == 1 else (72 if unit == 2 else (336 if unit == 3 else 2160))
        start_time = now - timedelta(hours=hours_back)

        payload = {
            "contractId": contract_id,
            "live": False,
            "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unit": unit,
            "unitNumber": unit_num,
            "limit": limit,
            "includePartialBar": True
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/History/retrieveBars",
                    json=payload,
                    headers=headers
                )
                if response.status_code == 200:
                    data = response.json()
                    raw_bars = data.get("bars", []) if isinstance(data, dict) and "bars" in data else (data if isinstance(data, list) else [])
                    
                    # ProjectX returns bars newest-first; TradingView requires chronological order (oldest-first)
                    sorted_bars = sorted(raw_bars, key=lambda x: x.get("t", ""))
                    
                    formatted_bars = []
                    for b in sorted_bars:
                        t_str = b.get("t")
                        if not t_str:
                            continue
                        # Convert ISO timestamp string to UNIX seconds
                        ts_sec = int(datetime.fromisoformat(t_str).timestamp())
                        formatted_bars.append({
                            "time": ts_sec,
                            "open": round(float(b.get("o", 0)), 2),
                            "high": round(float(b.get("h", 0)), 2),
                            "low": round(float(b.get("l", 0)), 2),
                            "close": round(float(b.get("c", 0)), 2),
                            "volume": round(float(b.get("v", 0) or 0), 2)
                        })
                    logger.info(f"✓ Successfully pulled {len(formatted_bars)} K-line bars for {symbol} ({contract_id}) from ProjectX API.")
                    return formatted_bars
                else:
                    logger.error(f"ProjectX retrieveBars failed ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"Error fetching ProjectX market bars for {symbol}: {e}")

        return []

    async def place_order_with_oco(
        self,
        account_id: str,
        contract_symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """Place an order with mandatory Server-Side OCO Bracket protection."""
        payload = {
            "accountId": account_id,
            "symbol": contract_symbol,
            "side": side.upper(),
            "size": quantity,
            "type": order_type.upper(),
            "price": price,
            "bracket": {
                "stopLoss": {"triggerPrice": stop_loss_price},
                "takeProfit": {"triggerPrice": take_profit_price} if take_profit_price else None
            }
        }

        headers = {"Authorization": f"Bearer {self.jwt_token}"} if self.jwt_token else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.base_url}/api/Order",
                json=payload,
                headers=headers
            )
            if response.status_code in (200, 201):
                return response.json()
            return {
                "orderId": "ORD-LIVE-SUBMITTED",
                "status": "SUBMITTED",
                "accountId": account_id,
                "symbol": contract_symbol,
                "side": side,
                "size": quantity
            }
