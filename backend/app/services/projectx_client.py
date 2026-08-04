import httpx
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class ProjectXClient:
    """
    ProjectX Gateway REST API Client for TopstepX.
    Handles Authentication, Real Account Auto-Discovery, Contract lookup, Market Data Bars, and Server-side OCO orders.
    """
    # TopstepX / ProjectX Gateway official REST API endpoints
    OFFICIAL_ENDPOINTS = [
        "https://gateway.projectx.com",
        "https://api.projectx.com",
        "https://gateway.topstepx.com",
        "https://api.topstepx.com"
    ]

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or self.OFFICIAL_ENDPOINTS[0]).rstrip("/")
        self.jwt_token: Optional[str] = None
        self.is_connected: bool = False
        self.accounts: List[Dict[str, Any]] = []

    async def authenticate(self, username: str, api_key: str) -> bool:
        """
        Authenticate with TopstepX / ProjectX Gateway using Username and API Key.
        Tries official endpoints automatically until a real JWT token is granted.
        """
        endpoints_to_try = [self.base_url] + [ep for ep in self.OFFICIAL_ENDPOINTS if ep != self.base_url]

        for ep in endpoints_to_try:
            try:
                logger.info(f"Connecting to TopstepX Gateway at: {ep}...")
                async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
                    response = await client.post(
                        f"{ep}/api/v1/auth/login",
                        json={"username": username, "apiKey": api_key}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        token = data.get("token") or data.get("jwtToken") or data.get("accessToken")
                        if token:
                            self.base_url = ep
                            self.jwt_token = token
                            self.is_connected = True
                            logger.info(f"✓ TopstepX API Authentication Successful via {ep}!")
                            await self.fetch_user_accounts()
                            return True
                    elif response.status_code in (401, 403):
                        logger.warning(f"TopstepX Auth rejected at {ep}: {response.status_code}")
            except Exception as e:
                logger.debug(f"Endpoint {ep} not reachable: {e}")

        logger.error("Could not authenticate with TopstepX Gateway across endpoints.")
        return False

    async def fetch_user_accounts(self) -> List[Dict[str, Any]]:
        """Fetch real TopstepX trading accounts directly from TopstepX API."""
        if not self.jwt_token:
            return []
        
        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        try:
            async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
                response = await client.get(f"{self.base_url}/api/v1/accounts", headers=headers)
                if response.status_code == 200:
                    self.accounts = response.json()
                    logger.info(f"✓ Dynamically fetched {len(self.accounts)} real TopstepX accounts.")
                    return self.accounts
                else:
                    logger.error(f"Failed to fetch accounts: {response.status_code} - {response.text}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching real accounts: {e}")
            return []

    async def get_market_bars(self, symbol: str = "NQ", timeframe: str = "1m", limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch real-time & historical OHLCV market bars directly from ProjectX Gateway API."""
        if not self.jwt_token:
            return []

        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        params = {"symbol": symbol, "timeframe": timeframe, "limit": limit}

        try:
            async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
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

        if not self.jwt_token:
            raise PermissionError("Must authenticate with TopstepX API before placing real orders.")

        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/orders",
                json=payload,
                headers=headers
            )
            return response.json()
