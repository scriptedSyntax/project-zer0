# bot_logic/bot_core.py

import asyncio
import logging
from datetime import datetime
from user_config.models import UserProfile, BotSettings, BotStatus
from analysis.utils import get_live_ticks
from utils.deriv_api import get_account_balance
from bot_logic.state_manager import user_bot_states, BotState, is_bot_running
from bot_logic.trade_manager import TradeManager
from bot_logic.tick_handler import TickContext, on_tick
    

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
    await tm.connect()
    tm.api.subscribe_balance(lambda b: state.set_balance(b))

    
    ctx = TickContext(
        user_id=user_id,
        tm=tm,
        state=state,
        settings=settings,                    # <-- pass your BotSettings
        stop_loss_threshold=stop_threshold,   # <-- renamed
        take_profit_threshold=take_threshold, # <-- renamed
        send_update=send_update_callback
    )

    async for tick in get_live_ticks(user.deriv_token, settings.symbol):
        # heartbeat
        await send_update_callback({"type": "tick", "epoch": tick["epoch"]})

        # call unified on_tick
        should_continue = await on_tick(tick, ctx)
        if not should_continue:
            break
    
    # --- Cleanup ---
    await asyncio.to_thread(BotStatus.objects.filter(user_id=user_id).update, is_running=False)
    state.stop()
    await send_update_callback({"message": "✅ Bot finished."})
