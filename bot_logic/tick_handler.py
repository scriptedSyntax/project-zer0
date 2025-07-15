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

        # for initial trade
        self.first_trade = True

    # async def handle_closed(self, event):
    #     """Called whenever a contract closes."""
    #     cid    = event["contract_id"]
    #     epoch  = event["sell_time"]
    #     profit = round(float(event["profit"]), 2)
    #     loss   = profit < 0

    #     # 1) Martingale pointer update
    #     if loss:
    #         self.state.record_loss()
    #     else:
    #         self.state.reset_on_win()

    #     # 2) Record & notify
    #     trade = {
    #         "contract_id": cid,
    #         "stake":       self.last_stake,
    #         "profit":      profit,
    #         "buy_time":    self.last_epoch,
    #         "sell_time":   epoch,
    #         "result":      "loss" if loss else "win"
    #     }
    #     self.state.add_trade(trade)
    #     await self.send_update({"type": "bot_update", "data": trade})

    #     # 3) Immediately fire the next buy
    #     stake = round(self.state.get_next_pointer_stake(), 2)
    #     try:
    #         prop     = await self.trade_manager.propose_contract(
    #                        self.settings.symbol, stake, self.settings.prediction
    #                    )
    #         buy_info = await self.trade_manager.buy_contract(prop["proposal_id"], prop["ask_price"])
    #     except Exception as e:
    #         logger.error(f"Buy failed at tick {epoch}: {e}")
    #         return

    #     self.last_stake = stake
    #     self.last_epoch = epoch
    #     # re‑subscribe for closure
    #     self.trade_manager.api.subscribe_contract_closed(
    #         buy_info["contract_id"],
    #         lambda ev: asyncio.create_task(self.handle_closed(ev))
    #     )
    async def handle_closed(self, event):
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

        # ✅ 3) Delay before firing next trade (based on user settings)
        delay = max(0, int(self.settings.tick_result_delay or 0))
        if delay > 0:
            logger.info(f"Delaying next trade for {delay} seconds.")
            await asyncio.sleep(delay)

        # 4) Fire the next buy
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

        self.trade_manager.api.subscribe_contract_closed(
            buy_info["contract_id"],
            lambda ev: asyncio.create_task(self.handle_closed(ev))
        )


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
        return True

    # 5) All further logic (if you ever need per‑tick indicators)
    #    e.g. update_result_based_state, etc.  If you don’t have
    #    indicator‑based decisions, you can omit this.
    # update_result_based_state(tick, ctx)
    # decision = make_decision_based_on_previous_result(ctx)
    # if decision.should_trade:
    #     await maybe_place_trade(decision, ctx, tick)

    return True
