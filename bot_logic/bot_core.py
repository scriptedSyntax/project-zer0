# bot_logic/bot_core.py

import asyncio
import logging
import time
from datetime import datetime

from user_config.models import UserProfile, BotSettings, BotStatus
from analysis.utils import get_live_ticks
from utils.deriv_api import get_account_balance
from bot_logic.state_manager import user_bot_states, BotState
from bot_logic.trade_manager import TradeManager

logger = logging.getLogger(__name__)
SAFETY_MARGIN = 0.03  # seconds into each tick to fire the buy


async def run_bot_for_user(user_id, stop_event: asyncio.Event, send_update_callback, bot_mode=None):
    # --- setup user & state
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

    # --- connect & subscribe balance
    trade_manager = TradeManager(user.deriv_token)
    await trade_manager.connect()
    trade_manager.api.subscribe_balance(lambda b: setattr(state, 'last_balance', b))

    # --- main tick loop ---
    tasks = set()
    async for tick in get_live_ticks(user.deriv_token, bot_settings.symbol):
        if stop_event.is_set() or not state.running:
            break

        # stop-loss / take-profit
        bal = state.last_balance
        if bal is not None:
            if bal <= stop_threshold:
                state.running = False
                await send_update_callback({"message": "🛑 Stop-loss reached. Bot stopped."})
                break
            if bal >= take_threshold:
                state.running = False
                await send_update_callback({"message": "🎯 Take-profit reached. Bot stopped."})
                break

        await send_update_callback({"type": "tick", "epoch": tick.get("epoch")})
        
        # stake = state.get_next_priority_stake(bot_settings.stake)
        # await asyncio.sleep(SAFETY_MARGIN)
        
        stake = state.get_next_priority_stake(bot_settings.stake)
        proposal = await trade_manager.propose_contract(
            bot_settings.symbol, stake, bot_settings.prediction
        )
        await asyncio.sleep(SAFETY_MARGIN)
        buy_info = await trade_manager.buy_contract(proposal["proposal_id"], proposal["ask_price"])
        buy_time = buy_info["timestamp"]

        # fire and forget, but keep track so we can await on teardown
        task = asyncio.create_task(
            _handle_result(
                buy_info["contract_id"],
                stake,
                buy_time,
                state,
                bot_settings,
                trade_manager,
                send_update_callback
            )
        )
        tasks.add(task)
        task.add_done_callback(lambda t: tasks.discard(t))

    # wait for any in-flight result-handlers before marking stopped
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=False)
    state.running = False
    logger.info(f"✅ Bot finished for user {user_id}")
    await send_update_callback({"message": "✅ Bot finished."})


async def _handle_result(contract_id, stake, buy_time, state,
                         bot_settings, trade_manager, send_update_callback):
    # prevent stray tasks after stop
    if not state.running:
        return

    try:
        print(f"[INFO] Handling result for contract_id: {contract_id}")

        # 1) fetch raw net profit (Deriv sends stake + winnings minus stake, i.e. net)
        result = await trade_manager.get_result(contract_id)
        print(f"[DEBUG] Raw result received: {result}")
        if "profit" not in result:
            raise KeyError("missing profit field")
        
        state.reset_profit_tracking()
        net_raw = float(result["profit"])
        net = round(net_raw, 2)
        print(f"[DEBUG] Parsed raw net profit: {net_raw}")

        # 2) round net profit and stake to 2 decimal places
        net = float(f"{net_raw:.2f}")        # half-away-from-zero rounding
        stake_rounded = float(f"{stake:.2f}")
        print(f"[DEBUG] Rounded net: {net}, Rounded stake: {stake_rounded}")

        # 3) sell_time
        sell_time = result.get("timestamp") or int(time.time())
        # ensure monotonic
        sell_time = max(sell_time, buy_time)
        print(f"[DEBUG] Sell time resolved to: {sell_time}")

        # 4) WIN-FIRST check
        is_loss = net < 0
        print(f"[RESULT] {'LOSS' if is_loss else 'WIN'} detected. Net: {net}")

        # 5) martingale state update
        if is_loss:
            state.record_loss()
            if state.should_martingale(bot_settings.do_martingale_after):
                next_stake = state.get_next_martingale_stake()
                state.enqueue_stake(next_stake)
        else:
            state.reset_on_win(bot_settings.stake)

        # 6) record history
        trade_data = {
            "contract_id": contract_id,
            "stake":        stake_rounded,
            "result":       "LOSS" if is_loss else "WIN",
            "profit":       net,
            "raw_profit":   net_raw,
            "buy_time":     datetime.fromtimestamp(buy_time).isoformat(),
            "sell_time":    datetime.fromtimestamp(sell_time).isoformat(),
        }
        state.add_trade(trade_data)

        # 7) notify front-end
        await send_update_callback({
            "type": "bot_update",
            "data": {
                "contract_id": contract_id,
                "result":      "loss" if is_loss else "win",
                "stake":       stake_rounded,
                "profit":      net,
                "buy_time":    buy_time,
                "sell_time":   sell_time,
            }
        })

    except Exception as e:
        print(f"[ERROR] in _handle_result for {contract_id}: {e}")
        await send_update_callback({
            "message": f"❌ Error handling result for {contract_id}"
        })
