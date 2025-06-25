# bot_logic/state_manager.py

import collections
from collections import deque
from typing import Deque, List
from user_config.models import BotSettings

# In-memory store of BotState per user
user_bot_states = {}  # user_id -> BotState

def generate_martingale_sequence(base: float, factor: float, levels: int) -> List[float]:
    """
    Generate Martingale sequence: [base, base*factor, base*factor^2, ...]
    """
    seq = [round(base * (factor ** i), 2) for i in range(levels)]
    return seq

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

    def init_martingale(self, bot_settings: BotSettings):
        """
        Initialize martingale parameters and stake queue at bot start.
        """
        self.running = True
        self.loss_counter = 0
        self.is_recovering = False
        # Build sequence of stake levels (fixed max levels = 20)
        self.martingale_sequence = generate_martingale_sequence(
            base=bot_settings.stake,
            factor=bot_settings.martingale,
            levels=60
        )
        # Start with base stake
        self.stake_queue.clear()
        self.stake_queue.append(bot_settings.stake)

    def get_next_priority_stake(self, base_stake: float) -> float:
        """
        Return the next stake from the queue, or default to base_stake.
        """
        if self.stake_queue:
            return self.stake_queue.popleft()
        return base_stake

    def reset_on_win(self, base_stake: float):
        """
        Reset state after a winning trade.
        """
        self.loss_counter = 0
        self.is_recovering = False
        self.stake_queue.clear()
        self.stake_queue.append(base_stake)

    def record_loss(self):
        """
        Update state on a lost trade.
        """
        self.loss_counter += 1
        self.is_recovering = True
        # clear any queued stakes
        self.stake_queue.clear()

    def should_martingale(self, trigger_after: int) -> bool:
        """
        Determine if martingale stake should be applied.
        """
        return (
            self.loss_counter >= trigger_after
            and self.loss_counter < len(self.martingale_sequence)
        )

    def get_next_martingale_stake(self) -> float:
        """
        Get stake amount for the current martingale level.
        """
        idx = min(self.loss_counter, len(self.martingale_sequence) - 1)
        return self.martingale_sequence[idx]

    def enqueue_stake(self, stake: float):
        """
        Queue a stake to be used on the very next tick.
        """
        self.stake_queue.appendleft(stake)

    def add_trade(self, trade: dict):
        """
        Record trade details for history.
        """
        self.trade_history.append(trade)
    
    def reset_profit_tracking(self):
        """
        Reset any profit-related temporary tracking values.
        Currently a placeholder for safety; extendable if needed.
        """
        pass  # If you later add attributes like self.last_profit, reset them here

# Helper to check if bot is running

def is_bot_running(user_id: int) -> bool:
    state = user_bot_states.get(user_id)
    return state.running if state else False
