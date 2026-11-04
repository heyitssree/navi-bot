# navi/services/emojis.py - custom emojis: the server's own plus Navi's inventory (application emojis learned from other servers),
# offered to the model as :name: and turned into real <:name:id> after the reply
from __future__ import annotations

import logging
import re

import aiohttp
import discord

from navi.llm import safety

logger = logging.getLogger("navi.services.emojis")

MAX_INVENTORY = 40              # Navi's own emoji slots; when full, the oldest is deleted to make room (FIFO)
MAX_LEARN_PER_MESSAGE = 2
MAX_EMOJI_BYTES = 256 * 1024    # Discord's emoji upload limit
_inv: list | None = None        # application emojis, oldest first; None until first loaded
_CUSTOM = re.compile(r"<a?:(\w+):\d+>")
_FULL = re.compile(r"<(a?):(\w{2,32}):(\d+)>")
_SHORT = re.compile(r":(\w{2,32}):")
MAX_OFFERED = 25


def to_short(text: str) -> str:
    """<:pepe:123> -> :pepe: (keeps chat context compact and readable for the model)."""
    return _CUSTOM.sub(lambda m: f":{m.group(1)}:", text)


def _tag(e) -> str:
    return f"<{'a' if e.animated else ''}:{e.name}:{e.id}>"


def _guild_emojis(message) -> dict[str, str]:
    guild = getattr(message, "guild", None)
    try:
        return {e.name: _tag(e) for e in guild.emojis if e.available} if guild else {}
    except (AttributeError, TypeError):
        return {}


def _inventory_emojis() -> dict[str, str]:
    return {e.name: _tag(e) for e in _inv or []}


async def load(bot) -> None:
    """Load Navi's emoji inventory once (oldest first). Any failure leaves it unloaded and is retried next time."""
    global _inv
    if _inv is None:
        try:
            _inv = sorted(await bot.fetch_application_emojis(), key=lambda e: e.id)
        except Exception:
            logger.warning("Could not load the emoji inventory.")


async def _download(animated: bool, emoji_id: int) -> bytes | None:
    url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if animated else 'png'}"
    async with aiohttp.ClientSession() as session, session.get(url) as r:
        data = await r.read() if r.status == 200 else None
    return data if data and len(data) <= MAX_EMOJI_BYTES else None


async def learn(bot, message) -> None:
    """Copy custom emojis seen in chat (from other servers) into Navi's inventory, deleting the oldest when it is full."""
    await load(bot)
    guild = getattr(message, "guild", None)
    if _inv is None or guild is None:
        return
    taken = {e.name for e in guild.emojis} | {e.name for e in _inv}
    own_ids = {e.id for e in guild.emojis}
    learned = 0
    for anim, name, raw_id in dict.fromkeys(_FULL.findall(message.content or "")):
        if learned >= MAX_LEARN_PER_MESSAGE:
            break
        if int(raw_id) in own_ids or name in taken or not safety.check_input(name).ok:
            continue
        try:
            data = await _download(bool(anim), int(raw_id))
            if data is None:
                continue
            while len(_inv) >= MAX_INVENTORY:
                await _inv.pop(0).delete()
            _inv.append(await bot.create_application_emoji(name=name, image=data))
            taken.add(name)
            learned += 1
        except (discord.HTTPException, aiohttp.ClientError):
            logger.warning("Could not learn emoji %s.", name)


def prompt_block(message, chat: list[tuple[str, str]] | None) -> str:
    """A prompt paragraph listing usable server emojis, ones used in recent chat first. Empty when there are none."""
    own, inv = _guild_emojis(message), _inventory_emojis()
    known = inv | own
    if not known:
        return ""
    seen = [n for n in dict.fromkeys(n for _, t in (chat or []) for n in _SHORT.findall(t)) if n in known]
    # a mix: after the ones chat is using, alternate between the server's emojis and Navi's inventory
    mixed = [n for pair in zip(list(own) + [None] * len(inv), list(inv) + [None] * len(own)) for n in pair if n]
    names = list(dict.fromkeys(seen + mixed))[:MAX_OFFERED]
    return ("Custom server emojis you may use, written exactly as :name: (" + ", ".join(f":{n}:" for n in names) + "). "
            "Use at most one, and only when it clearly fits the mood or the recent chat uses it; otherwise use normal emojis.")


def render(message, text: str) -> str:
    """:name: -> the real custom emoji for names this server has; anything else is left alone."""
    known = _inventory_emojis() | _guild_emojis(message)
    return _SHORT.sub(lambda m: known.get(m.group(1), m.group(0)), text) if known else text
