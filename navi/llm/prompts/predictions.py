# navi/llm/prompts/predictions.py - moved from prompts.py (wording unchanged)

from __future__ import annotations


def get_navi_prompt(
    name: str,
    rashi: str | None = None,
    past_predictions: list[str] | None = None,
) -> str:
    """Build the user-facing Navi prediction prompt."""
    import random as _random

    rashi_line = f"Their star sign is {rashi}." if rashi else ""

    memory_aside = ""
    avoid_list = ""

    if past_predictions:
        avoid_list = "DO NOT repeat or use topics from these past predictions:\n"
        for p in past_predictions:
            avoid_list += f"- {p}\n"

        if _random.random() < 0.40:
            past_item = _random.choice(past_predictions)
            memory_aside = (
                f"You may briefly hint (in at most 5 words) that a previous warning came true — "
                f"e.g. the last one was: \"{past_item[:60]}\". "
                f"This is optional flavour only, not the main prediction."
            )

    return f"""Give a short, dry cosmic warning / Navi reading for {name}. {rashi_line}
{memory_aside}
{avoid_list}

Requirements:
- Vary the opener: "Hey {name}," / "Oh {name}," / "{name}," / "Right, {name} —"
- Ground it in ONE specific, mundane Trivandrum situation. Pick from a wide range — do not default to traffic or power cuts. Examples of what to draw from: a delayed KSRTC bus, a sold-out parotta at the thattukada, mobile network dropping mid-call, an ATM out of cash, a medical shop running out of stock, a bakery line stretching out the door, a sudden downpour when you left the umbrella at home, a temple crowd blocking the road, an auto driver haggling 3x the meter, a courier that sat in Kazhakkoottam for a week, a chai going cold, a WhatsApp forward predicting doom, overpriced coconut water near the beach, a fan cutting out on a hot afternoon, a sudden queue at the ration shop, a dog blocking the gate, a surprise government exam holiday that ruins your plans, bad signal on the 3rd floor of your building, running out of gas right before cooking, or a neighbour blasting a film song at 7am.
- Dry and slightly inevitable-sounding, not dramatic. Think deadpan oracle, not fairground mystic.
- In English only. 1-2 fully complete sentences. Maximum 25 words.
- Do NOT use newlines, lists, or colons.
- End with proper punctuation."""
