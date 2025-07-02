# bot_logic/bot_logic.py

import asyncio
import logging
from datetime import datetime

from user_config.models import UserProfile, BotSettings, BotStatus
from analysis.utils import get_live_ticks
from utils.deriv_api import get_account_balance
from bot_logic.state_manager import user_bot_states, BotState
from bot_logic.trade_manager import TradeManager

logger = logging.getLogger(__name__)
SAFETY_MARGIN = 0.003  # seconds into each tick to fire the buy

async def cancel_pending_contracts(trade_manager, pending_trades, send_update_callback):
    """Cancel all pending contracts when bot stops"""
    if not pending_trades:
        return
        
    logger.info(f"🧹 Cancelling {len(pending_trades)} pending contracts...")
    await send_update_callback({"message": f"🧹 Cancelling {len(pending_trades)} pending contracts..."})
    
    cancel_tasks = []
    for contract_id in list(pending_trades.keys()):
        cancel_tasks.append(trade_manager.cancel_contract(contract_id))
    
    if cancel_tasks:
        results = await asyncio.gather(*cancel_tasks, return_exceptions=True)
        successful_cancels = sum(1 for r in results if r is True)
        logger.info(f"✅ Successfully cancelled {successful_cancels}/{len(cancel_tasks)} contracts")

def evaluate_prediction(prediction: str, last_digit: int) -> bool:
    logger.debug(f"Evaluating prediction '{prediction}' against last digit '{last_digit}'")

    if prediction == "DIGITODD":
        return last_digit % 2 == 1  # 1, 3, 5, 7, 9
    if prediction == "DIGITEVEN":
        return last_digit % 2 == 0  # 0, 2, 4, 6, 8
    if prediction.startswith("DIGIT_OVER_"):
        threshold = int(prediction.split("_")[2])
        return last_digit > threshold
    if prediction.startswith("DIGIT_UNDER_"):
        threshold = int(prediction.split("_")[2])
        return last_digit < threshold
    if prediction.startswith("DIGIT_MATCH_"):
        target = int(prediction.split("_")[2])
        return last_digit == target

    logger.warning(f"Unhandled prediction: {prediction}")
    return False  # Safe default


def calculate_profit(stake: float, is_loss: bool) -> float:
    """
    Simple profit calculation: win returns +stake, loss returns -stake.
    Modify if you need actual payout ratios, e.g. stake * payout_multiplier - stake.
    """
    profit = -stake if is_loss else stake
    logger.debug(f"Calculated profit: stake={stake}, is_loss={is_loss}, profit={profit}")
    return profit


async def run_bot_for_user(user_id, stop_event: asyncio.Event, send_update_callback, bot_mode=None):
    logger.info(f"Starting bot for user_id={user_id}")
    
    # Setup user and bot
    user = await asyncio.to_thread(UserProfile.objects.get, user__id=user_id)
    bot_settings = await asyncio.to_thread(BotSettings.objects.get, user_id=user_id)
    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=True)

    await send_update_callback({
        "message": f"🚀 Bot starting on {bot_settings.symbol} ({bot_settings.prediction}) "
                   f"with base stake {bot_settings.stake}"
    })

    balance, _ = await get_account_balance(user.deriv_token)
    stop_threshold = balance - bot_settings.stop_loss
    take_threshold = balance + bot_settings.take_profit

    state = BotState(user_id=user_id)
    state.init_martingale(bot_settings)
    state.last_balance = balance
    user_bot_states[user_id] = state

    trade_manager = TradeManager(user.deriv_token)
    await trade_manager.connect()
    trade_manager.api.subscribe_balance(lambda b: setattr(state, 'last_balance', b))

    pending_trades = {}
    evaluation_tick_delay = getattr(bot_settings, 'tick_result_delay', 1)  # <-- renamed from offset

    async for tick in get_live_ticks(user.deriv_token, bot_settings.symbol):
        if stop_event.is_set() or not state.running:
            # Cancel all pending contracts before stopping
            await cancel_pending_contracts(trade_manager, pending_trades, send_update_callback)
            break

        # Stop-loss / Take-profit
        bal = state.last_balance
        if bal is not None:
            if bal <= stop_threshold:
                state.running = False
                await cancel_pending_contracts(trade_manager, pending_trades, send_update_callback)
                await send_update_callback({"message": "🛑 Stop-loss reached. Bot stopped."})
                break
            if bal >= take_threshold:
                state.running = False
                await cancel_pending_contracts(trade_manager, pending_trades, send_update_callback)
                await send_update_callback({"message": "🎯 Take-profit reached. Bot stopped."})
                break

        await send_update_callback({"type": "tick", "epoch": tick.get("epoch")})

        # Resolve any trades that should be completed at this tick
        to_remove = []
        for pcid, info in pending_trades.items():
            if tick["epoch"] == info["buy_epoch"] + evaluation_tick_delay:
                last_digit = tick["last_digit"]
                prediction = info["prediction"]
                is_win = evaluate_prediction(prediction, last_digit)
                is_loss = not is_win
                logger.info(
                    f"[RESULT CHECK] Contract {pcid}: last_digit={last_digit}, prediction={prediction}, is_win={is_win}"
                )

                if is_win:
                    state.reset_on_win(bot_settings.stake)
                else:
                    state.record_loss()
                    if state.should_martingale(bot_settings.do_martingale_after):
                        next_stake = state.get_next_martingale_stake()
                        state.enqueue_stake(next_stake)
                    else:
                        state.enqueue_stake(bot_settings.stake)

                profit = calculate_profit(info["stake"], is_loss)
                trade_data = {
                    "contract_id": pcid,
                    "stake":        info["stake"],
                    "result":       "loss" if is_loss else "win",
                    "profit":       profit,
                    "buy_time":     info["buy_epoch"],
                    "sell_time":    tick["epoch"],
                }
                state.add_trade(trade_data)
                await send_update_callback({
                    "type": "bot_update",
                    "data": trade_data
                })

                to_remove.append(pcid)
                state.awaiting_result = False  # ✅ Release lock for next trade

        for pcid in to_remove:
            pending_trades.pop(pcid, None)

        # If a trade is still awaiting result, skip this tick
        if state.awaiting_result:
            continue

        # Determine and execute the next trade
        stake = state.get_next_priority_stake(bot_settings.stake)
        await asyncio.sleep(SAFETY_MARGIN)
        proposal = await trade_manager.propose_contract(
            bot_settings.symbol, stake, bot_settings.prediction
        )
        buy_info = await trade_manager.buy_contract(proposal["proposal_id"], proposal["ask_price"])
        cid = buy_info["contract_id"]
        buy_epoch = tick["epoch"]

        pending_trades[cid] = {
            "stake": stake,
            "buy_epoch": buy_epoch,
            "prediction": bot_settings.prediction
        }

        state.awaiting_result = True  # ✅ Block further trades until result is processed

    # Cleanup
    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=False)
    state.running = False
    await send_update_callback({"message": "✅ Bot finished."})

