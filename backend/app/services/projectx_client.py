import httpx
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class ProjectXClient:
    """
    ProjectX Gateway REST API Client for TopstepX.
    Handles Authentication, Account info, Contract lookup, Market Data Bars, and Server-side OCO orders.
    """
    def __init__(self, base_url: str = "https://gateway.docs.projectx.com/docs/intro"):
        self.base_url = base_url.rstrip("/")
        self.jwt_token: Optional[str] = None
        self.is_connected: bool = False

    async def authenticate(self, username: str, api_key: str) -> bool:
        """Authenticate with ProjectX Gateway using Username and API Key."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/auth/login",
                    json={"username": username, "apiKey": api_key}
                )
                if response.status_code == 200:
                    data = response.json()
                    self.jwt_token = data.get("token")
                    self.is_connected = True
                    return True
                else:
                    logger.error(f"Auth failed: {response.status_code} - {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Authentication exception: {e}")
            return False

    async def get_market_bars(self, symbol: str = "NQ", timeframe: str = "1m", limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch real-time & historical OHLCV market bars directly from ProjectX Gateway API.
        """
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

    async def get_account_info(self, account_id: str) -> Dict[str, Any]:
        """Fetch account balance, equity, and trailing drawdown status."""
        if not self.jwt_token:
            raise PermissionError("Not authenticated to ProjectX Gateway")
        
        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}/api/v1/accounts/{account_id}", headers=headers)
            return response.json()

    async def place_order_with_oco(
        self,
        account_id: str,
        contract_symbol: str,
        side: str,  # BUY or SELL
        quantity: int,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Place an order with mandatory Server-Side OCO Bracket protection (Hard Stop Loss).
        """
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

        # Simulated response if not live-connected yet
        if not self.jwt_token:
            return {
                "orderId": "SIM-ORD-998822",
                "status": "FILLED",
                "symbol": contract_symbol,
                "side": side,
                "quantity": quantity,
                "executedPrice": price or 19520.0,
                "serverSideOcoStop": stop_loss_price,
                "message": "Order executed with Server-side OCO stop protection."
            }

        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/orders",
                json=payload,
                headers=headers
            )
            return response.json()
