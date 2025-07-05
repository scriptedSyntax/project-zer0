# bot_logic/bot_core.py

import asyncio
import logging
from datetime import datetime

from user_config.models import UserProfile, BotSettings, BotStatus
from analysis.utils import get_live_ticks
from utils.deriv_api import get_account_balance
from bot_logic.state_manager import user_bot_states, BotState
from bot_logic.trade_manager import TradeManager
from bot_logic.balance_manager import get_balance_manager

from bot_logic.markets.even_odd import EvenOddStrategy
from bot_logic.markets.over_under import OverUnderStrategy

logger = logging.getLogger(__name__)
SAFETY_MARGIN = 0.003


async def cancel_pending_contracts(trade_manager, pending_trades, send_update_callback):
    if not pending_trades:
        return
    logger.info(f"🧹 Cancelling {len(pending_trades)} pending contracts...")
    await send_update_callback({"message": f"🧹 Cancelling {len(pending_trades)} pending contracts..."})
    cancel_tasks = [trade_manager.cancel_contract(cid) for cid in pending_trades]
    if cancel_tasks:
        results = await asyncio.gather(*cancel_tasks, return_exceptions=True)
        successful_cancels = sum(1 for r in results if r is True)
        logger.info(f"✅ Successfully cancelled {successful_cancels}/{len(cancel_tasks)} contracts")


def calculate_profit(stake: float, is_loss: bool) -> float:
    return -stake if is_loss else stake


async def run_bot_for_user(user_id, stop_event: asyncio.Event, send_update_callback, bot_mode=None):
    logger.info(f"Starting bot for user_id={user_id}")
    user = await asyncio.to_thread(UserProfile.objects.get, user__id=user_id)
    bot_settings = await asyncio.to_thread(BotSettings.objects.get, user_id=user_id)
    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=True)

    await send_update_callback({
        "message": f"🚀 Bot starting on {bot_settings.symbol} ({bot_settings.prediction}) "
                   f"with base stake {bot_settings.stake}"
    })

    balance_manager = await get_balance_manager(user.deriv_token)
    current_balance, _ = await balance_manager.get_current_balance()
    stop_threshold = current_balance - bot_settings.stop_loss
    take_threshold = current_balance + bot_settings.take_profit

    async def check_balance_limits(balance_data):
        nonlocal stop_event
        balance = balance_data["balance"]
        if balance <= stop_threshold:
            stop_event.set()
            await send_update_callback({"message": "🛑 Stop-loss reached. Bot stopped."})
        elif balance >= take_threshold:
            stop_event.set()
            await send_update_callback({"message": "🎯 Take-profit reached. Bot stopped."})
       
        await send_update_callback({
            "type": "balance_update",
            "balance": balance_data["balance"],
            "currency": balance_data["currency"]
        })

    balance_manager.subscribe(check_balance_limits)

    state = BotState(user_id=user_id)
    state.init_martingale(bot_settings)
    state.last_balance = current_balance
    user_bot_states[user_id] = state

    trade_manager = TradeManager(user.deriv_token)
    await trade_manager.connect()

    pending_trades = {}
    evaluation_tick_delay = getattr(bot_settings, 'tick_result_delay', 1)

    # Strategy: based on market_type
    if bot_settings.market_type == "even_odd":
        config = {"value": bot_settings.prediction.lower()}
        market_handler = EvenOddStrategy(config)
    elif bot_settings.market_type in ["over", "under"]:
        config = {
            "type": bot_settings.market_type,
            "threshold": bot_settings.threshold,
            "recovery_threshold": bot_settings.recovery_threshold,
        }
        market_handler = OverUnderStrategy(config)
    else:
        raise ValueError(f"Unsupported market type: {bot_settings.market_type}")

    async for tick in get_live_ticks(user.deriv_token, bot_settings.symbol):
        if stop_event.is_set() or not state.running:
            await cancel_pending_contracts(trade_manager, pending_trades, send_update_callback)
            break

        await send_update_callback({"type": "tick", "epoch": tick.get("epoch")})

        to_remove = []
        for pcid, info in pending_trades.items():
            if tick["epoch"] == info["buy_epoch"] + evaluation_tick_delay:
                last_digit = tick["last_digit"]
                prediction = info["prediction"]
                is_win = market_handler.evaluate_result(last_digit)
                is_loss = not is_win
                logger.info(
                    f"[RESULT CHECK] Contract {pcid}: last_digit={last_digit}, prediction={prediction}, is_win={is_win}"
                )

                if is_win:
                    state.reset_on_win(bot_settings.stake)
                else:
                    state.record_loss()
                    if state.should_martingale(bot_settings.do_martingale_after):
                        martingale_level = state.loss_counter - bot_settings.do_martingale_after
                        next_stake = state.martingale_sequence[
                            min(martingale_level, len(state.martingale_sequence) - 1)
                        ]
                        state.enqueue_stake(next_stake)
                    else:
                        state.enqueue_stake(bot_settings.stake)

                profit = calculate_profit(info["stake"], is_loss)
                trade_data = {
                    "contract_id": pcid,
                    "stake": info["stake"],
                    "result": "loss" if is_loss else "win",
                    "profit": profit,
                    "buy_time": info["buy_epoch"],
                    "sell_time": tick["epoch"],
                }
                state.add_trade(trade_data)
                await send_update_callback({
                    "type": "bot_update",
                    "data": trade_data
                })
                to_remove.append(pcid)
                state.awaiting_result = False

        for pcid in to_remove:
            pending_trades.pop(pcid, None)

        if state.awaiting_result:
            continue

        # 🔁 Update use_recovery dynamically before placing the trade
        if isinstance(market_handler, OverUnderStrategy):
            market_handler.use_recovery = (
                state.loss_counter > 0 and
                bot_settings.market_type in ["over", "under"]
            )

        stake = state.get_next_priority_stake(bot_settings.stake)
        await asyncio.sleep(SAFETY_MARGIN)

        prediction_str = market_handler.get_prediction_string()
        proposal = await trade_manager.propose_contract(bot_settings.symbol, stake, prediction_str)
        buy_info = await trade_manager.buy_contract(proposal["proposal_id"], proposal["ask_price"])
        cid = buy_info["contract_id"]
        buy_epoch = tick["epoch"]

        pending_trades[cid] = {
            "stake": stake,
            "buy_epoch": buy_epoch,
            "prediction": prediction_str
        }

        state.awaiting_result = True

    balance_manager.unsubscribe(check_balance_limits)
    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=False)
    state.running = False
    await send_update_callback({"message": "✅ Bot finished."})
