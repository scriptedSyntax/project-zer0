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
from bot_logic.markets.matches_differs import MatchesDiffersStrategy

logger = logging.getLogger(__name__)
SAFETY_MARGIN = 0.003


async def cancel_pending_contracts(trade_manager, pending_trades, send_update_callback):
    if not pending_trades:
        logger.info("No pending trades to cancel.")
        return
    logger.info(f"🧹 Cancelling {len(pending_trades)} pending contracts...")
    await send_update_callback({"message": f"🧹 Cancelling {len(pending_trades)} pending contracts..."})
    cancel_tasks = [trade_manager.cancel_contract(cid) for cid in pending_trades]
    if cancel_tasks:
        results = await asyncio.gather(*cancel_tasks, return_exceptions=True)
        successful_cancels = sum(1 for r in results if r is True)
        logger.info(f"✅ Successfully cancelled {successful_cancels}/{len(cancel_tasks)} contracts")


def calculate_profit(stake: float, is_loss: bool) -> float:
    profit = -stake if is_loss else stake
    logger.debug(f"Calculated profit: {profit} (Loss: {is_loss})")
    return profit


async def run_bot_for_user(user_id, stop_event: asyncio.Event, send_update_callback, bot_mode=None):
    logger.info(f"Starting bot for user_id={user_id}")
    user = await asyncio.to_thread(UserProfile.objects.get, user__id=user_id)
    bot_settings = await asyncio.to_thread(BotSettings.objects.get, user_id=user_id)
    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=True)

    msg = f"🚀 Bot starting on {bot_settings.symbol} [{bot_settings.market_type}]"
    if bot_settings.market_type == "even_odd":
        msg += f" with prediction: {bot_settings.prediction.lower()}"
    elif bot_settings.market_type in ["over", "under"]:
        msg += f" with threshold: {bot_settings.threshold}"
    elif bot_settings.market_type in ["matches", "differs"]:
        msg += f" targeting digit: {bot_settings.threshold}"
    msg += f" and base stake {bot_settings.stake}"
    await send_update_callback({"message": msg})

    balance_manager = await get_balance_manager(user.deriv_token)
    current_balance, _ = await balance_manager.get_current_balance()
    logger.info(f"Current balance: {current_balance}")

    stop_threshold = current_balance - bot_settings.stop_loss
    take_threshold = current_balance + bot_settings.take_profit
    logger.info(f"Stop-loss threshold: {stop_threshold}, Take-profit threshold: {take_threshold}")

    async def check_balance_limits(balance_data):
        nonlocal stop_event
        balance = balance_data["balance"]
        logger.debug(f"Balance update: {balance}")
        if balance <= stop_threshold:
            logger.warning("🛑 Stop-loss reached.")
            stop_event.set()
            await send_update_callback({"message": "🛑 Stop-loss reached. Bot stopped."})
        elif balance >= take_threshold:
            logger.info("🎯 Take-profit reached.")
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

    logger.info("Bot state initialized and subscribed to balance updates.")

    trade_manager = TradeManager(user.deriv_token)
    await trade_manager.connect()
    logger.info("Trade manager connected.")

    pending_trades = {}
    evaluation_tick_delay = getattr(bot_settings, 'tick_result_delay', 1)

    if bot_settings.market_type == "even_odd":
        config = {
            "value": bot_settings.prediction.lower(),
            "recovery_threshold": bot_settings.recovery_threshold if bot_settings.recovery_threshold in ['even', 'odd'] else None
        }
        market_handler = EvenOddStrategy(config)
    elif bot_settings.market_type in ["over", "under"]:
        config = {
            "type": bot_settings.market_type,
            "threshold": bot_settings.threshold,
            "recovery_threshold": bot_settings.recovery_threshold,
        }
        market_handler = OverUnderStrategy(config)
    elif bot_settings.market_type in ["matches", "differs"]:
        config = {
            "value": bot_settings.market_type,
            "target_digit": bot_settings.threshold,
            "recovery_threshold": bot_settings.recovery_threshold,
        }
        market_handler = MatchesDiffersStrategy(config)
    else:
        logger.error(f"Unsupported market type: {bot_settings.market_type}")
        raise ValueError(f"Unsupported market type: {bot_settings.market_type}")

    logger.info(f"Strategy initialized: {market_handler}")
    prediction_digit = int(bot_settings.threshold)

    async for tick in get_live_ticks(user.deriv_token, bot_settings.symbol):
        logger.info(f"[BOT TICK] Received tick: epoch={tick['epoch']}, quote={tick['quote']}, last_digit={tick['last_digit']}")
        logger.debug(f"Received tick: {tick}")
        if stop_event.is_set() or not state.running:
            logger.info("Stop event detected or bot no longer running.")
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
                    logger.info("Trade won. Resetting state.")
                    state.reset_on_win(bot_settings.stake)
                else:
                    logger.warning("Trade lost. Handling loss logic.")
                    state.record_loss(last_digit=last_digit)
                    # state.prediction_triggered = False
                    # state.waiting_for_prediction = True
                    await send_update_callback({"message": "❌ Loss occurred. Waiting for next prediction match to restart trading."})
                
                    if state.should_martingale(bot_settings.do_martingale_after):
                        martingale_level = state.loss_counter - bot_settings.do_martingale_after
                        next_stake = state.martingale_sequence[
                            min(martingale_level, len(state.martingale_sequence) - 1)
                        ]
                        logger.debug(f"Using martingale stake: {next_stake}")
                        state.enqueue_stake(next_stake)
                    else:
                        state.enqueue_stake(bot_settings.stake)

                if hasattr(market_handler, "use_recovery"):
                    market_handler.use_recovery = (
                        state.loss_counter > 0 and
                        getattr(market_handler, "recovery_threshold", None) is not None
                    )
                    logger.debug(f"[Recovery] use_recovery={market_handler.use_recovery} (losses={state.loss_counter})")

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
            logger.debug(f"Removing completed trade from pending: {pcid}")
            pending_trades.pop(pcid, None)

        last_digit = tick["last_digit"]

        if state.waiting_for_prediction and last_digit == prediction_digit:
            # if state.last_loss_digit is None:
            #     logger.info("No loss digit set — allowing trade.")
            #     state.waiting_for_prediction = False
            #     state.prediction_triggered = True
            # elif last_digit == state.last_loss_digit:
            #     if not state.loss_digit_seen_again:
            #         state.loss_digit_seen_again = True
            #         logger.debug("First reappearance of loss digit. Waiting for second.")
            #     else:
            #         logger.info("Second reappearance of loss digit. Restarting trading.")
            #         state.waiting_for_prediction = False
            #         state.prediction_triggered = True
            # else:
            #     logger.info("Different prediction digit than loss digit — resetting wait.")
            #     state.waiting_for_prediction = False
            #     state.prediction_triggered = True

            # logger.info(f"🎯 Prediction {prediction_digit} detected. Starting trade cycle...")
            # await send_update_callback({"message": f"🎯 Prediction {prediction_digit} detected. Starting trade cycle..."})
            state.waiting_for_prediction = False
            state.prediction_triggered = True
            
            logger.info(f"🎯 Prediction {prediction_digit} detected. Starting trade cycle...")
            await send_update_callback({"message": f"🎯 Prediction {prediction_digit} detected. Starting trade cycle..."})
            state.last_loss_digit = None
            state.loss_digit_seen_again = False

        if not state.prediction_triggered or state.awaiting_result:
            logger.debug("Skipping tick: Awaiting prediction trigger or result.")
            continue

        stake = state.get_next_priority_stake(bot_settings.stake)
        logger.info(f"Placing trade with stake: {stake}")
        await asyncio.sleep(SAFETY_MARGIN)

        prediction_str = market_handler.get_prediction_string()
        logger.debug(f"Getting proposal with prediction: {prediction_str}")
        proposal = await trade_manager.propose_contract(bot_settings.symbol, stake, prediction_str)
        buy_info = await trade_manager.buy_contract(proposal["proposal_id"], proposal["ask_price"])
        cid = buy_info["contract_id"]
        buy_epoch = tick["epoch"]
        logger.info(f"Trade executed. Contract ID: {cid}, Buy epoch: {buy_epoch}")

        pending_trades[cid] = {
            "stake": stake,
            "buy_epoch": buy_epoch,
            "prediction": prediction_str
        }

        state.awaiting_result = True

    logger.info("Unsubscribing from balance updates.")
    balance_manager.unsubscribe(check_balance_limits)
    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=False)
    state.running = False
    logger.info("Bot stopped and status updated.")
    await send_update_callback({"message": "✅ Bot finished."})
