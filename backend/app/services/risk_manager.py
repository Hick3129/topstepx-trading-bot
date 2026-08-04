class RiskViolationError(Exception):
    """Exception raised when a trade violates risk management rules."""
    pass

class RiskManager:
    def __init__(self, max_daily_loss: float = 1000.0, max_contracts: int = 5):
        self.max_daily_loss = max_daily_loss
        self.max_contracts = max_contracts
        self.is_locked = False
        self.manual_override = False

    def set_manual_override(self, enabled: bool):
        """Toggle manual priority mode to avoid bot conflict with manual trades."""
        self.manual_override = enabled

    def check_pnl(self, current_daily_loss: float) -> dict:
        """Check current daily PnL against 80% warning and 95% hard lock thresholds."""
        if self.is_locked:
            raise RiskViolationError("Trading is LOCKED due to prior Max Daily Loss violation.")

        loss_ratio = current_daily_loss / self.max_daily_loss if self.max_daily_loss > 0 else 0

        if loss_ratio >= 0.95:
            self.is_locked = True
            raise RiskViolationError(f"HARD LOCK TRIGGERED: Daily loss (${current_daily_loss}) reached 95% threshold (${self.max_daily_loss * 0.95}). Force Liquidating all positions.")
        
        if loss_ratio >= 0.80:
            return {
                "status": "WARNING",
                "ratio": loss_ratio,
                "message": f"Caution: Daily loss (${current_daily_loss}) reached {loss_ratio * 100:.1f}% of daily limit."
            }
        
        return {"status": "OK", "ratio": loss_ratio, "message": "Risk parameters within normal bounds."}

    def validate_order(self, contracts: int, side: str, stop_loss_price: float = None):
        """Validate order parameters against contract limits and mandatory OCO stop loss requirement."""
        if self.is_locked:
            raise RiskViolationError("Cannot place order: Trading account is LOCKED.")
        
        if contracts > self.max_contracts:
            raise RiskViolationError(f"Contract limit exceeded: Requested {contracts}, Max allowed is {self.max_contracts}.")
        
        if stop_loss_price is None:
            raise RiskViolationError("Server-side OCO stop loss is required for all orders.")

        return True
