# bot_logic/markets/even_odd.py

from .base_market import MarketStrategy

class EvenOddStrategy(MarketStrategy):
    def __init__(self, config):
        super().__init__(config)
        self.use_recovery = False
        self.recovery_value = config.get("recovery_threshold", None)  # must be 'even' or 'odd'

    def get_prediction_string(self):
        value = self.recovery_value if self.use_recovery and self.recovery_value else self.config["value"]
        return f"DIGIT{value.upper()}"

    def evaluate_result(self, last_digit: int) -> bool:
        value = self.recovery_value if self.use_recovery and self.recovery_value else self.config["value"]
        if value == "even":
            return last_digit % 2 == 0
        elif value == "odd":
            return last_digit % 2 == 1
        return False
