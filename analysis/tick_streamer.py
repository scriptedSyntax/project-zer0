# analysis/tick_streamer.py

import asyncio
from collections import deque, Counter
from asgiref.sync import sync_to_async

from .utils import get_live_ticks
from user_config.models import UserProfile
from .tick_analyzer import TickAnalyzer


class LiveTickStreamer:
    """
    Streams live tick data, analyzes it, and sends updates via a callback.
    """

    def __init__(self, user, send_callback, symbol="R_50", last_x_ticks=50):
        self.user = user
        self.send_callback = send_callback
        self.symbol = symbol
        self.last_x_ticks = last_x_ticks

        self.running = False
        self.task = None

        self.tick_history = deque(maxlen=self.last_x_ticks)
        self.tick_times = deque(maxlen=self.last_x_ticks)

        self.analyzer = TickAnalyzer(last_x_ticks=self.last_x_ticks)

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def run(self):
        user_profile = await sync_to_async(UserProfile.objects.get)(user=self.user)
        deriv_token = user_profile.deriv_token

        print(f"[LiveTickStreamer] Starting live stream for {self.user.username} on {self.symbol}")

        try:
            async for tick in get_live_ticks(deriv_token, self.symbol):
                if not self.running:
                    break

                last_digit = tick["last_digit"]
                timestamp = tick["epoch"]

                self.tick_history.append(last_digit)
                self.tick_times.append(timestamp)

                # Frequency counts
                digit_counter = Counter(self.tick_history)
                even_count = sum(digit_counter[d] for d in range(0, 10, 2))
                odd_count = sum(digit_counter[d] for d in range(1, 10, 2))

                analysis_result = self.analyzer.analyze_last_digits(
                    self.tick_history, self.tick_times
                )
                volatility_value = self.analyzer.extract_volatility(self.symbol)

                await self.send_callback({
                    "type": "analysis_update",
                    "tick": tick,
                    "last_digit": last_digit,
                    "history_size": len(self.tick_history),
                    "top_5_last_digits": analysis_result["top_5"],
                    "recommended_timer": analysis_result["recommended_timer"],
                    "average_time_diff": analysis_result["average_time_diff"],
                    "volatility_value": volatility_value,

                    # ✅ Include digit frequency/weight data
                    "digit_counts": {
                        "even": even_count,
                        "odd": odd_count,
                        "frequency": dict(digit_counter)
                    }
                })

                await asyncio.sleep(1)  # Throttle to avoid overwhelming the WebSocket

        except Exception as e:
            print(f"[ERROR] LiveTickStreamer.run: {e}")

        finally:
            print(f"[LiveTickStreamer] Stream stopped for {self.user.username}")
            self.running = False
            self.task = None
