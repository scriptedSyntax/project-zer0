# bot_logic/trade_manager.py

import asyncio
import json
import logging
import websockets

DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=84524"
logger = logging.getLogger(__name__)

class DerivAPI:
    def __init__(self, token):
        self.token = token
        self.ws = None
        self.pending_requests = {}
        self.req_id_counter = 0
        self.contract_futures = {}
        self.recv_task = None
        self.balance_callback = None
        self.last_balance = None
        self.rpc_queue = asyncio.Queue()

    async def connect(self):
        logger.info("🔌 Connecting to Deriv WebSocket...")
        self.ws = await websockets.connect(DERIV_WS_URL)
        logger.info("🔗 WebSocket connection established.")
        await self._authorize()

        logger.info("📡 Subscribing to balance updates...")
        await self.ws.send(json.dumps({
            "balance": 1,
            "subscribe": 1
        }))

        self.recv_task = asyncio.create_task(self._recv_loop())
        logger.info("📥 Receive loop started.")

    async def _authorize(self):
        logger.info("🔑 Sending authorization request...")
        await self.ws.send(json.dumps({"authorize": self.token}))
        try:
            message = await asyncio.wait_for(self.ws.recv(), timeout=3)
        except asyncio.TimeoutError:
            logger.warning("⚠️ Timeout during authorization – reconnecting...")
            await self.connect()
            return
        resp = json.loads(message)
        if "error" in resp:
            logger.error(f"❌ Authorization failed: {resp['error']['message']}")
            raise Exception(resp["error"]["message"])
        logger.info("✅ Authorized with Deriv API.")

    async def _recv_loop(self):
        logger.debug("📥 Starting receive loop...")
        async for raw in self.ws:
            data = json.loads(raw)
            logger.debug(f"📨 Received message: {data}")

            if "req_id" in data:
                req_id = str(data["req_id"])
                fut = self.pending_requests.pop(req_id, None)
                if fut and not fut.done():
                    logger.debug(f"🔓 Resolving request with req_id={req_id}")
                    fut.set_result(data)
                continue

            if data.get("msg_type") == "balance":
                if "balance" in data:
                    bal = float(data["balance"].get("balance", 0))
                    logger.info(f"💰 Balance update received: {bal}")
                    self.last_balance = bal
                    if self.balance_callback:
                        self.balance_callback(bal)
                else:
                    logger.warning(f"⚠️ Balance message malformed: {data}")
                continue

            if data.get("msg_type") == "proposal_open_contract":
                poc = data["proposal_open_contract"]
                if poc.get("is_sold") != 1:
                    logger.debug(f"📦 Contract update skipped (not sold): {poc}")
                    continue

                cid = poc["contract_id"]
                fut = self.contract_futures.pop(cid, None)
                if fut and not fut.done():
                    logger.info(f"📈 Contract closed: {cid}, profit={poc.get('profit', 0)}")
                    fut.set_result({
                        "contract_id": cid,
                        "profit": float(poc.get("profit", 0)),
                        "timestamp": poc.get("sell_time"),
                    })
                continue

            logger.debug(f"📥 Unhandled message, enqueuing: {data}")
            await self.rpc_queue.put(data)

    def subscribe_balance(self, callback):
        self.balance_callback = callback
        logger.debug("🔔 Balance callback subscribed.")

    async def propose_contract(self, symbol, stake, contract_type, duration=1):
        payload = {
            "proposal": 1,
            "amount": stake,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": "USD",
            "duration": duration,
            "duration_unit": "t",
            "symbol": symbol
        }
        logger.info(f"📨 Sending contract proposal: {payload}")
        resp = await self._send_request(payload)
        p = resp.get("proposal")
        if not p:
            raise Exception("Proposal failed, no 'proposal' in response.")
        logger.info(f"✅ Proposal received: id={p['id']}, ask_price={p['ask_price']}")
        return {"proposal_id": p["id"], "ask_price": p["ask_price"]}

    async def buy_contract(self, proposal_id, price):
        logger.info(f"🛒 Buying contract with proposal_id={proposal_id} for ${price}")
        resp = await self._send_request({
            "buy": proposal_id,
            "price": price,
            "subscribe": 1
        })

        b = resp.get("buy")
        if not b:
            raise Exception("Failed to buy contract, no 'buy' in response.")

        cid = b["contract_id"]
        logger.info(f"✅ Contract bought: {cid}, purchase_time={b['purchase_time']}")

        fut = asyncio.get_event_loop().create_future()
        self.contract_futures[cid] = fut

        return {"contract_id": cid, "timestamp": b["purchase_time"]}

    async def get_result(self, contract_id):
        logger.info(f"⏳ Awaiting result for contract_id={contract_id}")
        fut = self.contract_futures.get(contract_id)
        if fut:
            try:
                result = await asyncio.wait_for(fut, timeout=1)     # adjust this timer
                logger.info(f"🎯 Result received for contract_id={contract_id}: {result}")
                return result
            except asyncio.TimeoutError:
                logger.error(f"⏱️ Timeout waiting for contract {contract_id} to settle.")
                raise

        error_msg = f"🚫 No result future found for contract {contract_id}"
        logger.error(error_msg)
        raise Exception(error_msg)

    async def close(self):
        if self.recv_task:
            self.recv_task.cancel()
            logger.debug("🔒 Receive task cancelled.")
            try:
                await self.recv_task
            except asyncio.CancelledError:
                logger.debug("📴 Receive loop cancelled.")
        if self.ws:
            await self.ws.close()
            logger.info("✅ WebSocket connection closed.")

    async def _send_request(self, payload):
        self.req_id_counter += 1
        req_id = str(self.req_id_counter)
        payload["req_id"] = req_id

        fut = asyncio.get_event_loop().create_future()
        self.pending_requests[req_id] = fut

        logger.debug(f"📤 Sending request with req_id={req_id}: {payload}")
        await self.ws.send(json.dumps(payload))
        return await fut
        
    async def cancel_contract(self, contract_id):
        """Cancel a specific contract if it's still open"""
        logger.info(f"🚫 Cancelling contract: {contract_id}")
        try:
            resp = await self._send_request({
                "cancel": contract_id
            })
            if "cancel" in resp:
                logger.info(f"✅ Contract {contract_id} cancelled successfully")
                return True
            else:
                logger.warning(f"⚠️ Cancel response unexpected: {resp}")
                return False
        except Exception as e:
            logger.error(f"❌ Failed to cancel contract {contract_id}: {e}")
            return False

class TradeManager:
    def __init__(self, token):
        self.api = DerivAPI(token)
        logger.debug("🚀 TradeManager initialized.")

    async def connect(self):
        logger.info("🔌 Connecting via TradeManager...")
        await self.api.connect()

    async def propose_contract(self, *args, **kwargs):
        return await self.api.propose_contract(*args, **kwargs)

    async def buy_contract(self, proposal_id, ask_price):
        return await self.api.buy_contract(proposal_id, ask_price)

    async def get_result(self, contract_id):
        return await self.api.get_result(contract_id)

    async def close(self):
        logger.info("🛑 Closing TradeManager session...")
        await self.api.close()
    
    async def cancel_contract(self, contract_id):
        return await self.api.cancel_contract(contract_id)
