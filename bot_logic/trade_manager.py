# bot_logic/trade_manager.py

import asyncio
import json
import logging
import websockets
from typing import Callable

DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=81950"
logger = logging.getLogger(__name__)

class DerivAPI:
    def __init__(self, token):
        self.token = token
        self.ws = None
        self.rpc_lock = asyncio.Lock()
        self.rpc_queue = asyncio.Queue()
        self.contract_futures = {}               # contract_id -> Future
        self.contract_closed_callbacks = {}      # contract_id -> [callbacks]
        self.balance_callback = None
        self.recv_task = None

    async def connect(self):
        self.ws = await websockets.connect(DERIV_WS_URL)
        await self.authorize()
        # subscribe to balance
        await self.ws.send(json.dumps({"balance":1,"subscribe":1}))
        # start recv loop
        self.recv_task = asyncio.create_task(self._recv_loop())

    async def authorize(self):
        await self.ws.send(json.dumps({"authorize": self.token}))
        resp = json.loads(await self.ws.recv())
        if "error" in resp:
            raise Exception(resp["error"]["message"])
        logger.info("✅ Authorized with Deriv API.")

    async def _recv_loop(self):
        try:
            async for raw in self.ws:
                data = json.loads(raw)

                # 1) Balance updates
                if data.get("msg_type") == "balance":
                    bal = float(data["balance"].get("balance", 0))
                    if self.balance_callback:
                        self.balance_callback(bal)
                    continue

                # 2) Contract closure updates
                if data.get("msg_type") == "proposal_open_contract":
                    poc = data["proposal_open_contract"]
                    # only care once it's actually sold
                    if poc.get("is_sold") != 1:
                        continue

                    cid = poc["contract_id"]
                    # 2.a) fulfill any waiting future
                    fut = self.contract_futures.pop(cid, None)
                    result = {
                        "contract_id": cid,
                        "profit": float(poc.get("profit", 0)),
                        "sell_time": poc.get("sell_time")
                    }
                    if fut and not fut.done():
                        fut.set_result(result)

                    # 2.b) fire registered callbacks
                    callbacks = self.contract_closed_callbacks.pop(cid, [])
                    for cb in callbacks:
                        try:
                            cb(result)
                        except Exception:
                            logger.exception("Error in contract_closed callback")
                    continue

                # 3) All other RPCs go onto the queue
                await self.rpc_queue.put(data)

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Exception in DerivAPI._recv_loop")

    def subscribe_balance(self, callback: Callable[[float], None]):
        """Register for real-time balance updates."""
        self.balance_callback = callback

    def subscribe_contract_closed(self, contract_id: str, callback: Callable[[dict], None]):
        """
        Register a callback to be invoked immediately when
        a contract_id is marked is_sold==1.
        """
        self.contract_closed_callbacks.setdefault(contract_id, []).append(callback)

    async def propose_contract(self, symbol, stake, contract_type, duration=1):
        async with self.rpc_lock:
            await self.ws.send(json.dumps({
                "proposal": 1,
                "amount": stake,
                "basis": "stake",
                "contract_type": contract_type,
                "currency": "USD",
                "duration": duration,
                "duration_unit": "t",
                "symbol": symbol
            }))
            while True:
                resp = await self.rpc_queue.get()
                if resp.get("msg_type") == "proposal":
                    p = resp["proposal"]
                    return {"proposal_id": p["id"], "ask_price": p["ask_price"]}

    async def buy_contract(self, proposal_id, price):
        async with self.rpc_lock:
            await self.ws.send(json.dumps({"buy": proposal_id, "price": price}))
            while True:
                resp = await self.rpc_queue.get()
                if resp.get("msg_type") == "buy":
                    b = resp["buy"]
                    cid = b["contract_id"]
                    purchase_time = b["purchase_time"]
                    # subscribe to its closure event
                    await self.ws.send(json.dumps({
                        "proposal_open_contract": 1,
                        "contract_id": cid,
                        "subscribe": 1
                    }))
                    fut = asyncio.get_event_loop().create_future()
                    self.contract_futures[cid] = fut
                    return {"contract_id": cid, "timestamp": purchase_time}

    async def get_result(self, contract_id):
        """
        Polling fallback; not used in event-driven mode,
        but retained for backward compatibility.
        """
        fut = self.contract_futures.get(contract_id)
        if fut:
            return await fut
        raise Exception(f"No result future for contract {contract_id}")

    async def close(self):
        if self.recv_task:
            self.recv_task.cancel()
        if self.ws:
            await self.ws.close()
            logger.info("✅ WebSocket closed.")

class TradeManager:
    def __init__(self, token):
        self.api = DerivAPI(token)

    async def connect(self):
        await self.api.connect()

    async def propose_contract(self, *args, **kwargs):
        return await self.api.propose_contract(*args, **kwargs)

    async def buy_contract(self, *args, **kwargs):
        return await self.api.buy_contract(*args, **kwargs)

    async def get_result(self, contract_id):
        return await self.api.get_result(contract_id)

    async def close(self):
        await self.api.close()
