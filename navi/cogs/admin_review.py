# navi/cogs/admin_review.py - /admin review: pending generated templates and /teach entries, 5 at a time

from __future__ import annotations

import discord

from navi.db.repos.content import list_pending_content, set_content_status
from navi.services.teach import refresh_policy
from navi.db.repos.knowledge import list_pending_knowledge, set_knowledge_status

BATCH = 5


def pending_batch(db) -> list[dict]:
    """Up to 5 pending items, /teach entries first, then generated templates."""
    items = [{"source": "knowledge", **k} for k in list_pending_knowledge(db, BATCH)]
    items += [{"source": "content", **c} for c in list_pending_content(db, BATCH - len(items))] if len(items) < BATCH else []
    return items[:BATCH]


def describe(item: dict) -> str:
    if item["source"] == "knowledge":
        return f"📚 **{item['category']}: {item['term']}** — {item['description']}"
    return f"💬 `{item['kind']}` — {item['text']}"


class ReviewView(discord.ui.View):
    def __init__(self, ctx, user_id: int) -> None:
        super().__init__(timeout=600)
        self.ctx, self.user_id = ctx, user_id
        self.items = pending_batch(ctx.db)
        self.done: dict[int, str] = {}      # item index -> "approved" | "rejected"
        self._build()

    def _build(self) -> None:
        self.clear_items()
        for i, _ in enumerate(self.items):
            resolved = i in self.done
            self.add_item(ReviewButton(self, i, True, resolved))
            self.add_item(ReviewButton(self, i, False, resolved))

    def embed(self) -> discord.Embed:
        if not self.items:
            return discord.Embed(title="Review queue", description="Nothing is waiting for review. 🎉", color=discord.Color.green())
        lines = []
        for i, item in enumerate(self.items):
            state = {"approved": "✅ ", "rejected": "❌ "}.get(self.done.get(i), "")
            lines.append(f"**{i + 1}.** {state}{describe(item)}")
        return discord.Embed(title="Review queue", description="\n".join(lines)[:4000], color=discord.Color.orange())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This review belongs to someone else.", ephemeral=True)
            return False
        return True

    async def decide(self, interaction: discord.Interaction, index: int, approve: bool) -> None:
        item = self.items[index]
        status = "active" if approve else "rejected"
        if item["source"] == "knowledge":
            set_knowledge_status(self.ctx.db, item["id"], status, interaction.user.id)
            refresh_policy(self.ctx)          # an approved 'expression' term becomes an approved Manglish word
        else:
            set_content_status(self.ctx.db, item["id"], status, interaction.user.id)
        self.done[index] = "approved" if approve else "rejected"
        if len(self.done) == len(self.items):          # batch finished: load the next five
            self.items, self.done = pending_batch(self.ctx.db), {}
        self._build()
        await interaction.response.edit_message(embed=self.embed(), view=self)


class ReviewButton(discord.ui.Button):
    def __init__(self, view: ReviewView, index: int, approve: bool, disabled: bool) -> None:
        super().__init__(label=f"{'Approve' if approve else 'Reject'} {index + 1}", row=index, disabled=disabled,
                         style=discord.ButtonStyle.success if approve else discord.ButtonStyle.danger)
        self.review, self.index, self.approve = view, index, approve

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.review.decide(interaction, self.index, self.approve)
