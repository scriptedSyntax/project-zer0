# bot_logic/markets/base_market.py

from abc import ABC, abstractmethod

class MarketStrategy(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def get_prediction_string(self):
        pass

    @abstractmethod
    def evaluate_result(self, last_digit: int) -> bool:
        pass
