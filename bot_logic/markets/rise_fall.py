# bot_logic/markets/rise_fall.py
from .base_market import MarketStrategy

class RiseFallStrategy(MarketStrategy):
    def get_prediction_string(self):
        return self.config["direction"].upper()  # "RISE" or "FALL"

    def evaluate_result(self, price_diff: float) -> bool:
        if self.config["direction"].upper() == "RISE":
            return price_diff > 0
        elif self.config["direction"].upper() == "FALL":
            return price_diff < 0
        return False
