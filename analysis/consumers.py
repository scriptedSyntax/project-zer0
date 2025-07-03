# analysis/consumers.py

import json
import asyncio

from collections import deque
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async

from user_config.models import UserProfile
from bot_logic.balance_manager import get_balance_manager
from .tick_streamer import LiveTickStreamer
from bot_logic.state_manager import is_bot_running
from bot_logic.bot_core import run_bot_for_user

class AnalysisConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.tick_streamer = None
        self.balance_manager = None
        self.bot_task = None
        self.bot_stop_event = None

    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close()
            return

        await self.accept()
        await self.send(json.dumps({"message": "WebSocket connected to analysis"}))

        # Set up balance manager
        try:
            user_profile = await sync_to_async(UserProfile.objects.get)(user=self.user)
            self.balance_manager = await get_balance_manager(user_profile.deriv_token)
            self.balance_manager.subscribe(self._on_balance_update)
            
            # Get initial balance
            balance, currency = await self.balance_manager.get_current_balance()
            if balance is not None:
                await self.send(json.dumps({
                    "type": "balance_update",
                    "balance": balance,
                    "currency": currency
                }))
        except Exception as e:
            print(f"[Balance Setup Error] {e}")

        # Check if bot is already running
        try:
            if is_bot_running(self.user.id):
                print("[Bot Status] Bot already running.")
        except Exception as e:
            print(f"[Bot Status Check Error] {e}")

    async def disconnect(self, close_code):
        if self.tick_streamer:
            await self.tick_streamer.stop()

        # Unsubscribe from balance updates
        if hasattr(self, 'balance_manager') and self.balance_manager:
            self.balance_manager.unsubscribe(self._on_balance_update)

        if self.bot_task:
            self.bot_stop_event.set()
            self.bot_task.cancel()
            try:
                await self.bot_task
            except asyncio.CancelledError:
                print("[Bot] Cancelled on disconnect")
            self.bot_task = None
            self.bot_stop_event = None

    async def _on_balance_update(self, balance_data):
        """Handle balance updates from the balance manager."""
        await self.send(json.dumps({
            "type": "balance_update",
            "balance": balance_data["balance"],
            "currency": balance_data["currency"]
        }))

    async def receive(self, text_data):
        data = json.loads(text_data)
        command = data.get("command")

        if command == "start_analysis":
            new_symbol = data.get("symbol", "R_50")
            new_last_x_ticks = data.get("last_x_ticks", 50)

            if self.tick_streamer:
                await self.tick_streamer.stop()

            self.tick_streamer = LiveTickStreamer(
                user=self.user,
                send_callback=self.send_update,
                symbol=new_symbol,
                last_x_ticks=new_last_x_ticks
            )

            await self.tick_streamer.start()
            await self.send(json.dumps({"message": "Analysis started"}))

        elif command == "stop_analysis":
            if self.tick_streamer:
                await self.tick_streamer.stop()
                self.tick_streamer = None

            await self.send(json.dumps({"message": "Analysis stopped"}))

        elif command == "start_bot":
            user_id = self.user.id
            bot_mode = data.get("bot_mode", "even")

            # Cancel existing bot if running
            if self.bot_task:
                self.bot_stop_event.set()
                self.bot_task.cancel()
                try:
                    await self.bot_task
                except asyncio.CancelledError:
                    pass
                self.bot_task = None
                self.bot_stop_event = None

            # New bot task and stop event
            self.bot_stop_event = asyncio.Event()
            self.bot_task = asyncio.create_task(
                run_bot_for_user(user_id, self.bot_stop_event, self.send_bot_update, bot_mode=bot_mode)
            )

            await self.send(json.dumps({
                "message": "Bot started.",
                "bot_running": True
            }))

        elif command == "stop_bot":
            if self.bot_task:
                self.bot_stop_event.set()
                self.bot_task.cancel()
                try:
                    await self.bot_task
                except asyncio.CancelledError:
                    pass
                self.bot_task = None
                self.bot_stop_event = None

            await self.send(json.dumps({
                "message": "Bot stopped.",
                "bot_running": False
            }))

        elif command == "bot_status":
            user_id = self.user.id
            running = is_bot_running(user_id)
            await self.send(json.dumps({
                "bot_running": running
            }))

        else:
            await self.send(json.dumps({"error": "Unknown command"}))

    async def send_update(self, update_data):
        await self.send(json.dumps(update_data))

    async def send_bot_update(self, update_data):
        await self.send(json.dumps({
            "type": "bot_update",
            "data": update_data
        }))
