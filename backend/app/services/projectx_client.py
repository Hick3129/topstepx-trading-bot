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

    async def place_order(
        self,
        account_id: int,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        stop_loss_ticks: Optional[int] = None,
        take_profit_ticks: Optional[int] = None,
        custom_tag: str = "TopstepX-App"
    ) -> Dict[str, Any]:
        """
        Place an order using official endpoint POST /api/Order/place.
        Side: 0 = Bid (Buy), 1 = Ask (Sell)
        Type: 1=Limit, 2=Market, 3=StopLimit, 4=Stop, 5=TrailingStop, 6=JoinBid, 7=JoinAsk
        """
        contract_id = await self.resolve_contract_id(symbol)
        if not contract_id:
            logger.error(f"Cannot place order: unable to resolve contract ID for {symbol}")
            return {"success": False, "errorMessage": f"Contract {symbol} not found."}

        if not self.jwt_token:
            if self.username and self.api_key:
                await self.authenticate(self.username, self.api_key)
            if not self.jwt_token:
                return {"success": False, "errorMessage": "Not authenticated to TopstepX API."}

        # Map Side to integer
        side_upper = side.upper().strip()
        side_int = 0 if side_upper in ("BUY", "BID", "0", "LONG") else 1

        # Map Order Type to integer
        type_upper = order_type.upper().strip()
        type_map = {
            "LIMIT": 1, "MARKET": 2, "STOPLIMIT": 3, "STOP": 4,
            "TRAILINGSTOP": 5, "JOINBID": 6, "JOINASK": 7
        }
        type_int = type_map.get(type_upper, 2)

        payload = {
            "accountId": int(account_id),
            "contractId": contract_id,
            "type": type_int,
            "side": side_int,
            "size": int(quantity),
            "customTag": custom_tag
        }
        if limit_price is not None and type_int in (1, 3):
            payload["limitPrice"] = round(float(limit_price), 4)
        if stop_price is not None and type_int in (3, 4, 5):
            payload["stopPrice"] = round(float(stop_price), 4)

        if stop_loss_ticks and int(stop_loss_ticks) > 0:
            payload["stopLossBracket"] = {"ticks": int(stop_loss_ticks), "type": 4}  # Stop
        if take_profit_ticks and int(take_profit_ticks) > 0:
            payload["takeProfitBracket"] = {"ticks": int(take_profit_ticks), "type": 1}  # Limit

        headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
        try:
            logger.info(f"Placing order on TopstepX /api/Order/place: {payload}")
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(f"{self.base_url}/api/Order/place", json=payload, headers=headers)
                data = response.json() if response.text else {}
                if response.status_code in (200, 201) and data.get("success", True):
                    logger.info(f"✓ Order successfully placed on TopstepX: {data}")
                    return {"success": True, "orderId": data.get("orderId", "SUBMITTED"), "data": data}
                else:
                    err = data.get("errorMessage") or f"HTTP {response.status_code}: {response.text}"
                    logger.error(f"TopstepX order placement failed: {err}")
                    return {"success": False, "errorMessage": err, "data": data}
        except Exception as e:
            logger.error(f"Exception during TopstepX order placement: {e}")
            return {"success": False, "errorMessage": str(e)}

    async def get_open_positions(self, account_id: int) -> List[Dict[str, Any]]:
        """Fetch open positions for account via POST /api/Position/searchOpen."""
        if not self.jwt_token:
            return []
        headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/Position/searchOpen",
                    json={"accountId": int(account_id)},
                    headers=headers
                )
                if res.status_code == 200:
                    data = res.json()
                    return data.get("positions", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception as e:
            logger.error(f"Error fetching open positions for account {account_id}: {e}")
        return []

    async def get_open_orders(self, account_id: int) -> List[Dict[str, Any]]:
        """Fetch open orders for account via POST /api/Order/searchOpen."""
        if not self.jwt_token:
            return []
        headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/Order/searchOpen",
                    json={"accountId": int(account_id)},
                    headers=headers
                )
                if res.status_code == 200:
                    data = res.json()
                    return data.get("orders", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception as e:
            logger.error(f"Error fetching open orders for account {account_id}: {e}")
        return []

    async def get_recent_trades(self, account_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch real executed trades via POST /api/Trade/search."""
        if not self.jwt_token:
            return []
        headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
        start_ts = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/Trade/search",
                    json={"accountId": int(account_id), "startTimestamp": start_ts},
                    headers=headers
                )
                if res.status_code == 200:
                    data = res.json()
                    trades = data.get("trades", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    trades.sort(key=lambda x: x.get("creationTimestamp", ""), reverse=True)
                    return trades[:limit]
        except Exception as e:
            logger.error(f"Error fetching trades for account {account_id}: {e}")
        return []

    async def close_position(self, account_id: int, symbol: str) -> Dict[str, Any]:
        """Close an entire open position for a contract via POST /api/Position/closeContract."""
        contract_id = await self.resolve_contract_id(symbol)
        if not contract_id or not self.jwt_token:
            return {"success": False, "errorMessage": f"Could not resolve contract for {symbol} or not authenticated."}
        headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
        try:
            logger.info(f"Closing position on TopstepX for account {account_id}, contract {contract_id}...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/Position/closeContract",
                    json={"accountId": int(account_id), "contractId": contract_id},
                    headers=headers
                )
                if res.status_code in (200, 201):
                    logger.info("✓ Position closed successfully.")
                    return {"success": True, "message": f"Closed position for {symbol}."}
                else:
                    err = res.json().get("errorMessage") if res.text and res.text.startswith("{") else res.text
                    return {"success": False, "errorMessage": f"Failed to close position: {err}"}
        except Exception as e:
            return {"success": False, "errorMessage": str(e)}

    async def cancel_order(self, account_id: int, order_id: int) -> Dict[str, Any]:
        """Cancel an open order via POST /api/Order/cancel."""
        if not self.jwt_token:
            return {"success": False, "errorMessage": "Not authenticated."}
        headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/Order/cancel",
                    json={"accountId": int(account_id), "orderId": int(order_id)},
                    headers=headers
                )
                if res.status_code in (200, 201):
                    return {"success": True, "orderId": order_id}
                return {"success": False, "errorMessage": res.text}
        except Exception as e:
            return {"success": False, "errorMessage": str(e)}

    async def cancel_all_orders(self, account_id: int, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Cancel all open orders for an account, optionally filtered by symbol."""
        open_orders = await self.get_open_orders(account_id)
        if not open_orders:
            return {"success": True, "cancelled_count": 0, "message": "No open orders found."}
        
        target_contract = await self.resolve_contract_id(symbol) if symbol else None
        cancelled = 0
        for ord_item in open_orders:
            if target_contract and ord_item.get("contractId") != target_contract:
                continue
            oid = ord_item.get("id") or ord_item.get("orderId")
            if oid:
                res = await self.cancel_order(account_id, int(oid))
                if res.get("success"):
                    cancelled += 1
        return {"success": True, "cancelled_count": cancelled, "message": f"Cancelled {cancelled} orders."}

    async def flatten_all(self, account_id: int, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Flatten All: cancel all open orders and close all open positions for an account."""
        logger.info(f"FLATTEN ALL triggered for account {account_id} (symbol={symbol})...")
        # 1. Cancel orders
        cancel_res = await self.cancel_all_orders(account_id, symbol=symbol)
        
        # 2. Close open positions
        open_pos = await self.get_open_positions(account_id)
        target_contract = await self.resolve_contract_id(symbol) if symbol else None
        closed = 0
        for pos in open_pos:
            cid = pos.get("contractId")
            if not cid or (target_contract and cid != target_contract):
                continue
            # Use contractId directly or find inverse symbol
            headers = {"Authorization": f"Bearer {self.jwt_token}", "Content-Type": "application/json"}
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        f"{self.base_url}/api/Position/closeContract",
                        json={"accountId": int(account_id), "contractId": cid},
                        headers=headers
                    )
                closed += 1
            except Exception as e:
                logger.error(f"Error closing position {cid} during flatten: {e}")

        return {
            "success": True,
            "message": f"Flatten complete! Cancelled {cancel_res.get('cancelled_count', 0)} orders and closed {closed} positions."
        }
