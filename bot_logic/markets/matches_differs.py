# bot_logic/markets/matches_differs.py

class MatchesDiffersStrategy:
    def __init__(self, config):
        self.market_type = config.get("value")  # "matches" or "differs"
        self.target_digit = config.get("target_digit")
        self.recovery_threshold = config.get("recovery_threshold", None)
        self.use_recovery = False

        # 🚦 New state flags for core strategy workflow
        self.entry_triggered = False
        self.active_trading = False

    def get_prediction_string(self):
        digit = self.recovery_threshold if self.use_recovery and self.recovery_threshold is not None else self.target_digit

        if self.market_type == "matches":
            return f"DIGIT_MATCH_{digit}"
        elif self.market_type == "differs":
            return f"DIGIT_DIFF_{digit}"
        else:
            raise ValueError(f"Invalid market type: {self.market_type}")

    def should_trade(self, last_digit):
        """
        Implements entry → wait → active → reset on loss logic.
        """
        expected_digit = int(self.recovery_threshold if self.use_recovery and self.recovery_threshold is not None else self.target_digit)

        # 🛑 Not active yet: wait for entry signal
        if not self.active_trading:
            if not self.entry_triggered:
                if last_digit == expected_digit:
                    self.entry_triggered = True  # T1: matched, prepare to enter next tick
                return False  # Skip trading this tick
            else:
                # T2: next tick after match, begin trading
                self.active_trading = True
                self.entry_triggered = False
                return True
        else:
            return True  # ✅ Active trading phase

    def evaluate_result(self, last_digit):
        expected_digit = int(self.recovery_threshold if self.use_recovery and self.recovery_threshold is not None else self.target_digit)

        if self.market_type == "matches":
            is_win = last_digit == expected_digit
        elif self.market_type == "differs":
            is_win = last_digit != expected_digit
        else:
            is_win = False

        # ❌ If loss occurs during active trading, reset FSM
        if self.active_trading:
            if self.market_type == "matches" and last_digit == expected_digit:
                self.active_trading = False
            elif self.market_type == "differs" and last_digit != expected_digit:
                self.active_trading = False

        return is_win
