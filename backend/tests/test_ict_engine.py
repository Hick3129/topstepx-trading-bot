import pytest
from datetime import time
from app.services.ict_engine import ICTEngine, Candle

def test_kill_zone_filter():
    engine = ICTEngine()
    # 紐約開盤 Kill Zone (美東 08:30 - 11:30)
    assert engine.is_in_kill_zone(time(9, 30)) is True
    # 紐約午後 Kill Zone (美東 13:30 - 16:00)
    assert engine.is_in_kill_zone(time(14, 0)) is True
    # 非 Kill Zone (例如美東 12:15)
    assert engine.is_in_kill_zone(time(12, 15)) is False

def test_fvg_detection():
    engine = ICTEngine()
    # 建立 3 根 K 線 (Bullish FVG: Candle 1 High < Candle 3 Low)
    c1 = Candle(open=100.0, high=102.0, low=99.0, close=101.0, volume=1000)
    c2 = Candle(open=101.0, high=108.0, low=101.0, close=107.0, volume=3000) # 爆發推升
    c3 = Candle(open=107.0, high=109.0, low=104.0, close=108.0, volume=1500) # 最低點 104 > c1.high (102)

    fvg = engine.detect_fvg([c1, c2, c3])
    assert fvg is not None
    assert fvg["type"] == "BULLISH_FVG"
    assert fvg["gap_bottom"] == 102.0
    assert fvg["gap_top"] == 104.0
