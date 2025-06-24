from collections import Counter  # For counting occurrences of last digits

class TickAnalyzer:
    """
    Class to analyze recent tick data, focusing on last digit statistics,
    timing between ticks, and extracting volatility info from symbol names.
    """

    def __init__(self, last_x_ticks=50):
        """
        Initialize the analyzer with the number of recent ticks to consider.

        Args:
            last_x_ticks (int): Number of most recent ticks to analyze.
        """
        self.last_x_ticks = last_x_ticks

    def analyze_last_digits(self, tick_history, tick_times):
        """
        Analyze the distribution of last digits from tick history and
        calculate timing metrics.

        Args:
            tick_history (deque or list): Recent last digits of ticks.
            tick_times (deque or list): Corresponding timestamps (epoch seconds).

        Returns:
            dict: Analysis results containing:
                - top_5: Top 5 most frequent digits with stats
                - recommended_timer: Suggested wait time based on digit dominance
                - average_time_diff: Average seconds between ticks formatted as HH:MM:SS
        """
        if not tick_history:
            return {
                "top_5": [],
                "recommended_timer": "00:00:00",
                "average_time_diff": "00:00:00",
            }

        counter = Counter(tick_history)
        total_ticks = len(tick_history)

        top_5 = sorted(counter.items(), key=lambda x: (-x[1], x[0]))[:5]

        formatted_top_5 = []
        for idx, (digit, count) in enumerate(top_5, start=1):
            percent = (count / total_ticks) * 100
            formatted_top_5.append({
                "rank": idx,
                "digit": digit,
                "percent": round(percent, 2),
                "count": count
            })

        dominant_percent = formatted_top_5[0]["percent"] if formatted_top_5 else 0

        if dominant_percent >= 40:
            recommended_seconds = 15
        elif dominant_percent >= 30:
            recommended_seconds = 10
        else:
            recommended_seconds = 5

        time_diffs = [
            tick_times[i] - tick_times[i - 1]
            for i in range(1, len(tick_times))
        ]
        avg_time_diff_sec = sum(time_diffs) / len(time_diffs) if time_diffs else 0

        return {
            "top_5": formatted_top_5,
            "recommended_timer": self.format_seconds(recommended_seconds),
            "average_time_diff": self.format_seconds(avg_time_diff_sec),
        }

    def extract_volatility(self, symbol):
        """
        Extract volatility value from the symbol string.
        E.g., for "R_50", returns 50.

        Args:
            symbol (str): Market symbol like "R_50".

        Returns:
            int or None: Extracted volatility number or None if parsing fails.
        """
        try:
            return int(symbol.split("_")[1])
        except (IndexError, ValueError):
            return None

    @staticmethod
    def format_seconds(total_seconds):
        """
        Convert a number of seconds into a formatted string HH:MM:SS.

        Args:
            total_seconds (int or float): Number of seconds to format.

        Returns:
            str: Time formatted as "HH:MM:SS"
        """
        total_seconds = int(total_seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
