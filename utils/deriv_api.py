# -----------------------------------
# Import Libraries
# -----------------------------------

import asyncio
import websockets
import json
import time
from collections import deque

# Django/Channels imports
from channels.generic.websocket import AsyncWebsocketConsumer
from user_config.models import UserProfile
from asgiref.sync import sync_to_async

# -----------------------------------
# Global Constants
# -----------------------------------

DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=81950"

# -----------------------------------
# Utility Function: Get Account Balance
# -----------------------------------

async def get_account_balance(token):
    print("[INFO] get_account_balance() called")
    async with websockets.connect(DERIV_WS_URL) as websocket:
        print("[INFO] Connected to WebSocket for balance")

        await websocket.send(json.dumps({"authorize": token}))
        print("[INFO] Authorization sent")

        auth_response = await websocket.recv()
        auth_data = json.loads(auth_response)
        print(f"[DEBUG] Auth response: {auth_data}")

        if "error" in auth_data:
            raise Exception(f"Authorization failed: {auth_data['error']['message']}")

        await websocket.send(json.dumps({"balance": 1}))
        print("[INFO] Balance request sent")

        balance_response = await websocket.recv()
        balance_data = json.loads(balance_response)
        print(f"[DEBUG] Balance response: {balance_data}")

        if "error" in balance_data:
            raise Exception(f"Balance request failed: {balance_data['error']['message']}")

        balance = balance_data["balance"]["balance"]
        currency = balance_data["balance"]["currency"]

        print(f"[INFO] Retrieved balance: {balance} {currency}")
        return balance, currency


class DerivAPI:
    def __init__(self, token):
        print("[INIT] DerivAPI initialized")
        self.token = token
        self.ws = None
        self.subscriptions = {}

    async def connect(self):
        print("[INFO] Connecting to Deriv WebSocket...")
        self.ws = await websockets.connect(DERIV_WS_URL)
        await self.authorize()

    async def authorize(self):
        print("[INFO] Sending authorization message")
        await self._send({"authorize": self.token})
        response = await self._recv()
        print(f"[DEBUG] Auth response: {response}")
        if "error" in response:
            raise Exception(f"Authorization failed: {response['error']['message']}")
        print("[INFO] ✅ Authorized with Deriv API.")

    async def subscribe_ticks(self, symbol):
        print(f"[INFO] Subscribing to ticks for {symbol}")
        await self._send({"ticks": symbol, "subscribe": 1})
        response = await self._recv()
        print(f"[DEBUG] Subscribe response: {response}")
        if "error" in response:
            raise Exception(f"Subscribe failed: {response['error']['message']}")
        subscription_id = response["tick"]["id"]
        self.subscriptions[symbol] = subscription_id
        print(f"[INFO] ✅ Subscribed to {symbol} (ID: {subscription_id})")
        return subscription_id

    async def unsubscribe(self, subscription_id):
        print(f"[INFO] Unsubscribing from {subscription_id}")
        await self._send({"forget": subscription_id})
        response = await self._recv()
        print(f"[DEBUG] Unsubscribe response: {response}")
        print(f"[INFO] ✅ Unsubscribed from {subscription_id}")

    async def _send(self, msg):
        print(f"[SEND] {msg}")
        await self.ws.send(json.dumps(msg))

    async def _recv(self):
        response = json.loads(await self.ws.recv())
        print(f"[RECV] {response}")
        return response

    async def close(self):
        if self.ws:
            try:
                await self.ws.close()
                print("[INFO] ✅ WebSocket closed.")
            except Exception as e:
                print(f"[WARN] WebSocket close failed: {e}")


def get_analyzer():
    from analysis.logic_engine import RealTimeAnalyzer
    return RealTimeAnalyzer


class AnalysisConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("[WS] WebSocket connect requested")
        self.user = self.scope["user"]

        if not self.user.is_authenticated:
            print("[WS] User not authenticated — closing connection")
            await self.close()
            return

        RealTimeAnalyzer = get_analyzer()
        self.analyzer = RealTimeAnalyzer(self.user, self.send_update)
        self.balance_task = None

        await self.accept()
        print("[WS] WebSocket connection accepted")
        await self.send(json.dumps({"message": "WebSocket connected to analysis"}))

    async def disconnect(self, close_code):
        print(f"[WS] Disconnect received with code {close_code}")
        try:
            await self.analyzer.stop()
            print("[WS] Analyzer stopped successfully")
        except Exception as e:
            print(f"[WARN] Cleanup error: {e}")

        if self.balance_task:
            self.balance_task.cancel()
            try:
                await self.balance_task
            except asyncio.CancelledError:
                print("[Balance Loop] Cancelled on disconnect")

    async def receive(self, text_data):
        print(f"[WS] Message received: {text_data}")
        data = json.loads(text_data)
        command = data.get("command")

        if command == "start_analysis":
            print("[CMD] start_analysis received")
            new_symbol = data.get("symbol", "R_50")
            new_last_x_ticks = data.get("last_x_ticks", 50)

            await self.analyzer.stop()
            print(f"[INFO] Analyzer stopped before new start")

            self.analyzer.symbol = new_symbol
            self.analyzer.last_x_ticks = new_last_x_ticks
            self.analyzer.tick_history = deque(maxlen=new_last_x_ticks)
            self.analyzer.tick_times = deque(maxlen=new_last_x_ticks)

            await self.analyzer.start()
            print(f"[INFO] Analyzer started with {new_symbol}, last {new_last_x_ticks} ticks")

            if self.balance_task:
                self.balance_task.cancel()
                try:
                    await self.balance_task
                    print("[INFO] Previous balance task cancelled")
                except asyncio.CancelledError:
                    print("[INFO] Balance task was already cancelled")

            self.balance_task = asyncio.create_task(self.send_balance_loop())
            print("[INFO] New balance loop task created")

            await self.send(json.dumps({"message": "Analysis started"}))

        elif command == "stop_analysis":
            print("[CMD] stop_analysis received")
            await self.analyzer.stop()
            await self.send(json.dumps({"message": "Analysis stopped"}))

            if self.balance_task:
                self.balance_task.cancel()
                try:
                    await self.balance_task
                except asyncio.CancelledError:
                    print("[INFO] Balance loop cancelled on stop_analysis")

        else:
            print(f"[WARN] Unknown command: {command}")
            await self.send(json.dumps({"error": "Unknown command"}))

    async def send_update(self, update_data):
        print(f"[SEND] Sending update to client: {update_data}")
        await self.send(json.dumps(update_data))

    async def send_balance_loop(self):
        print("[LOOP] Balance loop started")
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
                    print(f"[LOOP] Sent balance: {balance} {currency}")
                except Exception as e:
                    await self.send(json.dumps({
                        "type": "balance_update",
                        "error": str(e)
                    }))
                    print(f"[ERROR] Failed to get balance: {e}")

                await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("[Balance Loop] Cancelled")

        except Exception as e:
            print(f"[ERROR] Balance loop crashed: {e}")
