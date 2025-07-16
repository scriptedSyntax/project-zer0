# bot_logic/tick_handler.py

import asyncio
import logging
from bot_logic.state_manager import is_bot_running
from utils.deriv_api import get_account_balance

logger = logging.getLogger(__name__)

class TickContext:
    def __init__(
        self,
        user_id,
        tm,
        state,
        settings,
        stop_loss_threshold,
        take_profit_threshold,
        send_update,
    ):
        self.user_id = user_id
        self.trade_manager = tm
        self.state = state
        self.settings = settings        # added
        self.stop_loss_threshold = stop_loss_threshold
        self.take_profit_threshold = take_profit_threshold
        self.send_update = send_update
        self.active_contract = None  # new

        # for initial trade
        self.first_trade = True

    async def handle_closed(self, event):
        """Called whenever a contract closes."""
        cid    = event["contract_id"]
        epoch  = event["sell_time"]
        profit = round(float(event["profit"]), 2)
        loss   = profit < 0

        # 1) Martingale pointer update
        if loss:
            self.state.record_loss()
        else:
            self.state.reset_on_win()

        # 2) Record & notify
        trade = {
            "contract_id": cid,
            "stake":       self.last_stake,
            "profit":      profit,
            "buy_time":    self.last_epoch,
            "sell_time":   epoch,
            "result":      "loss" if loss else "win"
        }
        self.state.add_trade(trade)
        await self.send_update({"type": "bot_update", "data": trade})

        # 3) Immediately fire the next buy
        stake = round(self.state.get_next_pointer_stake(), 2)
        try:
            prop     = await self.trade_manager.propose_contract(
                           self.settings.symbol, stake, self.settings.prediction
                       )
            buy_info = await self.trade_manager.buy_contract(prop["proposal_id"], prop["ask_price"])
        except Exception as e:
            logger.error(f"Buy failed at tick {epoch}: {e}")
            return

        self.last_stake = stake
        self.last_epoch = epoch
        # re‑subscribe for closure
        self.trade_manager.api.subscribe_contract_closed(
            buy_info["contract_id"],
            lambda ev: asyncio.create_task(self.handle_closed(ev))
        )
        self.active_contract = {
            "contract_id": buy_info["contract_id"],
            "stake": stake,
            "epoch": epoch,
            "prediction": self.settings.prediction
        }

async def on_tick(tick, ctx: TickContext):
    # 1) Bot still active?
    if not is_bot_running(ctx.user_id):
        return False

    # 2) Balance always comes in via subscription; use last_balance
    bal = ctx.state.last_balance
    if bal is None:
        # very first tick might not have a websocket update yet
        bal, _ = await get_account_balance(ctx.trade_manager.api.token)
        ctx.state.set_balance(bal)

    # 3) Hard stops
    if bal <= ctx.stop_loss_threshold or bal >= ctx.take_profit_threshold:
        ctx.state.stop()
        await ctx.send_update({"message": "🔒 Bot stopped due to balance threshold."})
        await ctx.trade_manager.close()
        return False

    # 4) First trade kickoff
    if ctx.first_trade:
        ctx.first_trade = False
        stake = round(ctx.state.get_next_pointer_stake(), 2)
        try:
            prop     = await ctx.trade_manager.propose_contract(
                           ctx.settings.symbol, stake, ctx.settings.prediction
                       )
            buy_info = await ctx.trade_manager.buy_contract(prop["proposal_id"], prop["ask_price"])
        except Exception as e:
            logger.error(f"Initial buy failed at tick {tick['epoch']}: {e}")
            return True   # keep streaming ticks

        ctx.last_stake = stake
        ctx.last_epoch = tick["epoch"]
        ctx.trade_manager.api.subscribe_contract_closed(
            buy_info["contract_id"],
            lambda ev: asyncio.create_task(ctx.handle_closed(ev))
        )
        ctx.active_contract = {
            "contract_id": buy_info["contract_id"],
            "stake": stake,
            "epoch": tick["epoch"],
            "prediction": ctx.settings.prediction
        }
        return True

    # ✅ Evaluate result manually if contract is active
    if ctx.active_contract:
        result_digit = tick["quote"] % 10
        prediction   = ctx.active_contract["prediction"]
        contract_id  = ctx.active_contract["contract_id"]
        is_win = False

        if prediction.startswith("DIGIT_DIFF_"):
            target = int(prediction.split("_")[-1])
            is_win = result_digit != target
        elif prediction.startswith("DIGIT_MATCH_"):
            target = int(prediction.split("_")[-1])
            is_win = result_digit == target

        trade = {
            "contract_id": contract_id,
            "stake": ctx.active_contract["stake"],
            "profit": round(ctx.active_contract["stake"] if is_win else -ctx.active_contract["stake"], 2),
            "buy_time": ctx.active_contract["epoch"],
            "sell_time": tick["epoch"],
            "result": "win" if is_win else "loss"
        }

        if is_win:
            ctx.state.reset_on_win()
        else:
            ctx.state.record_loss()

        ctx.state.add_trade(trade)
        await ctx.send_update({"type": "bot_update", "data": trade})

        # Next trade
        stake = round(ctx.state.get_next_pointer_stake(), 2)
        try:
            prop     = await ctx.trade_manager.propose_contract(
                           ctx.settings.symbol, stake, ctx.settings.prediction
                       )
            buy_info = await ctx.trade_manager.buy_contract(prop["proposal_id"], prop["ask_price"])
        except Exception as e:
            logger.error(f"Buy failed after result tick {tick['epoch']}: {e}")
            ctx.active_contract = None
            return True

        ctx.last_stake = stake
        ctx.last_epoch = tick["epoch"]
        ctx.trade_manager.api.subscribe_contract_closed(
            buy_info["contract_id"],
            lambda ev: asyncio.create_task(ctx.handle_closed(ev))
        )
        ctx.active_contract = {
            "contract_id": buy_info["contract_id"],
            "stake": stake,
            "epoch": tick["epoch"],
            "prediction": ctx.settings.prediction
        }

    return True
