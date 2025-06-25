# analysis/utils.py

import asyncio
import math
from utils.deriv_api import DerivAPI

# 🔹 Get Available Volatility Symbols
async def get_available_volatility_symbols(deriv_token):
    api = DerivAPI(deriv_token)
    available_symbols = []

    try:
        await api.connect()
        await api.send({"active_symbols": "brief", "product_type": "all"})
        response = await api._recv()

        print(f"--- Fetched Active Symbols for your account ---")
        print(f"Active symbols raw response: {response}")

        if response.get("msg_type") == "active_symbols" and response.get("active_symbols"):
            for symbol_data in response["active_symbols"]:
                display_name = symbol_data.get("display_name", "")
                symbol_api_name = symbol_data.get("symbol", "")

                if (symbol_api_name.startswith("V") and 
                    "volatility" in display_name.lower() and 
                    "index" in display_name.lower() and 
                    symbol_data.get("market") == "derived"):
                    
                    available_symbols.append({
                        "symbol": symbol_api_name,
                        "display_name": display_name
                    })
        else:
            print(f"[ERROR] Failed to retrieve active symbols or unexpected response format: {response}")

    except Exception as e:
        print(f"[ERROR] get_available_volatility_symbols failed: {e}")

    finally:
        await api.close()
    
    return available_symbols

# 🔹 Fast Live Ticks Generator with Decimal-Aware Last Digit Extraction
async def get_live_ticks(deriv_token, symbol="R_50", decimal_places_for_last_digit=2):
    """
    Async generator that yields live ticks from Deriv WebSocket API,
    extracting the last digit from the quote in real-time.

    Args:
        deriv_token (str): Deriv API token.
        symbol (str): Market symbol to subscribe to (default is "R_50").
        decimal_places_for_last_digit (int): Number of decimal places used for last digit calculation.

    Yields:
        dict: {
            "symbol": str,
            "quote": float,
            "epoch": int,
            "last_digit": int
        }
    """
    api = DerivAPI(deriv_token)
    subscription_id = None

    try:
        await api.connect()
        subscription_id = await api.subscribe_ticks(symbol)
        print(f"✅ Subscribed to ticks for {symbol}. Subscription ID: {subscription_id}")

        while True:
            tick_data = await api._recv()

            if tick_data.get("msg_type") == "tick":
                raw_quote = tick_data["tick"]["quote"]
                multiplier = 10 ** decimal_places_for_last_digit
                last_digit = int(round(raw_quote * multiplier)) % 10

                tick = {
                    "symbol": tick_data["tick"]["symbol"],
                    "quote": raw_quote,
                    "epoch": tick_data["tick"]["epoch"],
                    "last_digit": last_digit
                }

                yield tick

            await asyncio.sleep(3.4)  # Throttle to avoid overwhelming the WebSocket
            # This sleep can be adjusted based on your needs(we adjust based on tick value needed)

    except Exception as e:
        if "invalid" in str(e).lower() and "symbol" in str(e).lower():
            print(f"[ERROR] get_live_ticks failed: Invalid symbol '{symbol}'.")
        else:
            print(f"[ERROR] get_live_ticks failed: {e}")

    finally:
        try:
            if subscription_id:
                await api.unsubscribe(subscription_id)
                print(f"✅ Unsubscribed from {subscription_id}.")
            # await api.close()
            # print("✅ WebSocket connection closed.")
        except Exception as cleanup_err:
            print(f"[WARN] Cleanup error during disconnect: {cleanup_err}")
            
# 🔹 Even/Odd Trade Execution (DIGITEVEN / DIGITODD)
async def place_even_odd_trade(deriv_token, symbol, stake, contract_type, duration=1):
    """
    Places a DIGITEVEN or DIGITODD trade using DerivAPI wrapper.

    Args:
        deriv_token (str): Deriv API token.
        symbol (str): Market symbol.
        stake (float): Stake amount.
        contract_type (str): 'DIGITEVEN' or 'DIGITODD'
        duration (int): Trade duration in ticks (default: 1)

    Returns:
        dict: {
            is_win: bool,
            profit: float,
            contract_id: str,
            timestamp: int
        } or { error: str } on failure.
    """
    api = DerivAPI(deriv_token)

    try:
        await api.connect()

        result = await api.propose_and_buy_even_odd_contract(
            symbol=symbol,
            stake=stake,
            contract_type=contract_type,
            duration=duration
        )

        print(f"✅ Even/Odd TRADE RESULT: {result}")

        return {
            "is_win": result.get("is_win"),
            "profit": result.get("profit"),
            "contract_id": result.get("contract_id", ""),
            "timestamp": result.get("timestamp", None)
        }
        
        # print(f"contract_id: {result.get('contract_id', '')}, profit: {result.get('profit', 0.0)}")
        
    except Exception as e:
        print(f"[ERROR] place_even_odd_trade failed: {e}")
        return {"error": str(e)}

    finally:
        try:
            await api.close()
            print("✅ WebSocket closed after even/odd trade.")
        except Exception as close_err:
            print(f"[WARN] Cleanup failed: {close_err}")


