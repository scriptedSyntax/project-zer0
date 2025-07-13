# bot_logic/state_manager.py

import collections
import logging
from collections import deque
from typing import Deque, List
from bot_logic.balance_manager import get_balance_manager
from user_config.models import BotSettings

logger = logging.getLogger(__name__)

# In-memory store of BotState per user
user_bot_states = {}  # user_id -> BotState

def generate_martingale_sequence(base: float, factor: float, levels: int) -> List[float]:
    """
    Generate Martingale sequence starting from factor^1: [base*factor, base*factor^2, ...]
    This ensures proper indexing when martingale activates.
    """
    seq = [round(base * (factor ** i), 2) for i in range(1, levels + 1)]
    logger.debug(f"[generate_martingale_sequence] base={base}, factor={factor}, levels={levels}, sequence_sample={seq[:5]}")
    return seq

def get_next_martingale_stake(self) -> float:
    """
    Get stake amount for the current martingale level.
    Since sequence now starts from factor^1, we use (loss_counter - 1) as index.
    """
    idx = min(self.loss_counter - 1, len(self.martingale_sequence) - 1)
    stake = self.martingale_sequence[idx]
    logger.debug(f"[get_next_martingale_stake] loss_counter={self.loss_counter}, index={idx}, stake={stake}")
    return stake

def add_trade(self, trade: dict):
    self.trade_history.append(trade)
    self.awaiting_result = False  # ✅ Reset trade block after trade resolves
    logger.debug(f"[add_trade] Trade added: {trade}")

class BotState:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.running = False
        self.loss_counter = 0
        self.is_recovering = False
        self.martingale_sequence: List[float] = []
        self.stake_queue: Deque[float] = deque()
        self.last_trade_epoch = None
        self.trade_history: List[dict] = []
        self.awaiting_result = False  # 🚦 Block further trades until result arrives
        self.last_result = None       # 🧾 Store result (can help with advanced stake logic)

        self.waiting_for_prediction = True  # 🕓 Waiting until prediction digit appears
        self.prediction_triggered = False   # ✅ Flag to start tick-by-tick trading
        self.last_loss_digit = None  # 🚫 To avoid retrading on the loss-causing digit
        self.loss_digit_seen_again = False  # ✅ Waits for a second appearance after loss
        self.first_trade_pending = False  # ✅ Delay mechanism after first prediction match

        logger.info(f"[BotState:init] Created BotState for user_id={user_id}")

    def init_martingale(self, bot_settings: BotSettings):
        """
        Initialize martingale parameters and stake queue at bot start.
        """
        self.running = True
        self.loss_counter = 0
        self.is_recovering = False
        self.martingale_sequence = generate_martingale_sequence(
            base=bot_settings.stake,
            factor=bot_settings.martingale,
            levels=100
        )
        self.stake_queue.clear()
        self.stake_queue.append(bot_settings.stake)
        logger.info(f"[init_martingale] Initialized martingale: stake={bot_settings.stake}, factor={bot_settings.martingale}")

    def get_next_priority_stake(self, base_stake: float) -> float:
        """
        Return the next stake from the queue, or default to base_stake.
        """
        if self.stake_queue:
            stake = self.stake_queue.popleft()
            logger.debug(f"[get_next_priority_stake] Popped stake from queue: {stake}")
            return stake
        logger.debug(f"[get_next_priority_stake] Queue empty. Using base stake: {base_stake}")
        return base_stake

    def reset_on_win(self, base_stake: float):
        """
        Reset state after a winning trade.
        """
        self.loss_counter = 0
        self.is_recovering = False
        self.stake_queue.clear()
        self.stake_queue.append(base_stake)
        logger.info(f"[reset_on_win] Win detected. Resetting with base stake: {base_stake}")

    def record_loss(self, last_digit=None):
        self.loss_counter += 1
        self.is_recovering = True
        self.stake_queue.clear()
        if last_digit is not None:
            self.last_loss_digit = last_digit  # 🧠 Track loss-causing digit
        logger.warning(f"[record_loss] Loss recorded. count={self.loss_counter}, last_digit={last_digit}")

    def should_martingale(self, trigger_after: int) -> bool:
        """
        Determine if martingale stake should be applied.
        """
        should = (
            self.loss_counter >= trigger_after
            and self.loss_counter < len(self.martingale_sequence)
        )
        logger.debug(f"[should_martingale] loss_counter={self.loss_counter}, trigger_after={trigger_after}, should_martingale={should}")
        return should

    def get_next_martingale_stake(self) -> float:
        """
        Get stake amount for the current martingale level.
        """
        idx = min(self.loss_counter, len(self.martingale_sequence) - 1)
        stake = self.martingale_sequence[idx]
        logger.debug(f"[get_next_martingale_stake] loss_counter={self.loss_counter}, index={idx}, stake={stake}")
        return stake

    def enqueue_stake(self, stake: float):
        """
        Queue a stake to be used on the very next tick.
        """
        self.stake_queue.appendleft(stake)
        logger.debug(f"[enqueue_stake] Stake enqueued: {stake}")

    def add_trade(self, trade: dict):
        """
        Record trade details for history.
        """
        self.trade_history.append(trade)
        logger.info(f"[add_trade] Trade recorded: {trade}")

    def reset_profit_tracking(self):
        """
        Reset any profit-related temporary tracking values.
        Currently a placeholder for safety; extendable if needed.
        """
        logger.debug("[reset_profit_tracking] Called (currently a no-op)")

    def should_trade_now(self, last_digit: int, prediction_digit: int) -> bool:
        """
        Determine if bot should start trading again based on digit and previous loss.
        """
        logger.debug(f"[should_trade_now] Checking: last_digit={last_digit}, prediction_digit={prediction_digit}, last_loss_digit={self.last_loss_digit}, seen_again={self.loss_digit_seen_again}")

        if not self.waiting_for_prediction:
            return False
        if last_digit != prediction_digit:
            return False
        if self.last_loss_digit is None:
            return True
        if last_digit == self.last_loss_digit:
            if not self.loss_digit_seen_again:
                self.loss_digit_seen_again = True  # Mark first reappearance
                return False  # skip first time
            return True  # second time it's okay
        return True

async def setup_balance_monitoring(self, token: str):
    """
    Set up balance monitoring for this bot state.
    """
    self.balance_manager = await get_balance_manager(token)
    self.balance_manager.subscribe(self._on_balance_update)
    balance, currency = await self.balance_manager.get_current_balance()
    if balance is not None:
        self.last_balance = balance
        logger.info(f"[setup_balance_monitoring] Balance initialized: {balance} {currency}")

async def on_balance_update(self, balance_data):
    """Handle balance updates."""
    self.last_balance = balance_data["balance"]
    logger.debug(f"[on_balance_update] New balance: {balance_data}")

def cleanup_balance_monitoring(self):
    """
    Clean up balance monitoring.
    """
    if hasattr(self, 'balance_manager'):
        self.balance_manager.unsubscribe(self._on_balance_update)
        logger.info("[cleanup_balance_monitoring] Unsubscribed from balance updates")

def is_bot_running(user_id: int) -> bool:
    state = user_bot_states.get(user_id)
    running = state.running if state else False
    logger.debug(f"[is_bot_running] user_id={user_id}, running={running}")
    return running

