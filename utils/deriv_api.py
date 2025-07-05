# utils/deriv_api.py

# -----------------------------------
# Import Libraries
# -----------------------------------

import asyncio  # For async programming
import websockets  # For WebSocket API communication
import json  # For JSON encoding/decoding
import time  # For sleep in monitor loop
from collections import deque  # For analyzer tick history

# Django/Channels imports
from channels.generic.websocket import AsyncWebsocketConsumer
from user_config.models import UserProfile
# from utils.deriv_api import get_account_balance
from asgiref.sync import sync_to_async

from bot_logic.balance_manager import get_balance_manager

# -----------------------------------
# Global Constants
# -----------------------------------

# Deriv WebSocket API URL (demo app_id 1089)
DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=84524"

# -----------------------------------
# Utility Function: Get Account Balance
# -----------------------------------

async def get_account_balance(token):
    """
    Get account balance using the centralized balance manager.
    Returns: (balance, currency)
    """
    manager = await get_balance_manager(token)
    return await manager.get_current_balance()


class DerivAPI:
    """
    Minimal async Deriv WebSocket wrapper: supports DIGITEVEN, DIGITODD
    """
# This class provides methods to connect to Deriv WebSocket API, subscribe to ticks,

    def __init__(self, token):
        self.token = token
        self.ws = None
        self.subscriptions = {}

    async def connect(self):
        self.ws = await websockets.connect(DERIV_WS_URL)
        await self._authorize()

    async def _authorize(self):
        await self._send({"authorize": self.token})
        response = await self._recv()
        if "error" in response:
            raise Exception(f"Authorization failed: {response['error']['message']}")
        print("✅ Authorized with Deriv API.")

    async def subscribe_ticks(self, symbol):
        await self._send({"ticks": symbol, "subscribe": 1})
        response = await self._recv()
        if "error" in response:
            raise Exception(f"Subscribe failed: {response['error']['message']}")
        subscription_id = response["tick"]["id"]
        self.subscriptions[symbol] = subscription_id
        print(f"✅ Subscribed to {symbol} (ID: {subscription_id})")
        return subscription_id

        
        async def propose_contract(self, symbol, stake, contract_type, duration=1):
            payload = {
                "proposal": 1,
                "amount": stake,
                "basis": "stake",
                "currency": "USD",
                "duration": duration,
                "duration_unit": "t",
                "symbol": symbol
            }

            # ✅ Parse 'over' and 'under' with thresholds
            if contract_type.startswith("DIGIT_OVER_") or contract_type.startswith("DIGIT_UNDER_"):
                # e.g., DIGIT_OVER_5 → contract_type=DIGITOVER, barrier=5
                parts = contract_type.split("_")
                if len(parts) == 3:
                    payload["contract_type"] = f"DIGIT{parts[1].upper()}"
                    payload["barrier"] = parts[2]
                else:
                    raise ValueError(f"Invalid contract_type format: {contract_type}")

            # ✅ Support even_odd predictions
            elif contract_type in ["DIGITEVEN", "DIGITODD"]:
                payload["contract_type"] = contract_type

            else:
                raise ValueError(f"Unsupported contract type: {contract_type}")

            logger.info(f"📨 Sending contract proposal: {payload}")
            resp = await self._send_request(payload)
            p = resp.get("proposal")

            if not p:
                logger.error(f"❌ Proposal failed, full response: {resp}")
                raise Exception("Proposal failed, no 'proposal' in response.")

            logger.info(f"✅ Proposal received: id={p['id']}, ask_price={p['ask_price']}")
            return {"proposal_id": p["id"], "ask_price": p["ask_price"]}

    
    async def unsubscribe(self, subscription_id):
        await self._send({"forget": subscription_id})
        await self._recv()
        print(f"✅ Unsubscribed from {subscription_id}")

    async def _send(self, msg):
        await self.ws.send(json.dumps(msg))

    async def _recv(self):
        return json.loads(await self.ws.recv())

    async def close(self):
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                print(f"[WARN] WebSocket close failed: {e}")
            print("✅ WebSocket closed.")



# # -----------------------------------
# Real-Time Analysis WebSocket Consumer
# -----------------------------------

# Lazy import analyzer
def get_analyzer():
    from analysis.logic_engine import RealTimeAnalyzer
    return RealTimeAnalyzer

class AnalysisConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time analysis with balance updates.
    """

    async def connect(self):
        """
        On WebSocket connect.
        """
        self.user = self.scope["user"]

        if not self.user.is_authenticated:
            await self.close()
            return

        RealTimeAnalyzer = get_analyzer()
        self.analyzer = RealTimeAnalyzer(self.user, self.send_update)
        self.balance_task = None

        await self.accept()
        await self.send(json.dumps({"message": "WebSocket connected to analysis"}))

    async def disconnect(self, close_code):
        """
        On WebSocket disconnect.
        """
        try:
            await self.analyzer.stop()
        except Exception as e:
            print(f"[WARN] Cleanup error: {e}")

        if self.balance_task:
            self.balance_task.cancel()
            try:
                await self.balance_task
            except asyncio.CancelledError:
                print("[Balance Loop] Cancelled on disconnect")

    async def receive(self, text_data):
        """
        On message received from client.
        """
        data = json.loads(text_data)
        command = data.get("command")

        if command == "start_analysis":
            new_symbol = data.get("symbol", "R_50")
            new_last_x_ticks = data.get("last_x_ticks", 50)

            await self.analyzer.stop()

            self.analyzer.symbol = new_symbol
            self.analyzer.last_x_ticks = new_last_x_ticks
            self.analyzer.tick_history = deque(maxlen=new_last_x_ticks)
            self.analyzer.tick_times = deque(maxlen=new_last_x_ticks)

            await self.analyzer.start()

            if self.balance_task:
                self.balance_task.cancel()
                try:
                    await self.balance_task
                except asyncio.CancelledError:
                    pass

            self.balance_task = asyncio.create_task(self.send_balance_loop())
            await self.send(json.dumps({"message": "Analysis started"}))

        elif command == "stop_analysis":
            await self.analyzer.stop()
            await self.send(json.dumps({"message": "Analysis stopped"}))

            if self.balance_task:
                self.balance_task.cancel()
                try:
                    await self.balance_task
                except asyncio.CancelledError:
                    pass

        else:
            await self.send(json.dumps({"error": "Unknown command"}))

    async def send_update(self, update_data):
        """
        Sends real-time analyzer updates to client.
        """
        await self.send(json.dumps(update_data))

    async def send_balance_loop(self):
        """
        Continuously sends updated balance to client every 1 second.
        """
        try:
            user_profile = await sync_to_async(UserProfile.objects.get)(user=self.user)
            token = user_profile.deriv_token

            while True:
                try:
                    balance, currency = await get_account_balance(token)
                    await self.send(json.dumps({
                        "type": "balance_update",
                        "balance": balance,
                        "currency": currency
                    }))
                except Exception as e:
                    await self.send(json.dumps({
                        "type": "balance_update",
                        "error": str(e)
                    }))

                await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("[Balance Loop] Cancelled")

        except Exception as e:
            print(f"[ERROR] Balance loop crashed: {e}")
