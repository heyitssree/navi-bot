# navi/cogs/teach.py - /teach add | list | remove

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from navi.context import AppContext
from navi.db.repos.knowledge import list_knowledge, remove_knowledge
from navi.services.features import deny_if_disabled
from navi.services.mentions import nobody
from navi.services.teach import CATEGORIES, DESC_LEN, TERM_LEN, role_of, submit, validate_entry, refresh_policy

CATEGORY_CHOICES = [app_commands.Choice(name=c.title(), value=c) for c in CATEGORIES]


class AddAnywayView(discord.ui.View):
    def __init__(self, ctx, role, user_id, check, category, tags) -> None:
        super().__init__(timeout=60)
        self.ctx, self.role, self.user_id, self.check, self.category, self.tags = ctx, role, user_id, check, category, tags

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Add anyway", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        status = submit(self.ctx, self.role, self.user_id, self.category, self.check.term, self.check.description, self.tags)
        await interaction.response.edit_message(content=_result_text(status, self.check.term), view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)


def _result_text(status: str, term: str) -> str:
    if status == "active":
        return f"✅ **{term}** is live in Navi's knowledge."
    if status == "pending":
        return f"📝 **{term}** was submitted and waits for review (`/admin review`)."
    return "That term was added by someone else a moment ago."


class TeachGroup(app_commands.Group):
    def __init__(self) -> None:
        super().__init__(name="teach", description="Teach Navi local knowledge")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return not await deny_if_disabled(interaction, "feature.teach")

    @app_commands.command(name="add", description="Add a landmark, food, culture or expression entry")
    @app_commands.describe(category="What kind of entry", term=f"The name ({TERM_LEN[0]}-{TERM_LEN[1]} characters)",
                           description=f"What it is ({DESC_LEN[0]}-{DESC_LEN[1]} characters)", tags="Optional comma-separated tags")
    @app_commands.choices(category=CATEGORY_CHOICES)
    async def add(self, interaction: discord.Interaction, category: str, term: str, description: str, tags: str = "") -> None:
        ctx = interaction.client.ctx
        role = role_of(ctx, interaction.user)
        if role.name is None:
            await interaction.response.send_message("Only the owner, moderators and approved teachers can use /teach.", ephemeral=True)
            return
        check = validate_entry(ctx.db, category, term, description)
        if not check.ok:
            await interaction.response.send_message("❌ " + " ".join(check.problems), ephemeral=True)
            return
        if check.similar_to:
            view = AddAnywayView(ctx, role, interaction.user.id, check, category, tags)
            await interaction.response.send_message(f"This looks similar to **{check.similar_to}**. Add **{check.term}** anyway?", view=view, ephemeral=True)
            return
        status = submit(ctx, role, interaction.user.id, category, check.term, check.description, tags)
        await interaction.response.send_message(_result_text(status, check.term), ephemeral=True, allowed_mentions=nobody())

    @app_commands.command(name="list", description="Show knowledge entries by status")
    @app_commands.choices(status=[app_commands.Choice(name=s, value=s) for s in ("active", "pending", "rejected")])
    async def list_cmd(self, interaction: discord.Interaction, status: str = "active") -> None:
        ctx = interaction.client.ctx
        if role_of(ctx, interaction.user).name is None:
            await interaction.response.send_message("Only the owner, moderators and approved teachers can use /teach.", ephemeral=True)
            return
        rows = list_knowledge(ctx.db, status, 25)
        body = "\n".join(f"• **{r['term']}** ({r['category']}): {r['description'][:80]}" for r in rows) or "Nothing here."
        await interaction.response.send_message(f"**{status.title()} entries** (latest 25)\n{body}", ephemeral=True, allowed_mentions=nobody())

    @app_commands.command(name="remove", description="Delete an entry by its term (owner and moderators)")
    async def remove(self, interaction: discord.Interaction, term: str) -> None:
        ctx = interaction.client.ctx
        if not role_of(ctx, interaction.user).publishes_immediately:
            await interaction.response.send_message("Only the owner and moderators can remove entries.", ephemeral=True)
            return
        removed = remove_knowledge(ctx.db, term)
        if removed:
            refresh_policy(ctx)
        await interaction.response.send_message(f"Removed {removed} entr{'y' if removed == 1 else 'ies'} named **{term}**." if removed else f"No entry named **{term}**.", ephemeral=True, allowed_mentions=nobody())


class TeachCog(commands.Cog):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._added: list = []

    async def cog_load(self) -> None:
        group = TeachGroup()
        self.ctx.bot.tree.add_command(group)
        self._added.append(group)

    async def cog_unload(self) -> None:
        for cmd in self._added:
            self.ctx.bot.tree.remove_command(cmd.name, type=cmd.type)


async def setup(bot) -> None:
    await bot.add_cog(TeachCog(bot.ctx))
