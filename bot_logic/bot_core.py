# bot_logic/bot_core.py

import asyncio
import logging
from datetime import datetime
from user_config.models import UserProfile, BotSettings, BotStatus
from analysis.utils import get_live_ticks
from utils.deriv_api import get_account_balance
from bot_logic.state_manager import user_bot_states, BotState, is_bot_running
from bot_logic.trade_manager import TradeManager

logger = logging.getLogger(__name__)

async def run_bot_for_user(user_id, stop_event: asyncio.Event, send_update_callback, bot_mode=None):
    # --- Setup ---
    user = await asyncio.to_thread(UserProfile.objects.get, user__id=user_id)
    settings = await asyncio.to_thread(BotSettings.objects.get, user_id=user_id)
    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=True)

    # Frontend notification
    await send_update_callback({
        "message": f"🚀 Bot starting on {settings.symbol} ({settings.prediction}) with base stake {settings.stake:.2f}"
    })

    # Initial balance & thresholds
    balance, _ = await get_account_balance(user.deriv_token)
    stop_threshold = balance - settings.stop_loss
    take_threshold = balance + settings.take_profit

    # Initialize state
    state = BotState(user_id=user_id)
    state.init_martingale(settings)
    state.last_balance = balance
    user_bot_states[user_id] = state

    # Connect & subscribe
    tm = TradeManager(user.deriv_token)
    # await tm.connect()
    try:
        await tm.connect()
    except Exception as e:
        logger.error(f"[BotCore] Failed to connect TradeManager: {e}")
        # notify UI and abort
        await send_update_callback({
            "type":    "error",
            "message": f"🚨 Bot failed to start: {e}"
        })
        return
    tm.api.subscribe_balance(lambda b: state.set_balance(b))

    first_trade = True
    last_stake = None
    last_epoch = None

    async def handle_closed(event):
        nonlocal last_stake, last_epoch
        cid       = event["contract_id"]
        epoch     = event["sell_time"]
        profit    = round(float(event["profit"]), 2)
        loss      = profit < 0

        # 1) Martingale pointer update
        if loss:
            state.record_loss()
        else:
            state.reset_on_win()

        # 2) Record & notify
        trade = {
            "contract_id": cid,
            "stake":       last_stake,
            "profit":      profit,
            "buy_time":    last_epoch,
            "sell_time":   epoch,
            "result":      "loss" if loss else "win"
        }
        state.add_trade(trade)
        await send_update_callback({"type": "bot_update", "data": trade})

        # 3) Fire next buy _immediately_ on this tick
        stake = round(state.get_next_pointer_stake(), 2)
        try:
            prop     = await tm.propose_contract(
                           settings.symbol, stake, settings.prediction
                       )
            buy_info = await tm.buy_contract(prop["proposal_id"], prop["ask_price"])
        except Exception as e:
            logger.error(f"Buy failed at tick {epoch}: {e}")
            return

        last_stake = stake
        last_epoch = epoch
        tm.api.subscribe_contract_closed(
            buy_info["contract_id"],
            lambda ev: asyncio.create_task(handle_closed(ev))
        )

    # --- Main single-tick loop ---
    async for tick in get_live_ticks(user.deriv_token, settings.symbol):
        epoch = tick.get("epoch")

        # 1) Exit checks
        if stop_event.is_set() or not is_bot_running(user_id):
            break

        # 2) Heartbeat
        await send_update_callback({"type": "tick", "epoch": epoch})

        # 3) Risk checks
        bal = state.last_balance
        if bal is not None:
            if bal <= stop_threshold:
                state.stop()
                await send_update_callback({"message": "🛑 Stop-loss reached. Bot stopped."})
                break
            if bal >= take_threshold:
                state.stop()
                await send_update_callback({"message": "🎯 Take-profit reached. Bot stopped."})
                break

        # 4) Kick off first trade only once
        if first_trade:
            stake = round(state.get_next_pointer_stake(), 2)
            try:
                prop     = await tm.propose_contract(
                               settings.symbol, stake, settings.prediction
                           )
                buy_info = await tm.buy_contract(prop["proposal_id"], prop["ask_price"])
            except Exception as e:
                logger.error(f"Initial buy failed at tick {epoch}: {e}")
                continue

            last_stake = stake
            last_epoch = epoch
            tm.api.subscribe_contract_closed(
                buy_info["contract_id"],
                lambda ev: asyncio.create_task(handle_closed(ev))
            )
            first_trade = False

    # --- Cleanup ---
    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=False)
    state.stop()
    await send_update_callback({"message": "✅ Bot finished."})

