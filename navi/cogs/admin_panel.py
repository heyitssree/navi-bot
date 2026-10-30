# navi/cogs/admin_panel.py - the /admin panel: ephemeral, 10 minute timeout, only the invoker can use it.
#
#   home      select a category; the embed shows how many settings differ from their default
#   category  embed with every setting's value (marked when changed) + a select of settings (25 per page)
#   setting   label, help, current value, default and a control for the kind:
#             toggle (bool) | modal (numbers, text, id lists) | select (choices) | channel/role select; Reset; Back

from __future__ import annotations

import logging

import discord

from navi.settings.registry import CATEGORIES, SETTINGS, resolve
from navi.settings.store import SettingError, format_value

logger = logging.getLogger("navi.cogs.admin_panel")

PAGE_SIZE = 25
COLOR = discord.Color.blurple()


def settings_in(category: str):
    return [s for s in SETTINGS if s.category == category and not s.hidden]


class PanelView(discord.ui.View):
    def __init__(self, ctx, user_id: int) -> None:
        super().__init__(timeout=600)
        self.ctx = ctx
        self.user_id = user_id
        self.mode = "home"
        self.category: str | None = None
        self.key: str | None = None
        self.page = 0
        self.notice = ""
        self.message: discord.Message | None = None
        self._rebuild()

    # ---------------------------------------------------------------- plumbing
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This panel belongs to someone else. Run /admin panel yourself.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def show(self, interaction: discord.Interaction) -> None:
        self._rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    # ---------------------------------------------------------------- state changes
    def go_home(self) -> None:
        self.mode, self.category, self.key, self.page = "home", None, None, 0

    def go_category(self, category: str, page: int = 0) -> None:
        self.mode, self.category, self.key, self.page = "category", category, None, page

    def go_setting(self, key: str) -> None:
        self.mode, self.key = "setting", key

    def apply(self, key: str, value, interaction: discord.Interaction) -> None:
        """Store a value from a control; the confirmation (or the validation error) becomes the embed's notice line."""
        setting = resolve(key)
        try:
            stored = self.ctx.settings.set(key, value, by=interaction.user.id)
            self.notice = f"✅ {setting.label} is now **{format_value(setting, stored)}**." + (" (takes effect after a restart)" if setting.restart else "")
            llm = self.ctx.llm
            if key in ("ai.provider", "ai.fallback_provider") and llm is not None and stored not in ("off", *llm.providers):
                self.notice += f"\n⚠️ {stored} is not configured on this server, so replies will use fallbacks."
        except SettingError as exc:
            self.notice = f"❌ {exc}"

    # ---------------------------------------------------------------- embeds
    def embed(self) -> discord.Embed:
        if self.mode == "home":
            emb = discord.Embed(title="⚙️ Navi settings", description="Pick a category. ✏️ counts settings changed from their default.", color=COLOR)
            for cat, (changed, total) in self.ctx.settings.category_counts().items():
                emb.add_field(name=cat, value=f"{total} settings" + (f" · ✏️ {changed}" if changed else ""), inline=True)
        elif self.mode == "category":
            items = settings_in(self.category)
            start = self.page * PAGE_SIZE
            lines = []
            for s in items[start:start + PAGE_SIZE]:
                mark = "" if self.ctx.settings.is_default(s.key) else " ✏️"
                lines.append(f"**{s.label}** — {format_value(s, self.ctx.settings.get(s.key))}{mark}")
            pages = max(1, -(-len(items) // PAGE_SIZE))
            emb = discord.Embed(title=f"⚙️ {self.category}", description="\n".join(lines) or "Nothing here.", color=COLOR)
            emb.set_footer(text=f"Page {self.page + 1}/{pages} · pick a setting below to change it")
        else:
            s = resolve(self.key)
            emb = discord.Embed(title=s.label, description=s.help or " ", color=COLOR)
            emb.add_field(name="Current", value=format_value(s, self.ctx.settings.get(s.key)), inline=True)
            emb.add_field(name="Default", value=format_value(s, s.default), inline=True)
            if s.kind in ("int", "float") and s.min is not None:
                emb.add_field(name="Allowed", value=f"{s.min:g} to {s.max:g}", inline=True)
            if s.kind == "choice":
                emb.add_field(name="Options", value=", ".join(s.choices), inline=True)
            emb.set_footer(text=s.key)
        if self.notice:
            emb.add_field(name="​", value=self.notice, inline=False)
        return emb

    # ---------------------------------------------------------------- components
    def _rebuild(self) -> None:
        self.clear_items()
        if self.mode == "home":
            self.add_item(CategorySelect(self))
            return
        if self.mode == "category":
            items = settings_in(self.category)
            start = self.page * PAGE_SIZE
            self.add_item(SettingSelect(self, items[start:start + PAGE_SIZE]))
            if len(items) > PAGE_SIZE:
                self.add_item(PageButton(self, -1, disabled=self.page == 0))
                self.add_item(PageButton(self, +1, disabled=start + PAGE_SIZE >= len(items)))
            self.add_item(BackButton(self))
            return
        s = resolve(self.key)
        if s.kind == "bool":
            current = bool(self.ctx.settings.get(s.key))
            self.add_item(ToggleButton(self, s, current))
        elif s.kind == "choice":
            self.add_item(ChoiceSelect(self, s))
        elif s.kind == "channel":
            self.add_item(ChannelPicker(self, s))
        elif s.kind == "role":
            self.add_item(RolePicker(self, s))
        else:
            self.add_item(EditButton(self, s))
        self.add_item(ResetButton(self, s, disabled=self.ctx.settings.is_default(s.key)))
        self.add_item(BackButton(self))


class CategorySelect(discord.ui.Select):
    def __init__(self, view: PanelView) -> None:
        counts = view.ctx.settings.category_counts()
        options = [discord.SelectOption(label=c, value=c, description=f"{counts[c][1]} settings" + (f", {counts[c][0]} changed" if counts[c][0] else ""))
                   for c in CATEGORIES if counts[c][1]]
        super().__init__(placeholder="Choose a category", options=options)
        self.panel = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.notice = ""
        self.panel.go_category(self.values[0])
        await self.panel.show(interaction)


class SettingSelect(discord.ui.Select):
    def __init__(self, view: PanelView, items) -> None:
        options = [discord.SelectOption(label=s.label[:100], value=s.key, description=format_value(s, view.ctx.settings.get(s.key))[:100]) for s in items]
        super().__init__(placeholder="Choose a setting", options=options)
        self.panel = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.notice = ""
        self.panel.go_setting(self.values[0])
        await self.panel.show(interaction)


class PageButton(discord.ui.Button):
    def __init__(self, view: PanelView, step: int, disabled: bool) -> None:
        super().__init__(label="◀ Prev" if step < 0 else "Next ▶", style=discord.ButtonStyle.secondary, disabled=disabled)
        self.panel, self.step = view, step

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.go_category(self.panel.category, self.panel.page + self.step)
        await self.panel.show(interaction)


class BackButton(discord.ui.Button):
    def __init__(self, view: PanelView) -> None:
        super().__init__(label="Back", style=discord.ButtonStyle.secondary)
        self.panel = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.notice = ""
        if self.panel.mode == "setting":
            self.panel.go_category(self.panel.category or resolve(self.panel.key).category, self.panel.page)
        else:
            self.panel.go_home()
        await self.panel.show(interaction)


class ToggleButton(discord.ui.Button):
    def __init__(self, view: PanelView, setting, current: bool) -> None:
        super().__init__(label="Turn off" if current else "Turn on", style=discord.ButtonStyle.danger if current else discord.ButtonStyle.success)
        self.panel, self.setting, self.current = view, setting, current

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.apply(self.setting.key, not self.current, interaction)
        await self.panel.show(interaction)


class ResetButton(discord.ui.Button):
    def __init__(self, view: PanelView, setting, disabled: bool) -> None:
        super().__init__(label="Reset to default", style=discord.ButtonStyle.secondary, disabled=disabled)
        self.panel, self.setting = view, setting

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.ctx.settings.reset(self.setting.key, by=interaction.user.id)
        self.panel.notice = f"↩️ {self.setting.label} reset to **{format_value(self.setting, self.setting.default)}**."
        await self.panel.show(interaction)


class ChoiceSelect(discord.ui.Select):
    def __init__(self, view: PanelView, setting) -> None:
        current = view.ctx.settings.get(setting.key)
        super().__init__(placeholder="Choose a value", options=[discord.SelectOption(label=c, value=c, default=c == current) for c in setting.choices])
        self.panel, self.setting = view, setting

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.apply(self.setting.key, self.values[0], interaction)
        await self.panel.show(interaction)


class ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, view: PanelView, setting) -> None:
        super().__init__(placeholder="Choose a channel", channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
        self.panel, self.setting = view, setting

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.apply(self.setting.key, self.values[0].id, interaction)
        await self.panel.show(interaction)


class RolePicker(discord.ui.RoleSelect):
    def __init__(self, view: PanelView, setting) -> None:
        super().__init__(placeholder="Choose a role", min_values=1, max_values=1)
        self.panel, self.setting = view, setting

    async def callback(self, interaction: discord.Interaction) -> None:
        self.panel.apply(self.setting.key, self.values[0].id, interaction)
        await self.panel.show(interaction)


class EditButton(discord.ui.Button):
    def __init__(self, view: PanelView, setting) -> None:
        super().__init__(label="Edit", style=discord.ButtonStyle.primary)
        self.panel, self.setting = view, setting

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(EditModal(self.panel, self.setting))


class EditModal(discord.ui.Modal):
    def __init__(self, view: PanelView, setting) -> None:
        super().__init__(title=setting.label[:45])
        self.panel, self.setting = view, setting
        hint = f"{setting.min:g} to {setting.max:g}" if setting.kind in ("int", "float") and setting.min is not None else setting.kind
        self.value = discord.ui.TextInput(
            label=setting.label[:45], placeholder=hint[:100], required=True, max_length=200,
            default=format_value(setting, view.ctx.settings.get(setting.key)).replace("(empty)", "")[:200],
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = self.panel.ctx.settings.set_text(self.setting.key, self.value.value, by=interaction.user.id)
            self.panel.notice = f"✅ {self.setting.label} is now **{format_value(self.setting, value)}**."
        except SettingError as exc:
            self.panel.notice = f"❌ {exc}"
        await self.panel.show(interaction)
