# navi/cogs/market.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import io
import logging
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.db.repos.market import (
    buy_holding,
    get_market_item,
    get_market_items,
    get_price_history,
    get_user_holding_for_item,
    get_user_holdings,
    reduce_holding,
)
from navi.db.repos.users import get_user_profile
from navi.services.market_engine import get_trend_arrow
from navi.services.market_loop import MARKET_EXPIRY_DAYS
from navi.services.points import add_experience, update_boli_points

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False

logger = logging.getLogger("navi.cogs.market")


def _generate_price_chart(item_label: str, history: list[dict]) -> io.BytesIO:
    """Render a price history chart to an in-memory PNG (runs in executor, blocking is fine)."""
    from matplotlib.ticker import MaxNLocator
    dates, prices = [], []
    for h in history:
        try:
            dt_str = h["date"].replace("T", " ")
            dt = datetime.strptime(dt_str[:16], "%Y-%m-%d %H:%M")
            dates.append(dt)
            prices.append(h["price"])
        except Exception:
            continue

    if not dates:
        raise ValueError("No plottable history entries")

    fig, ax = plt.subplots(figsize=(10, 4), facecolor="#2b2d31")
    ax.set_facecolor("#1e1f22")
    ax.plot(dates, prices, "o-", color="#f0c040", linewidth=2, markersize=4)
    ax.fill_between(dates, prices, min(prices) * 0.98, alpha=0.2, color="#f0c040")
    ax.set_title(item_label, color="white", fontsize=13)
    ax.set_ylabel("Boli", color="#aaaaaa")
    ax.tick_params(colors="#aaaaaa")
    for spine in ax.spines.values():
        spine.set_edgecolor("#555555")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=8))
    plt.xticks(rotation=30, ha="right", color="#aaaaaa")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf


_MARKET_BUY_TEMPLATES: list[str] = [
    "📦 {user} just bought **{qty}× {emoji} {name}** at 🍮 **{price} Boli** each. Bold move.",
    "💸 {user} dropped **{total} Boli** on **{qty}× {emoji} {name}**. We stan a risk-taker.",
    "🛒 Order confirmed! {user} snagged **{qty}× {emoji} {name}** @ {price} Boli. 7 days to flip it.",
]


_MARKET_SELL_TEMPLATES: list[str] = [
    "✅ {user} sold **{qty}× {emoji} {name}** at 🍮 **{price} Boli** each. {pnl_str}",
    "💰 {user} just cashed out **{qty}× {emoji} {name}** for **{total} Boli**. {pnl_str}",
    "📊 Sale complete! {user} offloaded {qty}× {emoji} {name} @ {price} Boli. {pnl_str}",
]


class MarketGroup(app_commands.Group):
    """Boli Stock Market — buy, sell, and hold funny assets."""

    def __init__(self) -> None:
        super().__init__(name="market", description="Boli Stock Market — buy and sell assets for profit")

    @app_commands.command(name="view", description="Browse the Boli Stock Market")
    async def market_view(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        items = get_market_items(ctx.db)
        embed = discord.Embed(
            title="📈 Boli Stock Market",
            description="Prices update daily at midnight IST. Holdings expire in 7 days.",
            color=discord.Color.dark_gold(),
        )
        for item in items:
            trend = get_trend_arrow(item["current_price"], item["base_price"])
            pct = 100 * (item["current_price"] - item["base_price"]) / max(item["base_price"], 1)
            embed.add_field(
                name=f"{item['emoji']} {item['name']} {trend}",
                value=(
                    f"🍮 **{item['current_price']} Boli** "
                    f"*(base: {item['base_price']}, {pct:+.1f}%)*\n"
                    f"_{item['description']}_"
                ),
                inline=False,
            )
        embed.set_footer(text="Use /market buy <item_id> <qty> to invest • /market holdings to see your portfolio")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy a market item with Boli points")
    @app_commands.describe(item_id="Item to buy", quantity="How many to buy (1–10)")
    async def market_buy(
        self,
        interaction: discord.Interaction,
        item_id: str,
        quantity: app_commands.Range[int, 1, 10] = 1,
    ) -> None:
        ctx = interaction.client.ctx
        item = get_market_item(ctx.db, item_id.lower().strip())
        if not item:
            ids = ", ".join(i["item_id"] for i in get_market_items(ctx.db))
            await interaction.response.send_message(
                f"Unknown item `{item_id}`. Valid IDs: {ids}", ephemeral=True
            )
            return

        profile = get_user_profile(ctx.db, interaction.user.id)
        if not profile:
            await interaction.response.send_message("Use /navi first to get started.", ephemeral=True)
            return

        total_cost = item["current_price"] * quantity
        if profile["boli_points"] < total_cost:
            await interaction.response.send_message(
                f"Not enough Boli. This costs 🍮 **{total_cost}** but you have **{profile['boli_points']}**.",
                ephemeral=True,
            )
            return

        expires = datetime.now(timezone.utc) + timedelta(days=MARKET_EXPIRY_DAYS)
        update_boli_points(ctx.db, interaction.user.id, -total_cost)
        buy_holding(ctx.db, interaction.user.id, item["item_id"], quantity, item["current_price"], expires)

        msg = random.choice(_MARKET_BUY_TEMPLATES).format(
            user=interaction.user.mention,
            qty=quantity,
            emoji=item["emoji"],
            name=item["name"],
            price=item["current_price"],
            total=total_cost,
        )
        await interaction.response.send_message(msg)
        logger.info("%s bought %dx %s @ %d Boli", interaction.user.display_name, quantity, item_id, item["current_price"])

    @market_buy.autocomplete("item_id")
    async def market_buy_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        ctx = interaction.client.ctx
        items = get_market_items(ctx.db)
        return [
            app_commands.Choice(name=f"{item['emoji']} {item['name']} — {item['current_price']} Boli", value=item["item_id"])
            for item in items
            if not current or current.lower() in item["item_id"] or current.lower() in item["name"].lower()
        ][:25]

    @app_commands.command(name="sell", description="Sell a market item from your holdings")
    @app_commands.describe(item_id="Item to sell", quantity="How many to sell")
    async def market_sell(
        self,
        interaction: discord.Interaction,
        item_id: str,
        quantity: app_commands.Range[int, 1, 100] = 1,
    ) -> None:
        ctx = interaction.client.ctx
        item = get_market_item(ctx.db, item_id.lower().strip())
        if not item:
            await interaction.response.send_message(f"Unknown item `{item_id}`.", ephemeral=True)
            return

        holdings = get_user_holding_for_item(ctx.db, interaction.user.id, item_id.lower().strip())
        total_held = sum(h["quantity"] for h in holdings)
        if total_held < quantity:
            await interaction.response.send_message(
                f"You only hold **{total_held}×** {item['emoji']} {item['name']}.", ephemeral=True
            )
            return

        # FIFO sell — consume oldest holdings first
        remaining = quantity
        total_cost_basis = 0
        for holding in holdings:
            if remaining <= 0:
                break
            sell_qty = min(remaining, holding["quantity"])
            total_cost_basis += holding["purchase_price"] * sell_qty
            reduce_holding(ctx.db, holding["id"], sell_qty)
            remaining -= sell_qty

        proceeds = item["current_price"] * quantity
        update_boli_points(ctx.db, interaction.user.id, proceeds)
        add_experience(ctx.db, interaction.user.id, max(0, proceeds - total_cost_basis) // 10)  # XP from profit

        pnl = proceeds - total_cost_basis
        pnl_str = f"📈 Profit: +{pnl} Boli" if pnl > 0 else (f"📉 Loss: {pnl} Boli" if pnl < 0 else "Break-even.")
        msg = random.choice(_MARKET_SELL_TEMPLATES).format(
            user=interaction.user.mention,
            qty=quantity,
            emoji=item["emoji"],
            name=item["name"],
            price=item["current_price"],
            total=proceeds,
            pnl_str=pnl_str,
        )
        await interaction.response.send_message(msg)
        logger.info("%s sold %dx %s @ %d Boli (P&L: %+d)", interaction.user.display_name, quantity, item_id, item["current_price"], pnl)

    @market_sell.autocomplete("item_id")
    async def market_sell_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        ctx = interaction.client.ctx
        items = get_market_items(ctx.db)
        return [
            app_commands.Choice(name=f"{item['emoji']} {item['name']} — {item['current_price']} Boli", value=item["item_id"])
            for item in items
            if not current or current.lower() in item["item_id"] or current.lower() in item["name"].lower()
        ][:25]

    @app_commands.command(name="holdings", description="View your current market holdings")
    async def market_holdings(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        holdings = get_user_holdings(ctx.db, interaction.user.id)
        if not holdings:
            await interaction.response.send_message(
                "You have no active holdings. Use `/market buy` to invest!", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="💼 Your Market Holdings",
            color=discord.Color.dark_teal(),
        )
        total_value = 0
        total_cost = 0
        for h in holdings:
            current_val = h["current_price"] * h["quantity"]
            cost_val = h["purchase_price"] * h["quantity"]
            pnl = current_val - cost_val
            pnl_str = f"+{pnl}" if pnl >= 0 else str(pnl)
            # Days left before expiry
            try:
                exp = datetime.fromisoformat(h["expires_at"].replace("Z", "+00:00"))
                days_left = max(0, (exp - datetime.now(timezone.utc)).days)
            except Exception:
                days_left = "?"
            embed.add_field(
                name=f"{h['emoji']} {h['name']} ×{h['quantity']}",
                value=(
                    f"Bought @ {h['purchase_price']} · Now {h['current_price']} · P&L: **{pnl_str} Boli**\n"
                    f"Current value: 🍮 **{current_val}** · Expires in **{days_left}d**"
                ),
                inline=False,
            )
            total_value += current_val
            total_cost += cost_val
        total_pnl = total_value - total_cost
        pnl_sign = "+" if total_pnl >= 0 else ""
        embed.set_footer(text=f"Portfolio value: 🍮 {total_value} Boli · Total P&L: {pnl_sign}{total_pnl} Boli")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="history", description="See price history chart for an item (last 48 data points)")
    @app_commands.describe(item_id="Item to inspect (use ID from /market view)")
    async def market_history(self, interaction: discord.Interaction, item_id: str) -> None:
        ctx = interaction.client.ctx
        item = get_market_item(ctx.db, item_id.lower().strip())
        if not item:
            ids = ", ".join(i["item_id"] for i in get_market_items(ctx.db))
            await interaction.response.send_message(
                f"Unknown item `{item_id}`. Valid IDs: {ids}", ephemeral=True
            )
            return

        history = get_price_history(ctx.db, item_id.lower().strip(), days=48)
        if not history:
            await interaction.response.send_message(
                "No price history yet — the bot records prices hourly. Check back in an hour!", ephemeral=True
            )
            return

        await interaction.response.defer()

        embed = discord.Embed(
            title=f"{item['emoji']} {item['name']} — Price History",
            color=discord.Color.dark_green(),
        )
        embed.set_footer(text=f"Current: 🍮 {item['current_price']} Boli · Prices update every hour")

        if _MATPLOTLIB_AVAILABLE and len(history) > 1:
            chart_file = await asyncio.get_running_loop().run_in_executor(
                None, lambda: _generate_price_chart(item['emoji'] + ' ' + item['name'], history)
            )
            discord_file = discord.File(chart_file, filename="price_chart.png")
            embed.set_image(url="attachment://price_chart.png")
            await interaction.followup.send(embed=embed, file=discord_file)
        else:
            # Fallback text bars
            max_p = max(h["price"] for h in history)
            chart_lines = []
            for h in history[-14:]:  # last 14 points
                bar_len = int(18 * h["price"] / max(max_p, 1))
                bar = "█" * bar_len
                chart_lines.append(f"`{h['date'][:16]}` {bar} **{h['price']}**")
            embed.description = "\n".join(chart_lines)
            await interaction.followup.send(embed=embed)

    @market_history.autocomplete("item_id")
    async def market_history_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        ctx = interaction.client.ctx
        items = get_market_items(ctx.db)
        return [
            app_commands.Choice(name=f"{item['emoji']} {item['name']}", value=item["item_id"])
            for item in items
            if not current or current.lower() in item["item_id"] or current.lower() in item["name"].lower()
        ][:25]


class MarketCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        group = MarketGroup()
        self.ctx.bot.tree.add_command(group)
        self._added.append(group)

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)



async def setup(bot) -> None:
    await bot.add_cog(MarketCog(bot.ctx))
