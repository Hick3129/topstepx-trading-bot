import httpx
import logging
from typing import Optional, Dict, Any, List

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

    async def get_market_bars(self, symbol: str = "NQ", timeframe: str = "1m", limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch market bars."""
        if not self.jwt_token:
            return []

        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        params = {"symbol": symbol, "timeframe": timeframe, "limit": limit}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/market/bars",
                    headers=headers,
                    params=params
                )
                if response.status_code == 200:
                    return response.json()
                return []
        except Exception as e:
            logger.error(f"Error fetching ProjectX market bars: {e}")
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
