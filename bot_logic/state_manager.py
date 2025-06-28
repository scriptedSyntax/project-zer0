# bot_logic/state_manager.py

from typing import List
from user_config.models import BotSettings

user_bot_states = {}  # user_id -> BotState

def generate_martingale_sequence(base: float, factor: float, levels: int) -> List[float]:
    return [round(base * (factor ** i), 2) for i in range(levels)]

class BotState:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.running = False
        self.loss_counter = 0
        self.pointer = 0 
        self.martingale_sequence: List[float] = []
        self.last_balance = None
        self.trade_history: List[dict] = []

    def init_martingale(self, settings: BotSettings, levels: int = 60):
        """Precompute stake array and reset pointer/loss counter."""
        self.running = True
        self.loss_counter = 0
        self.pointer = 0
        self.do_martingale_after = settings.do_martingale_after
        self.martingale_sequence = generate_martingale_sequence(
            base=settings.stake,
            factor=settings.martingale,
            levels=levels
        )

#    def get_next_pointer_stake(self) -> float:
#        """O(1) stake lookup and pointer advance (up to end)."""
#        stake = self.martingale_sequence[self.pointer]
#        if self.pointer < len(self.martingale_sequence) - 1:
#            self.pointer += 1
#        return stake

    def get_next_pointer_stake(self) -> float:
        stake = self.martingale_sequence[self.pointer]
        if self.loss_counter >= self.do_martingale_after:
            if self.pointer < len(self.martingale_sequence) - 1:
                self.pointer += 1
            self.loss_counter = 0  # reset loss counter after martingale trigger
        return stake
    
    def record_loss(self):
        """Called on a losing trade (pointer already advanced)."""
        self.loss_counter += 1

    def reset_on_win(self):
        """Called on a winning trade: reset pointer and loss counter."""
        self.loss_counter = 0
        self.pointer = 0

    def add_trade(self, trade: dict):
        """Append a trade record for history & dashboard metrics."""
        self.trade_history.append(trade)

    def set_balance(self, balance: float):
        """Update last known account balance for stop checks."""
        self.last_balance = balance

    def stop(self):
        """Mark bot as no longer running."""
        self.running = False

    def to_summary(self) -> dict:
        """Compute total_profit, wins, and losses for the dashboard."""
        wins = sum(1 for t in self.trade_history if t["result"] == "WIN")
        losses = sum(1 for t in self.trade_history if t["result"] == "LOSS")
        total = round(sum(t["profit"] for t in self.trade_history), 2)
        return {"total_profit": total, "wins": wins, "losses": losses}

def is_bot_running(user_id: int) -> bool:
    state = user_bot_states.get(user_id)
    return bool(state and state.running)
