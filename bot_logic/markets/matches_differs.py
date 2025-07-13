# bot_logic/markets/matches_differs.py

class MatchesDiffersStrategy:
    def __init__(self, config):
        self.market_type = config.get("value")  # "matches" or "differs"
        self.target_digit = config.get("target_digit")
        self.recovery_threshold = config.get("recovery_threshold", None)
        self.use_recovery = False  # Default to off; set dynamically in bot_core

    def get_prediction_string(self):
        digit = self.recovery_threshold if self.use_recovery and self.recovery_threshold is not None else self.target_digit

        if self.market_type == "matches":
            return f"DIGIT_MATCH_{digit}"
        elif self.market_type == "differs":
            return f"DIGIT_DIFF_{digit}"
        else:
            raise ValueError(f"Invalid market type: {self.market_type}")

    def evaluate_result(self, last_digit):
        if self.use_recovery and self.recovery_threshold is not None:
            expected_digit = int(self.recovery_threshold)
        else:
            expected_digit = int(self.target_digit)

        if self.market_type == "matches":
            return last_digit == expected_digit
        elif self.market_type == "differs":
            return last_digit != expected_digit
        return False
