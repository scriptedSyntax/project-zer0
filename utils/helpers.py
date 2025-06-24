# utils/helpers.py

"""
helpers.py:
- General utilities shared across apps.
- Includes:
    - Safe JSON parsing
    - Logging
    - Retry decorator (useful for API calls)
    - Math helpers (for bot profit, loss, etc.)
"""

import json
import logging
import time
import functools
import random

# Set up simple logging to console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def safe_json_parse(json_str):
    """
    Safely parse JSON string. Returns dict or None if invalid.
    """
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON.")
        return None

def log_info(message):
    """
    Simple wrapper for logging info.
    """
    logger.info(message)

def log_error(message):
    """
    Simple wrapper for logging errors.
    """
    logger.error(message)

def retry(max_retries=3, delay=1):
    """
    Decorator to retry a function up to max_retries times with delay between retries.
    Useful for API calls.
    """
    def decorator_retry(func):
        @functools.wraps(func)
        def wrapper_retry(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Attempt {attempt + 1} failed: {e}")
                    time.sleep(delay)
            logger.error(f"All {max_retries} attempts failed.")
            raise Exception("Max retries exceeded.")
        return wrapper_retry
    return decorator_retry

def calculate_profit(trade_result, stake, payout_ratio=1.9):
    """
    Basic profit calculation.
    If win → return profit
    If loss → return negative stake
    """
    if trade_result == "win":
        return round(stake * (payout_ratio - 1), 2)
    elif trade_result == "loss":
        return -stake
    else:
        return 0.0

def random_delay(min_delay=0.5, max_delay=2.0):
    """
    Returns random float delay between min_delay and max_delay.
    Useful to add human-like delays in bot logic.
    """
    return round(random.uniform(min_delay, max_delay), 2)

