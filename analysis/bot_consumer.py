### analysis/bot_consumer.py  

import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from bot_logic.bot_core import run_bot_for_user
import logging

logger = logging.getLogger(__name__)

class BotConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot_task = None
        self.stop_event = None

    async def connect(self):
        if not self.scope["user"].is_authenticated:
            await self.close()
            return

        await self.accept()
        # await self.send(json.dumps({"message": "Bot WebSocket connected."}))
        await self.send(json.dumps({"message": "Bot connected."}))

    async def disconnect(self, close_code):
        if self.bot_task:
            self.stop_event.set()
            self.bot_task.cancel()
            try:
                await self.bot_task
            except asyncio.CancelledError:
                pass
            logger.info(f"[BotConsumer] Bot stopped for user {self.scope['user'].id}.")

    async def receive(self, text_data):
        data = json.loads(text_data)
        cmd = data.get("command")

        if cmd == "start_bot":
            if self.bot_task and not self.bot_task.done():
                return await self.send(json.dumps({"message": "Bot already running."}))
            self.stop_event = asyncio.Event()
            async def send_update(u):
                await self.send(json.dumps(u))
            self.bot_task = asyncio.create_task(
                run_bot_for_user(self.scope["user"].id, self.stop_event, send_update)
            )
            await self.send(json.dumps({"message": "Bot started."}))

        elif cmd == "stop_bot":
            if self.bot_task:
                self.stop_event.set()
                self.bot_task.cancel()
                try:
                    await self.bot_task
                except asyncio.CancelledError:
                    pass
                await self.send(json.dumps({"message": "Bot stopped."}))
            else:
                await self.send(json.dumps({"message": "Bot not running."}))

        else:
            await self.send(json.dumps({"error": "Unknown command."}))
