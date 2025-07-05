# bot_logic/markets/even_odd.py

from .base_market import MarketStrategy

class EvenOddStrategy(MarketStrategy):
    def get_prediction_string(self):
        return f"DIGIT{self.config['value'].upper()}"

    def evaluate_result(self, last_digit: int) -> bool:
        if self.config["value"] == "even":
            return last_digit % 2 == 0
        elif self.config["value"] == "odd":
            return last_digit % 2 == 1
        return False
