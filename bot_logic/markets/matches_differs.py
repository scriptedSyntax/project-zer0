class MatchesDiffersStrategy:
    def __init__(self, config):
        self.market_type = config.get("value")  # "matches" or "differs"
        self.target_digit = config.get("target_digit")

    def get_prediction_string(self):
        if self.market_type == "matches":
            return f"DIGIT_MATCH_{self.target_digit}"
        elif self.market_type == "differs":
            return f"DIGIT_DIFF_{self.target_digit}"
        else:
            raise ValueError(f"Invalid market type: {self.market_type}")

    def evaluate_result(self, last_digit):
        if self.market_type == "matches":
            return int(last_digit) == int(self.target_digit)
        elif self.market_type == "differs":
            return int(last_digit) != int(self.target_digit)
        return False
