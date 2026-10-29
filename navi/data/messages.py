# navi/data/messages.py - canned bot messages (moved from prompts.py, wording unchanged)

from __future__ import annotations

FALLBACK_MESSAGES: list[str] = [
    "Something went wrong on my end — API or connection issue. Try again in a moment.",
    "The cosmos is currently offline for maintenance. Try again later.",
    "My connection to the stars is currently showing a 404. Give me a minute.",
    "Even oracles need a reboot. API is down, try again shortly.",
    "Network shokam. The universe isn't responding right now.",
]


WELCOME_MESSAGES: list[str] = [
    "Hey {user}, you made it. Sit down, don't break anything.",
    "{user} has joined. Good — we were one person short of a proper argument.",
    "Oh look, {user} showed up. Welcome aboard, try to keep up.",
    "{user} just walked in. Server capacity: questionable. Vibes: pending.",
    "Welcome {user}. The server was fine before you arrived. Let's see if it stays that way.",
    "Hey {user}! You found us. Points for persistence, at least.",
    "{user} has entered. The rest of us have been here longer and learned nothing useful.",
    "Look who decided to show up. Welcome to the chaos, {user}.",
    "Door's open, {user}. Wipe your feet and find a seat.",
]


# Moda introduction — always appended to the welcome message for verified members
MODA_INTROS: list[str] = [
    "If you have questions, ask Moda — assuming he's not currently distracted by a fresh batch of Kuzhalappam.",
    "Moda is the moderator here. You can usually bribe him with a packet of crispy Kuzhalappam if you break a minor rule.",
    "Got questions? Moda's the boss. He's probably out hunting for Kuzhalappam right now, but leave a message.",
    "Moda moderates this server. He takes the role very seriously, but he takes his daily Kuzhalappam intake even more seriously.",
    "Our moderator Moda will help you. Unless he's on a Kuzhalappam run, in which case you are entirely on your own.",
    "Ask Moda if you get lost. Just don't touch his Kuzhalappam stash, or you'll get banned.",
    "Moda runs this server. He's powered entirely by caffeine and an unhealthy amount of Kuzhalappam.",
]


# Welcome messages for pending (unverified) members — no Moda intro
PENDING_WELCOME_MESSAGES: list[str] = [
    "Welcome to the waiting room, {user}. Verify your phone number to unlock the chat and join the chaos.",
    "Hey {user}! You made it to the door. Now verify your phone number so we can actually hear you.",
    "{user} is peering through the window. Complete your phone verification to step inside!",
    "Look who's here! {user}, you're officially in 'pending' purgatory. Verify that mobile number to break free.",
    "Welcome {user}! The bouncer needs to see your verified phone number before you can start typing.",
    "{user} has joined, but they're muted by the cosmos. Link a phone number to your account to speak!",
]


BOT_SELF_CURSE_REPLIES: list[str] = [
    "You think I can curse myself? Impressive logic. No.",
    "Self-cursing is not in my feature set. Try again.",
    "Cursing the bot doing the cursing? Bold strategy. Still no.",
    "That's not how this works. I don't curse myself.",
]


# When someone tries to feed another bot into the curse system
BOT_LOOP_CURSE_REPLIES: list[str] = [
    "That's a bot. I'm not starting a bot war.",
    "Bots don't need cosmic readings. Try a real person.",
    "You're asking me to curse a machine. No.",
    "Bot-on-bot cursing is not a thing I do. Nice try.",
    "I don't do bot-on-bot action. Pick a human target.",
]


BOT_SELF_COMPLIMENT_REPLIES: list[str] = [
    "Compliment myself? I already know I'm iconic.",
    "I don't need validation. I'm the bot. But appreciated.",
    "Peak perfection doesn't require compliments. Still, noted.",
    "I'm already at max hype. But the gesture is understood.",
]


BOT_LOOP_COMPLIMENT_REPLIES: list[str] = [
    "I'm not hyping up a bot. Pick a human.",
    "Bot-to-bot compliments? That's not a thing here.",
    "Bots don't need hype. Try a real person.",
    "I only compliment humans. Try again.",
]


SPAM_WRAPPERS: list[str] = [
    "Already told you — {prediction}",
    "Nothing changed in the last five minutes. {prediction}",
    "Same answer as before: {prediction}",
    "You already have your prediction. {prediction}",
    "The cosmos doesn't update that fast. {prediction}",
    "One prediction per customer. {prediction}",
    "Fate doesn't change on demand. {prediction}",
]


LEVEL_UP_MESSAGES: list[str] = [
    "{user} reached Level {level}! The server has taken note. Reluctantly.",
    "{user} is now Level {level}. Keep going.",
    "Level {level} for {user}! The cosmos updated your file.",
    "{user} hit Level {level}! Dedication noted. Barely, but noted.",
    "{user} — Level {level} achieved. The leaderboard shifts.",
    "Level {level}! {user} is not messing around.",
    "{user} unlocked Level {level}. Progress is progress.",
    "Level {level} for {user}. Even the server is mildly impressed.",
]
