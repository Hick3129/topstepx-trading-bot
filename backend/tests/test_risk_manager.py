import pytest
from app.services.risk_manager import RiskManager, RiskViolationError

def test_risk_manager_initialization():
    risk_mgr = RiskManager(max_daily_loss=1000.0, max_contracts=5)
    assert risk_mgr.max_daily_loss == 1000.0
    assert risk_mgr.max_contracts == 5
    assert risk_mgr.is_locked is False

def test_risk_manager_80_percent_warning():
    risk_mgr = RiskManager(max_daily_loss=1000.0, max_contracts=5)
    warning = risk_mgr.check_pnl(current_daily_loss=850.0)
    assert warning["status"] == "WARNING"
    assert warning["ratio"] == 0.85

def test_risk_manager_95_percent_hard_lock():
    risk_mgr = RiskManager(max_daily_loss=1000.0, max_contracts=5)
    with pytest.raises(RiskViolationError):
        risk_mgr.check_pnl(current_daily_loss=960.0)
    assert risk_mgr.is_locked is True

def test_max_contracts_exceeded():
    risk_mgr = RiskManager(max_daily_loss=1000.0, max_contracts=2)
    with pytest.raises(RiskViolationError):
        risk_mgr.validate_order(contracts=3, side="BUY")

def test_server_side_oco_bracket_required():
    risk_mgr = RiskManager(max_daily_loss=1000.0, max_contracts=2)
    # Validate that every order MUST specify stop_loss_ticks or stop_loss_price
    with pytest.raises(RiskViolationError, match="Server-side OCO stop loss is required"):
        risk_mgr.validate_order(contracts=1, side="BUY", stop_loss_price=None)
