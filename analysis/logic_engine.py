# analysis/logic_engine.py

# Import the TickAnalyzer class from the tick_analyzer module
from .tick_analyzer import TickAnalyzer

class RealTimeAnalyzer:
    def __init__(self, symbol, bot_mode, last_x_ticks=10):
        """
        Initialize the RealTimeAnalyzer for processing ticks and deciding trade actions.

        Args:
            symbol (str): The trading symbol (e.g., "R_100").
            bot_mode (str): The trading strategy mode - either "even" or "odd".
            last_x_ticks (int): Number of recent ticks to consider for analysis.
        """
        self.symbol = symbol  # The market symbol this bot is trading on.
        self.bot_mode = bot_mode  # Strategy mode: "even" or "odd" (determines what to bet on).
        self.tick_history = []  # Stores the last N tick values (digits).
        self.tick_times = []  # Stores the timestamps of the corresponding ticks.
        self.analyzer = TickAnalyzer(last_x_ticks)  # Analyzer instance to evaluate digit patterns.

    def update_tick(self, new_tick, tick_time):
        """
        Update the tick history with the latest tick and evaluate whether to trade.

        Args:
            new_tick (int): The last digit from the latest market tick.
            tick_time (str): Timestamp when the tick was received.

        Returns:
            dict: Decision info with trade action or reason to wait.
        """
        # Append the new tick value and its timestamp
        self.tick_history.append(new_tick)
        self.tick_times.append(tick_time)

        # Ensure tick history does not exceed the configured window (last_x_ticks)
        if len(self.tick_history) > self.analyzer.last_x_ticks:
            self.tick_history.pop(0)     # Remove the oldest tick
            self.tick_times.pop(0)       # Remove the corresponding oldest timestamp

        # Decide whether to trade based on the updated tick history
        return self.should_trade()

    def should_trade(self):
        """
        Determine whether a trade should be placed based on analyzed digit patterns
        and the configured trading mode.

        Returns:
            dict: Contains action ("trade" or "wait"), trade contract (if any), 
                  confidence score, volatility level, tick time, and last digits analyzed.
        """
        # Check if we have enough data to perform analysis
        if len(self.tick_history) < self.analyzer.last_x_ticks:
            return {
                "action": "wait",
                "reason": "Not enough data"  # Wait until we collect enough ticks
            }

        # Analyze the last digits and get prediction and confidence
        result = self.analyzer.analyze_last_digits(self.tick_history, self.tick_times)
        predicted_digit = result["likely_next_digit"]  # The digit most likely to appear next

        # If no confident prediction was found, wait
        if predicted_digit is None:
            return {
                "action": "wait",
                "reason": "No clear digit pattern"  # Could not confidently predict a next digit
            }

        # Determine trade type based on bot strategy mode
        if self.bot_mode == "even":
            # If prediction is even, suggest trading EVEN; else, wait
            trade_type = "EVEN" if predicted_digit % 2 == 0 else "WAIT"
        elif self.bot_mode == "odd":
            # If prediction is odd, suggest trading ODD; else, wait
            trade_type = "ODD" if predicted_digit % 2 == 1 else "WAIT"
        else:
            # Invalid mode; no trade should be made
            trade_type = "WAIT"

        # Construct the decision dictionary
        return {
            "action": "trade" if trade_type in ["EVEN", "ODD"] else "wait",  # Only trade if prediction aligns with strategy
            "contract": trade_type if trade_type in ["EVEN", "ODD"] else None,  # Contract type to send to the bot
            "confidence": result["confidence"],  # Confidence score from the prediction model
            "volatility": self.analyzer.extract_volatility(self.symbol),  # Volatility level for logging or analysis
            "timestamp": self.tick_times[0],  # Timestamp of the latest tick
            "last_digits": result["last_digits"],  # Last digits analyzed
        }

    # Optional method to clear internal state (commented out for now)
    # def reset(self):
    #     """
    #     Reset the analyzer’s tick history and internal state.
    #     Useful when restarting or switching strategies.
    #     """
    #     self.tick_history = []  # Clear stored tick digits
    #     self.tick_times = []  # Clear corresponding timestamps
    #     self.analyzer.reset()  # Reset internal analyzer state
