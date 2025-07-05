# # bot_logic/markets/over_under.py

from .base_market import MarketStrategy

class OverUnderStrategy(MarketStrategy):
    def __init__(self, config):
        super().__init__(config)
        self.use_recovery = False  # toggled externally on loss

    def get_prediction_string(self):
        threshold = self.config["recovery_threshold"] if self.use_recovery else self.config["threshold"]
        return f"DIGIT_{self.config['type'].upper()}_{threshold}"

    def evaluate_result(self, last_digit: int) -> bool:
        threshold = self.config["recovery_threshold"] if self.use_recovery else self.config["threshold"]
        if self.config["type"] == "over":
            return last_digit > threshold
        elif self.config["type"] == "under":
            return last_digit < threshold
        return False
