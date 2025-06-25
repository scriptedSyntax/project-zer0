
### bot_logic/trade_manager.py
# ```python
import asyncio
import json
import logging
import websockets

DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=1089"
logger = logging.getLogger(__name__)

class DerivAPI:
    def __init__(self, token):
        self.token = token
        self.ws = None
        self.rpc_lock = asyncio.Lock()
        self.rpc_queue = asyncio.Queue()
        self.contract_futures = {}
        self.recv_task = None
        self.balance_callback = None
        self.last_balance = None

    async def connect(self):
        self.ws = await websockets.connect(DERIV_WS_URL)
        await self._authorize()

        # subscribe to balance updates
        await self.ws.send(json.dumps({
            "balance": 1,
            "subscribe": 1
        }))

        self.recv_task = asyncio.create_task(self._recv_loop())

    async def _authorize(self):
        await self.ws.send(json.dumps({"authorize": self.token}))
        resp = json.loads(await self.ws.recv())
        if "error" in resp:
            raise Exception(resp["error"]["message"])
        logger.info("✅ Authorized with Deriv API.")

    async def _recv_loop(self):
        async for raw in self.ws:
            data = json.loads(raw)

            # balance update
            if data.get("msg_type") == "balance":
                bal = float(data["balance"].get("balance", 0))
                self.last_balance = bal
                if self.balance_callback:
                    self.balance_callback(bal)
                continue

            # # handle contract closure update
            # if data.get("msg_type") == "proposal_open_contract":
            #     poc = data.get("proposal_open_contract", {})
            #     cid = poc.get("contract_id")
            #     fut = self.contract_futures.pop(cid, None)

            #     if fut and not fut.done():
            #         fut.set_result({
            #             "contract_id": cid,
            #             "profit": float(poc.get("profit", 0)),
            #             "timestamp": poc.get("sell_time"),
            #         })
            
            # handle contract closure update — only when it’s actually sold
            if data.get("msg_type") == "proposal_open_contract":
                poc = data["proposal_open_contract"]

                # ‼️ skip every in-flight update until contract is closed
                # Deriv sets is_sold=1 (or status="sold") when it's final
                if poc.get("is_sold") != 1:
                    continue

                cid = poc["contract_id"]
                fut = self.contract_futures.pop(cid, None)

                if fut and not fut.done():
                    fut.set_result({
                        "contract_id": cid,
                        # now this really is net profit (payout minus stake)
                        "profit": float(poc.get("profit", 0)),
                        "timestamp": poc.get("sell_time"),
                    })

            else:
                await self.rpc_queue.put(data)

    def subscribe_balance(self, callback):
        """
        Register a callback to be invoked with the new balance whenever it updates.
        """
        self.balance_callback = callback

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

                    await self.ws.send(json.dumps({
                        "proposal_open_contract": 1,
                        "contract_id": cid,
                        "subscribe": 1
                    }))

                    fut = asyncio.get_event_loop().create_future()
                    self.contract_futures[cid] = fut

                    return {"contract_id": cid, "timestamp": purchase_time}

    async def get_result(self, contract_id):
        fut = self.contract_futures.get(contract_id)
        if fut:
            return await fut
        raise Exception(f"No result future found for contract {contract_id}")

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

    async def buy_contract(self, proposal_id, ask_price):
        return await self.api.buy_contract(proposal_id, ask_price)

    async def get_result(self, contract_id):
        return await self.api.get_result(contract_id)

    async def close(self):
        await self.api.close()
