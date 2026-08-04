from datetime import time
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float

class ICTEngine:
    def __init__(self, use_kill_zones: bool = True):
        self.use_kill_zones = use_kill_zones
        # 紐約開盤 Kill Zone (美東 08:30 - 11:30)
        self.ny_am_start = time(8, 30)
        self.ny_am_end = time(11, 30)
        # 紐約午後 Kill Zone (美東 13:30 - 16:00)
        self.ny_pm_start = time(13, 30)
        self.ny_pm_end = time(16, 0)

    def is_in_kill_zone(self, current_time: time) -> bool:
        """Check if current timestamp falls within ICT Kill Zones."""
        if not self.use_kill_zones:
            return True
        
        in_am_zone = self.ny_am_start <= current_time <= self.ny_am_end
        in_pm_zone = self.ny_pm_start <= current_time <= self.ny_pm_end
        
        return in_am_zone or in_pm_zone

    def detect_fvg(self, candles: List[Candle]) -> Optional[dict]:
        """
        Detect Fair Value Gap across a 3-candle sequence.
        Bullish FVG: Candle 1 High < Candle 3 Low
        Bearish FVG: Candle 1 Low > Candle 3 High
        """
        if len(candles) < 3:
            return None

        c1, c2, c3 = candles[-3], candles[-2], candles[-1]

        # Bullish Fair Value Gap
        if c3.low > c1.high:
            return {
                "type": "BULLISH_FVG",
                "gap_bottom": c1.high,
                "gap_top": c3.low,
                "gap_size": c3.low - c1.high
            }

        # Bearish Fair Value Gap
        if c3.high < c1.low:
            return {
                "type": "BEARISH_FVG",
                "gap_bottom": c3.high,
                "gap_top": c1.low,
                "gap_size": c1.low - c3.high
            }

        return None
