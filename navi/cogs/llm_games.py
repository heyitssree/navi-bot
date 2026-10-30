# navi/cogs/llm_games.py - moved from bot.py (behaviour unchanged)
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone

import discord

from navi.db.repos.content import (
    dialogue_exists,
    get_movie_dialogue_count,
    get_random_movie_dialogue,
    get_score_comment,
    save_movie_dialogue,
    save_score_comment,
)
from navi.db.repos.counters import _GEMINI_GAME_DAILY_LIMIT, get_gemini_game_daily_count, increment_gemini_game_count
from navi.db.repos.knowledge import get_random_knowledge_terms
from navi.db.repos.users import get_user_profile
from navi.llm.base import LLMRequest
from navi.services.points import award

logger = logging.getLogger("navi.cogs.llm_games")


_TYPE_RACE_RULES = (
    "📋 **How to play:**\n"
    "• **Option A — Malayalam script** → scored **0–100** "
    "(accuracy of meaning + Trivandrum regional accent)\n"
    "• **Option B — Manglish slang** → max **50 pts** even if perfect "
    "(how a Trivandrum local would say it out loud)\n"
    "• You have **60 seconds** once you hit Start\n"
    "• Foul language = zero marks, full stop\n"
    "• Scoring is strict — average effort gets 30–55"
)


def _is_malayalam_script(text: str) -> bool:
    """True if the text contains any Malayalam Unicode characters (U+0D00–U+0D7F)."""
    return any('ഀ' <= ch <= 'ൿ' for ch in text)


# DISABLED: @tree.command(name="navi_challenge", description="Navi Challenge — write a cosmic prediction using 3 random keywords (2 attempts/day)")
async def navi_challenge_slash(interaction: discord.Interaction) -> None:
    ctx = interaction.client.ctx
    if not ctx.settings.feat("feature_navi_challenge"):
        await interaction.response.send_message("Navi Challenge is currently disabled.", ephemeral=True)
        return

    loop = asyncio.get_running_loop()
    count, profile, keywords = await loop.run_in_executor(
        None,
        lambda: (
            get_gemini_game_daily_count(ctx.db, interaction.user.id, "navi_challenge"),
            get_user_profile(ctx.db, interaction.user.id),
            get_random_knowledge_terms(ctx.db, num_categories=3),
        ),
    )
    testing = ctx.settings.is_testing_guild(interaction.guild_id)
    if not profile:
        await interaction.response.send_message("Use /navi first to get started.", ephemeral=True)
        return
    if not testing and count >= _GEMINI_GAME_DAILY_LIMIT:
        await interaction.response.send_message(
            "You've used both your **Navi Challenge** attempts for today. Come back after midnight IST!",
            ephemeral=True,
        )
        return
    if not keywords:
        await interaction.response.send_message("Knowledge base is empty — contact the bot admin.", ephemeral=True)
        return

    if not testing:
        await loop.run_in_executor(
            None, lambda: increment_gemini_game_count(ctx.db, interaction.user.id, "navi_challenge")
        )

    keyword_lines = "\n".join(
        f"• **{k['term']}** *(_{k['category']}_)* — {k['description'][:70]}"
        for k in keywords
    )
    start_time = datetime.now(timezone.utc)
    modal = NaviChallengeModal(keywords=keywords, start_time=start_time, score_comment_cache={})

    # send_modal is the only way to present modals — use it as the immediate response
    await interaction.response.send_modal(modal)
    # followup shows the keywords publicly in the channel
    attempt_line = "*(🧪 Testing mode — unlimited attempts, no rewards)*" if testing else f"*(Attempt {count + 1}/{_GEMINI_GAME_DAILY_LIMIT} today)*"
    kw_content = (
        f"🔮 **Navi Challenge for {interaction.user.mention}!**\n"
        f"Write a **Navi-style cosmic prediction** (max 2 sentences) using all 3 keywords below.\n"
        f"Modal is open — you have **90 seconds**. {attempt_line}\n\n"
        f"{keyword_lines}"
    )
    kw_msg = await interaction.followup.send(kw_content)
    # Edit the keywords message after 91s to signal the window has closed
    async def _navi_timeout_edit() -> None:
        await asyncio.sleep(92)
        try:
            await kw_msg.edit(content=kw_content + "\n\n⏰ *90-second window has closed.*")
        except Exception:
            pass
    asyncio.create_task(_navi_timeout_edit())
    logger.info(
        "Navi Challenge started for %s (attempt %d, keywords: %s)",
        interaction.user.display_name, count + 1, [k["term"] for k in keywords],
    )


# DISABLED: @tree.command(name="type_race", description="Translate a movie dialogue into Malayalam or Trivandrum Manglish — 60 seconds (2 attempts/day)")
async def type_race_slash(interaction: discord.Interaction) -> None:
    ctx = interaction.client.ctx
    if not ctx.settings.feat("feature_type_race"):
        await interaction.response.send_message("Type Race is currently disabled.", ephemeral=True)
        return

    loop = asyncio.get_running_loop()
    count, profile = await loop.run_in_executor(
        None,
        lambda: (
            get_gemini_game_daily_count(ctx.db, interaction.user.id, "type_race"),
            get_user_profile(ctx.db, interaction.user.id),
        ),
    )
    testing = ctx.settings.is_testing_guild(interaction.guild_id)
    if not profile:
        await interaction.response.send_message("Use /navi first to get started.", ephemeral=True)
        return
    if not testing and count >= _GEMINI_GAME_DAILY_LIMIT:
        await interaction.response.send_message(
            "You've used both your **Type Race** attempts for today. Come back after midnight IST!",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)

    _DIALOGUE_CACHE_LIMIT = 300
    dialogue_count = await loop.run_in_executor(None, lambda: get_movie_dialogue_count(ctx.db))

    _DIALOGUE_GENRES = [
        "90s action blockbusters",
        "Disney or Pixar animated films",
        "Marvel or DC superhero movies",
        "classic sci-fi films (Star Wars, Matrix, Terminator, etc.)",
        "90s or 2000s comedies",
        "thriller or suspense films",
        "80s cult classics",
        "romantic comedies",
        "war or historical epics",
        "heist or crime films",
        "horror or dark films (no gore references)",
        "sports films",
        "coming-of-age films",
    ]

    if dialogue_count >= _DIALOGUE_CACHE_LIMIT:
        # Cache is full — use it exclusively, no API call needed
        sentence = await loop.run_in_executor(None, lambda: get_random_movie_dialogue(ctx.db))
        if not sentence:
            sentence = "Why so serious? Let's put a smile on that face."
        logger.info("Type Race: using cached dialogue (%d in cache)", dialogue_count)
    else:
        gen_system = "You are a movie buff. Reply with ONLY the dialogue line, no movie title, no speaker name, no quotes, nothing else. Never include foul or abusive language."
        sentence = None
        for attempt in range(3):
            try:
                attempt_genre = random.choice(_DIALOGUE_GENRES)
                attempt_prompt = (
                    f"Pick ONE iconic, funny, or dramatically memorable line specifically from {attempt_genre}. "
                    f"It must be a line a Trivandrum crowd would recognise or find hilarious to translate into Malayalam. "
                    f"The line must be clean (no profanity), in plain English, 8-20 words, and stand alone without needing context. "
                    f"Do NOT pick the most obvious or overused line — surprise us. "
                    f"Output ONLY the dialogue line itself."
                )
                _res = await ctx.llm.generate(
                    LLMRequest(purpose="template_batch", system=gen_system, prompt=attempt_prompt),
                    fallback="",
                    name="TypeRace",
                    cache_type="type_race",
                )
                raw_sentence = _res.text
                candidate = (raw_sentence or "").strip().strip('"').strip("'")
                if not candidate or len(candidate) < 8:
                    logger.warning("Type Race: attempt %d returned empty sentence, retrying", attempt + 1)
                    continue
                is_dupe = await loop.run_in_executor(None, lambda: dialogue_exists(ctx.db, candidate))
                if is_dupe:
                    logger.info("Type Race: attempt %d duplicate (%r), retrying", attempt + 1, candidate[:50])
                    continue
                # Unique — save and use it
                await loop.run_in_executor(None, lambda: save_movie_dialogue(ctx.db, candidate))
                sentence = candidate
                logger.info("Type Race: new dialogue cached after %d attempt(s) (%d → %d, genre: %s)",
                            attempt + 1, dialogue_count, dialogue_count + 1, attempt_genre)
                break
            except Exception as exc:
                logger.error("Type Race sentence generation attempt %d error: %s", attempt + 1, exc)

        if not sentence:
            # All attempts failed or were duplicates — fall back to cache, then hardcoded
            sentence = await loop.run_in_executor(None, lambda: get_random_movie_dialogue(ctx.db))
            if not sentence:
                sentence = "Why so serious? Let's put a smile on that face."
            logger.info("Type Race: fell back to cached/hardcoded dialogue after 3 attempts")

    if not testing:
        await loop.run_in_executor(
            None, lambda: increment_gemini_game_count(ctx.db, interaction.user.id, "type_race")
        )

    attempt_line = "🧪 *Testing mode — unlimited attempts, no rewards*" if testing else f"*Attempt {count + 1}/{_GEMINI_GAME_DAILY_LIMIT} today*"
    view = TypeRaceStartView(sentence=sentence, user_id=interaction.user.id)
    msg = await interaction.followup.send(
        f"⌨️ **Type Race for {interaction.user.mention}!**\n\n"
        f"{_TYPE_RACE_RULES}\n\n"
        f"**🎬 Translate this movie dialogue:**\n"
        f">>> {sentence}\n\n"
        f"*Click the button when you're ready — timer starts then.* {attempt_line}",
        view=view,
    )
    view.message = msg
    logger.info(
        "Type Race started for %s (attempt %d, testing=%s, sentence len=%d)",
        interaction.user.display_name, count + 1, testing, len(sentence),
    )


class NaviChallengeModal(discord.ui.Modal, title="🔮 Navi Challenge — Your Cosmic Prediction"):
    def __init__(
        self,
        keywords: list[dict],
        start_time: datetime,
        score_comment_cache: dict,
    ) -> None:
        super().__init__()
        self.keywords = keywords
        self.start_time = start_time
        self.score_comment_cache = score_comment_cache
        # Show keywords in placeholder so user can read them while the modal overlay is open
        kw_hint = " · ".join(k["term"] for k in keywords)
        kw_hint = kw_hint if len(kw_hint) <= 97 else kw_hint[:97] + "…"
        self.prediction = discord.ui.TextInput(
            label="Your prediction (use all 3 keywords)",
            style=discord.TextStyle.paragraph,
            placeholder=kw_hint,
            max_length=500,
            required=True,
        )
        self.add_item(self.prediction)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ctx = interaction.client.ctx
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        if elapsed > 90:
            await interaction.response.send_message(
                "⏱️ Time's up! You had 90 seconds. Better luck next time.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        keyword_str = ", ".join(f"**{k['term']}**" for k in self.keywords)
        user_prediction = self.prediction.value.strip()

        system_prompt = (
            "You are a harsh, witty cosmic judge. Reply ONLY with valid JSON. Be strict — most attempts deserve 30-60. Reserve high scores for genuinely impressive predictions."
        )
        prompt = (
            f"A user was given these 3 Trivandrum-themed keywords: {keyword_str}.\n"
            f"Their 2-sentence cosmic Navi-style prediction is:\n\"{user_prediction}\"\n\n"
            f"Judge STRICTLY on:\n"
            f"1. Did they use all 3 keywords meaningfully — not just shoehorned in? (40 pts)\n"
            f"2. Is it genuinely creative and Navi-like in tone — dry, deadpan, local? (30 pts)\n"
            f"3. Is the Trivandrum vibe authentic and specific — not generic? (30 pts)\n\n"
            f"STRICT GRADING SCALE (apply this rigorously):\n"
            f"- 0-20: Keywords missing or prediction makes no sense\n"
            f"- 21-40: Keywords mentioned but forced, generic prediction\n"
            f"- 41-60: Decent use of keywords but lacks Navi voice or Trivandrum flavour\n"
            f"- 61-75: Good — keywords woven in, some Trivandrum character\n"
            f"- 76-88: Strong — all keywords used well, genuinely Navi-toned\n"
            f"- 89-100: Reserved for predictions that are genuinely clever, specific, and perfectly capture Navi's voice\n\n"
            f"Do NOT use foul language. Reply ONLY with this JSON:\n"
            f'{{\"score\": <0-100>, \"comment\": \"<one short witty sentence>\"}}'
        )
        try:
            loop = asyncio.get_running_loop()
            _fallback = '{"score": 50, "comment": "The cosmos is unreachable right now."}'
            _res = await ctx.llm.generate(
                LLMRequest(purpose="template_batch", system=system_prompt, prompt=prompt),
                fallback=_fallback,
                name=interaction.user.display_name,
                cache_type="navi_challenge",
            )
            raw = _res.text
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                score = max(0, min(100, int(data.get("score", 50))))
                gemini_comment = data.get("comment", "The cosmos is unimpressed.")
            else:
                score = 50
                gemini_comment = "Navi couldn't parse the cosmic data. Defaulting to 50."
        except Exception as exc:
            logger.error("Navi Challenge Gemini error: %s", exc)
            score = 50
            gemini_comment = "The cosmic judging system is temporarily offline."

        # Try cached comment first, then save the new one
        cached = get_score_comment(ctx.db, "navi_challenge", score)
        if cached and random.random() < 0.7:
            display_comment = cached
        else:
            display_comment = gemini_comment
            try:
                save_score_comment(ctx.db, "navi_challenge", score, gemini_comment)
            except Exception:
                pass

        boli_award = score
        xp_award = score // 2
        testing = ctx.settings.is_testing_guild(interaction.guild_id)
        if not testing:
            award(ctx.db, interaction.user.id, boli_award, xp_award, reason="game", detail="navi_challenge")

        color = discord.Color.green() if score >= 70 else (discord.Color.orange() if score >= 40 else discord.Color.red())
        embed = discord.Embed(
            title="🔮 Navi Challenge — Results",
            color=color,
        )
        embed.add_field(name="Your Prediction", value=f"_{user_prediction}_", inline=False)
        embed.add_field(name="Keywords Used", value=keyword_str, inline=False)
        reward_line = (
            f"**{score}/100** *(🧪 Testing mode — no rewards credited)*"
            if testing else
            f"**{score}/100** → +🍮 **{boli_award} Boli** & +✨ **{xp_award} XP**"
        )
        embed.add_field(name="Score", value=reward_line, inline=False)
        embed.add_field(name="Navi's Verdict", value=f"_{display_comment}_", inline=False)
        embed.set_footer(text=f"Judged by Gemini · Time taken: {int(elapsed)}s of 90s")
        await interaction.followup.send(embed=embed)
        logger.info(
            "Navi Challenge: %s scored %d (keywords: %s, testing=%s)",
            interaction.user.display_name, score, [k["term"] for k in self.keywords], testing,
        )


class TypeRaceModal(discord.ui.Modal, title="⌨️ Type Race — Malayalam or Manglish?"):
    def __init__(self, sentence: str, start_time: datetime, view: "TypeRaceStartView") -> None:
        super().__init__()
        self.sentence = sentence
        self.start_time = start_time
        self._view = view
        placeholder = sentence if len(sentence) <= 97 else sentence[:97] + "…"
        self.answer = discord.ui.TextInput(
            label="Malayalam (max 100) or Manglish (max 50)",
            style=discord.TextStyle.paragraph,
            placeholder=placeholder,
            max_length=400,
            required=True,
        )
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        if elapsed > 60:
            await interaction.response.send_message(
                "⏱️ Time's up! You had 60 seconds. Faster next time!", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        self._view._modal_submitted = True  # cancel the 62s timeout-edit task

        try:
            await self._judge_and_respond(interaction, elapsed)
        except Exception as exc:
            logger.error("Type Race on_submit unhandled error: %s", exc, exc_info=True)
            try:
                await interaction.followup.send(
                    "Something went wrong judging your answer. This attempt has not been counted.",
                    ephemeral=True,
                )
            except Exception:
                pass

    async def _judge_and_respond(self, interaction: discord.Interaction, elapsed: float) -> None:
        ctx = interaction.client.ctx
        user_answer = self.answer.value.strip()
        is_malayalam = _is_malayalam_script(user_answer)

        if is_malayalam:
            score_cap = 100
            mode_label = "Malayalam script"
            system_prompt = (
                "You are a strict Malayalam language judge with a sharp Trivandrum ear. "
                "Reply ONLY with valid JSON. Be harsh — most attempts deserve 30–60. "
                "Only genuinely precise, beautifully localised translations deserve above 80."
            )
            prompt = (
                f"The user was given this famous English movie dialogue to translate into Malayalam "
                f"(Kerala/Trivandrum accent and phrasing):\n\"{self.sentence}\"\n\n"
                f"Their Malayalam translation:\n\"{user_answer}\"\n\n"
                f"Judge STRICTLY on:\n"
                f"1. Meaning accuracy — does it faithfully convey the original idea? (50 pts)\n"
                f"2. Trivandrum accent and phrasing — would a Trivandrum local actually say it this way? (30 pts)\n"
                f"3. Script correctness — is the Malayalam script properly written? (20 pts)\n\n"
                f"STRICT GRADING SCALE:\n"
                f"- 0-20: Wrong meaning or barely recognisable Malayalam\n"
                f"- 21-40: Attempted but meaning is off or script is poor\n"
                f"- 41-60: Correct meaning but generic Kerala Malayalam, no Trivandrum flavour\n"
                f"- 61-75: Good meaning, some Trivandrum character in phrasing\n"
                f"- 76-88: Strong — accurate meaning, proper script, clear Trivandrum accent\n"
                f"- 89-100: Near-perfect — only for genuinely precise, beautifully localised translations\n\n"
                f"Do NOT use foul language in your comment. Reply ONLY with this JSON:\n"
                f'{{\"score\": <0-100>, \"comment\": \"<one short witty sentence>\"}}'
            )
            fallback_score = 40
        else:
            score_cap = 50
            mode_label = "Manglish slang"
            system_prompt = (
                "You are a strict Trivandrum slang judge. "
                "Reply ONLY with valid JSON. Be harsh — most attempts deserve 15–30. "
                "The absolute maximum score is 50, only for genuinely brilliant Trivandrum slang."
            )
            prompt = (
                f"The user was given this famous English movie dialogue to translate into Trivandrum Manglish slang:\n\"{self.sentence}\"\n\n"
                f"Their Manglish attempt:\n\"{user_answer}\"\n\n"
                f"Judge STRICTLY on (MAX SCORE IS 50):\n"
                f"1. Meaning accuracy — same core idea as the original? (20 pts)\n"
                f"2. Trivandrum slang authenticity — sounds like a real local, not generic Manglish? (20 pts)\n"
                f"3. Natural flow and wit (10 pts)\n\n"
                f"STRICT GRADING SCALE (out of 50):\n"
                f"- 0-10: Wrong meaning or barely tried\n"
                f"- 11-20: Attempted but weak or very generic slang\n"
                f"- 21-30: Decent meaning, some slang but not distinctly Trivandrum\n"
                f"- 31-40: Good — recognisable meaning, authentic Trivandrum flavour\n"
                f"- 41-50: Only for genuinely brilliant, perfectly local Manglish — very rare\n\n"
                f"Do NOT use foul language in your comment. Reply ONLY with this JSON:\n"
                f'{{\"score\": <0-50>, \"comment\": \"<one short witty sentence>\"}}'
            )
            fallback_score = 20

        try:
            loop = asyncio.get_running_loop()
            _fallback = f'{{"score": {fallback_score}, "comment": "Cosmic judges are on a chai break."}}'
            _res = await ctx.llm.generate(
                LLMRequest(purpose="template_batch", system=system_prompt, prompt=prompt),
                fallback=_fallback,
                name=interaction.user.display_name,
                cache_type="type_race",
            )
            raw = _res.text
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                raw_score = max(0, min(score_cap, int(data.get("score", fallback_score))))
                score = raw_score
                gemini_comment = data.get("comment", "The cosmos cannot process this.")
            else:
                score = fallback_score
                gemini_comment = "The cosmic typesetter has crashed."
        except Exception as exc:
            logger.error("Type Race Gemini error: %s", exc)
            score = fallback_score
            gemini_comment = "The cosmic judging system is offline."

        cached = get_score_comment(ctx.db, "type_race", score)
        if cached and random.random() < 0.7:
            display_comment = cached
        else:
            display_comment = gemini_comment
            try:
                save_score_comment(ctx.db, "type_race", score, gemini_comment)
            except Exception:
                pass

        boli_award = score
        xp_award = score // 2
        testing = ctx.settings.is_testing_guild(interaction.guild_id)
        if not testing:
            award(ctx.db, interaction.user.id, boli_award, xp_award, reason="game", detail="type_race")

        color = discord.Color.green() if score >= (60 if is_malayalam else 35) else (
            discord.Color.orange() if score >= (30 if is_malayalam else 15) else discord.Color.red()
        )
        embed = discord.Embed(title="⌨️ Type Race — Results", color=color)
        embed.add_field(name="Movie Dialogue", value=f"_{self.sentence}_", inline=False)
        embed.add_field(
            name=f"Your Answer ({mode_label})",
            value=f"_{user_answer}_",
            inline=False,
        )
        reward_line = (
            f"**{score}/{score_cap}** *(🧪 Testing mode — no rewards credited)*"
            if testing else
            f"**{score}/{score_cap}** → +🍮 **{boli_award} Boli** & +✨ **{xp_award} XP**"
        )
        embed.add_field(name="Score", value=reward_line, inline=False)
        embed.add_field(name="Navi's Verdict", value=f"_{display_comment}_", inline=False)
        embed.set_footer(text=f"Mode: {mode_label} · Judged by Gemini · Time: {int(elapsed)}s of 60s")
        await interaction.followup.send(embed=embed)
        logger.info(
            "Type Race: %s scored %d/%d (%s) in %.0fs",
            interaction.user.display_name, score, score_cap, mode_label, elapsed,
        )


class TypeRaceStartView(discord.ui.View):
    """Button that opens the typing modal when clicked. Timer starts on click."""

    def __init__(self, sentence: str, user_id: int) -> None:
        super().__init__(timeout=120)
        self.sentence = sentence
        self.user_id = user_id
        self._used = False
        self.message: discord.Message | None = None
        self._modal_submitted = False
        self._timeout_task: asyncio.Task | None = None

    @discord.ui.button(label="Start Typing (60s timer starts now)", style=discord.ButtonStyle.danger, emoji="⌨️")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your race!", ephemeral=True)
            return
        if self._used:
            await interaction.response.send_message("You've already started this attempt.", ephemeral=True)
            return
        self._used = True
        start_time = datetime.now(timezone.utc)
        modal = TypeRaceModal(sentence=self.sentence, start_time=start_time, view=self)
        await interaction.response.send_modal(modal)
        # Keep sentence visible in the message while modal overlay is open
        button.disabled = True
        button.label = "⏱️ Timer running…"
        try:
            await interaction.message.edit(
                content=(
                    f"⌨️ **Type Race — ⏱️ Timer running! (60 seconds)**\n"
                    f"**Translate this movie dialogue** — Malayalam script (max 100) or Manglish slang (max 50):\n"
                    f">>> {self.sentence}"
                ),
                view=self,
            )
        except Exception:
            pass
        # Background task: mark time's-up on the message if modal is not submitted in time
        self._timeout_task = asyncio.create_task(self._race_timeout())
        self.stop()

    async def _race_timeout(self) -> None:
        await asyncio.sleep(62)
        if self._modal_submitted:
            return
        if self.message:
            try:
                await self.message.edit(
                    content=(
                        f"⌨️ **Type Race — ⏰ Time's Up!**\n"
                        f"*The 60-second window has closed. Late submissions will be rejected.*\n\n"
                        f">>> ~~{self.sentence}~~"
                    ),
                )
            except Exception:
                pass

    async def on_timeout(self) -> None:
        # Fires after 120s if the user never clicked the button
        if self.message:
            for item in self.children:
                item.disabled = True
            try:
                await self.message.edit(
                    content=(
                        f"⌨️ **Type Race — Attempt Expired**\n"
                        f"*This attempt window has closed. Run `/type_race` again.*"
                    ),
                    view=self,
                )
            except Exception:
                pass
