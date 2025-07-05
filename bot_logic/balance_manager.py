# bot_logic/balance_manager.py

import asyncio
import json
import logging
import websockets
from typing import Dict, Callable, Optional, Set
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

class BalanceManager:
    """
    Centralized balance management for all users.
    Maintains single WebSocket connection per user token and broadcasts to multiple subscribers.
    """
    
    _instances: Dict[str, 'BalanceManager'] = {}  # token -> BalanceManager instance
    _locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    
    def __init__(self, token: str):
        self.token = token
        self.ws = None
        self.current_balance = None
        self.current_currency = None
        self.last_updated = None
        self.subscribers: Set[Callable] = set()
        self.connection_task = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 2.0
        self._stop_event = asyncio.Event()
        
    @classmethod
    async def get_instance(cls, token: str) -> 'BalanceManager':
        """
        Get or create a BalanceManager instance for a given token.
        Ensures only one instance per token exists.
        """
        if token not in cls._instances:
            async with cls._locks[token]:
                if token not in cls._instances:
                    instance = cls(token)
                    cls._instances[token] = instance
                    await instance.connect()
        return cls._instances[token]
    
    @classmethod
    async def cleanup_instance(cls, token: str):
        """
        Remove and cleanup a BalanceManager instance.
        """
        if token in cls._instances:
            async with cls._locks[token]:
                if token in cls._instances:
                    instance = cls._instances.pop(token)
                    await instance.disconnect()
                    del cls._locks[token]
    
    async def connect(self):
        """
        Establish WebSocket connection and start balance monitoring.
        """
        if self.is_connected:
            return
            
        self.connection_task = asyncio.create_task(self._connection_loop())
        
    async def disconnect(self):
        """
        Close WebSocket connection and cleanup resources.
        """
        self._stop_event.set()
        
        if self.connection_task:
            self.connection_task.cancel()
            try:
                await self.connection_task
            except asyncio.CancelledError:
                pass
                
        if self.ws:
            try:
                await self.ws.close()
            except:
                pass
                
        self.is_connected = False
        self.subscribers.clear()
        
    async def _connection_loop(self):
        """
        Main connection loop with automatic reconnection.
        """
        while not self._stop_event.is_set():
            try:
                await self._establish_connection()
                await self._handle_messages()
            except Exception as e:
                logger.error(f"Balance connection error for token {self.token[:8]}...: {e}")
                self.is_connected = False
                
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    self.reconnect_attempts += 1
                    delay = max(1, self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)))
                    logger.info(f"Reconnecting in {delay}s (attempt {self.reconnect_attempts})")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Max reconnection attempts reached for token {self.token[:8]}...")
                    break

                    
    async def _establish_connection(self):
        """
        Establish WebSocket connection and authorize.
        """
        DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=84524"
        
        self.ws = await websockets.connect(DERIV_WS_URL)
        
        # Authorize
        await self.ws.send(json.dumps({"authorize": self.token}))
        auth_response = await self.ws.recv()
        auth_data = json.loads(auth_response)
        
        if "error" in auth_data:
            raise Exception(f"Authorization failed: {auth_data['error']['message']}")
            
        # Subscribe to balance updates
        await self.ws.send(json.dumps({
            "balance": 1,
            "subscribe": 1
        }))
        
        self.is_connected = True
        self.reconnect_attempts = 0
        logger.info(f"Balance manager connected for token {self.token[:8]}...")
        
    async def _handle_messages(self):
        """
        Handle incoming WebSocket messages.
        """
        async for message in self.ws:
            try:
                data = json.loads(message)
                
                if data.get("msg_type") == "balance":
                    await self._handle_balance_update(data)
                    
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received: {message}")
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                
    async def _handle_balance_update(self, data):
        """
        Process balance update and notify subscribers.
        """
        if "balance" not in data:
            return
            
        balance_info = data["balance"]
        new_balance = float(balance_info.get("balance", 0))
        new_currency = balance_info.get("currency", "USD")
        
        # Update internal state
        old_balance = self.current_balance
        self.current_balance = new_balance
        self.current_currency = new_currency
        self.last_updated = datetime.now()
        
        # Notify all subscribers
        update_data = {
            "balance": new_balance,
            "currency": new_currency,
            "previous_balance": old_balance,
            "timestamp": self.last_updated.isoformat()
        }
        
        # Create tasks for all subscribers to avoid blocking
        tasks = []
        for callback in self.subscribers.copy():  # Copy to avoid modification during iteration
            try:
                if asyncio.iscoroutinefunction(callback):
                    tasks.append(asyncio.create_task(callback(update_data)))
                else:
                    callback(update_data)
            except Exception as e:
                logger.error(f"Error calling subscriber callback: {e}")
                
        # Wait for all async callbacks to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            
    def subscribe(self, callback: Callable):
        """
        Subscribe to balance updates.
        
        Args:
            callback: Function to call with balance updates.
                     Can be sync or async function.
                     Receives dict with: balance, currency, previous_balance, timestamp
        """
        self.subscribers.add(callback)
        
        # Send current balance immediately if available
        if self.current_balance is not None:
            update_data = {
                "balance": self.current_balance,
                "currency": self.current_currency,
                "previous_balance": None,
                "timestamp": self.last_updated.isoformat() if self.last_updated else None
            }
            
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(update_data))
                else:
                    callback(update_data)
            except Exception as e:
                logger.error(f"Error calling immediate callback: {e}")
                
    def unsubscribe(self, callback: Callable):
        """
        Unsubscribe from balance updates.
        """
        self.subscribers.discard(callback)
        
    async def get_current_balance(self) -> tuple[Optional[float], Optional[str]]:
        """
        Get current balance synchronously.
        If not connected, makes a one-time API call.
        
        Returns:
            tuple: (balance, currency) or (None, None) if unavailable
        """
        if self.is_connected and self.current_balance is not None:
            return self.current_balance, self.current_currency
            
        # Fallback: make one-time API call
        try:
            return await self._fetch_balance_once()
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return None, None
            
    async def _fetch_balance_once(self) -> tuple[float, str]:
        """
        Make a one-time balance API call.
        """
        DERIV_WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=84524"
        
        async with websockets.connect(DERIV_WS_URL) as ws:
            # Authorize
            await ws.send(json.dumps({"authorize": self.token}))
            auth_response = await ws.recv()
            auth_data = json.loads(auth_response)
            
            if "error" in auth_data:
                raise Exception(f"Authorization failed: {auth_data['error']['message']}")
                
            # Get balance
            await ws.send(json.dumps({"balance": 1}))
            balance_response = await ws.recv()
            balance_data = json.loads(balance_response)
            
            if "error" in balance_data:
                raise Exception(f"Balance request failed: {balance_data['error']['message']}")
                
            balance = float(balance_data["balance"]["balance"])
            currency = balance_data["balance"]["currency"]
            
            return balance, currency
    
    def get_subscriber_count(self) -> int:
        """
        Get number of active subscribers.
        """
        return len(self.subscribers)
    
    def is_balance_stale(self, max_age_seconds: int = 30) -> bool:
        """
        Check if balance data is stale.
        """
        if not self.last_updated:
            return True
            
        age = (datetime.now() - self.last_updated).total_seconds()
        return age > max_age_seconds


# Convenience functions for backward compatibility
async def get_balance_manager(token: str) -> BalanceManager:
    """
    Get a BalanceManager instance for the given token.
    """
    return await BalanceManager.get_instance(token)

async def get_account_balance(token: str) -> tuple[float, str]:
    """
    Get account balance (backward compatibility function).
    """
    manager = await get_balance_manager(token)
    return await manager.get_current_balance()

async def cleanup_balance_manager(token: str):
    """
    Cleanup balance manager for a token.
    """
    await BalanceManager.cleanup_instance(token)
