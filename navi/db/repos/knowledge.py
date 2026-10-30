# navi/db/repos/knowledge.py - moved from schema.py (no behaviour change)
from __future__ import annotations

import logging
import random
import sqlite3

from navi.db.connection import _db_write

logger = logging.getLogger("navi.db.knowledge")


_LOCAL_KNOWLEDGE_DATA: list[tuple[str, str, str, str]] = [
    # (category, term, description, tags)
    # ---- LANDMARKS ----
    ("landmark", "Palayam / Connemara Market", "The bustling heart of the city for wholesale groceries, flowers, and chaos", "market,heritage,morning"),
    ("landmark", "Thampanoor", "The absolute epicenter of transit — central Railway Station and KSRTC bus stand", "transport,morning,junction"),
    ("landmark", "KD Puram", "Local abbreviation for Kesavadasapuram — a major traffic bottleneck and residential hub", "transport,evening,junction"),
    ("landmark", "Vellayambalam to Kowdiar Stretch", "The VIP road — wide, shaded by massive trees, lined with cafes and Rajapatham aesthetics", "posh,morning,culture"),
    ("landmark", "Chalai Market", "The labyrinthine heritage market near East Fort — from hardware to wholesale stationery", "market,heritage,nostalgia"),
    ("landmark", "Ponmudi", "The local hill station — standard weekend ride for youths and bikers", "weekend,nature,nostalgia"),
    ("landmark", "Sreekaryam / Pongumoodu", "Gateways to the tech-corridor — Technopark and Kazhakkoottam", "IT-crowd,weekday,morning"),
    ("landmark", "Museum Campus", "Napier Museum, Zoo, and Kanakakkunnu Palace — ultimate morning-walk and family hangout spot", "morning,heritage,family"),
    ("landmark", "Technopark", "Kerala's largest IT park — the realm of the IT Ambitions crowd", "IT-crowd,weekday,morning"),
    ("landmark", "East Fort", "Historical heart of the city near Padmanabhaswamy Temple — always busy", "heritage,morning,market"),
    ("landmark", "Vazhuthacaud", "The coaching centre universe — students everywhere with heavy bags", "students,morning,weekday"),
    ("landmark", "Jagathy", "Residential locality with a distinct old-city character", "nostalgia,morning"),
    ("landmark", "Sasthamangalam", "Quiet, leafy residential area — the old-money neighbourhood", "posh,morning"),
    ("landmark", "Pettah", "Junction area connecting Thampanoor to the old city — chaotic and busy", "transport,morning,junction"),
    ("landmark", "Varkala Cliff", "The Bali of TVM — laid-back cliffside vibes and backpacker energy", "beach,relaxed,weekend"),
    ("landmark", "Kanakakkunnu Palace", "Evening dates, cultural exhibitions, and open-air events in a colonial setting", "evening,posh,culture"),
    ("landmark", "Vizhinjam Port", "Massive cranes and non-stop development talk — the city's infrastructure pride", "infrastructure,modern,weekend"),
    ("landmark", "Akkulam Tourist Village", "Weekend picnic nostalgia — paddle boats and school-trip memories", "weekend,nostalgia,family"),
    ("landmark", "Technopark Phase 3", "The Ganga and Yamuna buildings — IT crowd gossip central", "IT-crowd,morning,weekday"),
    ("landmark", "Beemapally", "Vibrant market quarter with deep spiritual energy and Uroos festival fame", "market,spiritual,weekend"),
    ("landmark", "Vellayambalam Square", "The neon-lit city heart — always busy, never boring", "evening,junction"),
    ("landmark", "Shankumugham Beach", "Sunset rounds and the iconic giant mermaid statue by the sea", "evening,beach,sunset"),
    ("landmark", "Manaveeyam Veedhi", "The intellectual and cultural street — bookshops, debates, street art", "culture,arts,evening"),
    ("landmark", "Putharikandam Maidanam", "Political rallies and massive city exhibitions — Trivandrum's public square", "politics,events,morning"),
    ("landmark", "Kowdiar Avenue", "Posh road where the Rajahs live — broad, quiet, and dripping with old wealth", "posh,morning"),
    ("landmark", "Padmanabhaswamy Temple", "The world's richest temple — Vault B rumors never end", "spiritual,history,morning"),
    ("landmark", "Priyadarshini Planetarium", "School trip nostalgia — where every Trivandrum child learned about space", "nostalgia,family,morning"),
    ("landmark", "Napier Museum", "Morning walkers' paradise — heritage building, peacocks, and bureaucrats jogging", "morning,heritage"),
    ("landmark", "Lulu Mall TVM", "The new weekend traffic nightmare — shopping, food court, and parking grief", "weekend,shopping"),
    ("landmark", "Aruvikkara Dam", "Quick getaway for fresh water, peace, and picnics outside the city", "weekend,nature"),
    ("landmark", "Neyyar Dam", "Scenic spot with the lion safari — proper family outing material", "weekend,nature,family"),
    ("landmark", "Ponmudi Hill Station", "Mist-covered hairpin turns and cool air — the classic TVM escape", "weekend,nature,nostalgia"),
    ("landmark", "Agasthyarkoodam", "The ultimate trekking goal for serious hikers — breathtaking summit views", "nature,adventure,weekend"),
    # ---- FOOD ----
    ("food", "Boli and Paal Payasam", "The undisputed king of Trivandrum Sadya — sweet crepe mashed into warm milk payasam", "feast,traditional"),
    ("food", "Kethel's Chicken (Rahmaniya)", "Legendary roadside eatery — signature spicy chicken that draws queues", "street-food,spicy,nostalgia"),
    ("food", "Zam Zam (Palayam)", "Pioneer of Al Faham and Shawarma in the city — a cultural institution for youth", "street-food,evening,nostalgia"),
    ("food", "Indian Coffee House (Thampanoor)", "Iconic spiraling red-brick building — beetroot cutlets and uniformed waiters", "nostalgia,snack,morning"),
    ("food", "Sree Muruka Cafe (SMS)", "Famous for the classic Kerala combo: Pazham Pori and Beef Roast", "snack,morning,nostalgia"),
    ("food", "Maha Boly", "The dedicated shop for buying Boli in bulk — every TVM event needs this place", "snack,sweet,nostalgia"),
    ("food", "Rasavadai", "Popular evening snack heavily influenced by Tamil cuisine — spicy and addictive", "snack,spicy,evening"),
    ("food", "Evening chaya from thattukada", "Street tea at a local stall — mandatory daily ritual for every true Trivandrumite", "evening,social,nostalgia"),
    ("food", "Kizhi Parotta", "Steamed in banana leaf and soaked in rich gravy — dinner perfection", "dinner,rich"),
    ("food", "Pazham Pori and Beef Roast", "The Kochi-origin combo that Trivandrum has fully and proudly adopted", "snack,evening"),
    ("food", "Pazhamkanji", "Fermented rice served in earthen pots with fresh fish fry — morning soul food", "morning,traditional"),
    ("food", "Nadan Pothu Roast", "Spicy beef roast that pairs with absolutely anything on the menu", "dinner,spicy"),
    ("food", "Kappa and Meen Mulakittathu", "Spicy fish curry and mashed cassava — the classic Kerala lunch combo", "lunch,traditional"),
    ("food", "Sharjah Shake", "The quintessential Kerala milkshake — thick, sweet, and nostalgic", "evening,dessert,nostalgia"),
    ("food", "Unnakkaya", "Sweet banana snack stuffed with coconut — traditional teatime treat", "snack,sweet,traditional"),
    ("food", "Thattukada Omelette", "Street-style omelette heavy on onions and green chilies — late-night staple", "street-food,evening"),
    ("food", "Kulukki Sarbath", "Shaken lemonade with basil seeds — the summer street drink of choice", "drink,summer,evening"),
    ("food", "Fish Peera", "Small fish cooked with grated coconut — humble and delicious traditional dish", "lunch,traditional"),
    # ---- CULTURE ----
    ("culture", "IFFK (International Film Festival of Kerala)", "Every December the city turns into a cinephile paradise — delegates with Kalamandalam bags everywhere", "culture,arts,evening"),
    ("culture", "Attukal Pongala", "World's largest gathering of women — entire city shuts down, every street becomes an open-air kitchen", "festival,spiritual,morning"),
    ("culture", "Techie vs Core City Divide", "Gentle cultural gap between IT crowd in Technopark and traditional inner-city residents of Kowdiar/Sasthamangalam", "IT-crowd,culture,weekday"),
    ("culture", "Ramachandran Textiles East Fort", "The absolute juggernaut of local shopping — if a local buys budget clothes, they are here", "market,nostalgia,morning"),
    ("culture", "Evening Chaya at Thattukada", "Trivandrum operates on a slower bureaucratic clock — evening tea with politics and cinema discussion is sacred", "evening,social,nostalgia"),
    ("culture", "Tagore Theatre Events", "Heart of the city's arts scene — theatre, music, and cultural programmes", "culture,arts,evening"),
    ("culture", "Napier Museum Morning Walk", "High-profile bureaucrats and retirees jogging between heritage buildings — a daily Trivandrum ritual", "morning,posh,heritage"),
    ("culture", "KSRTC Minnal Bus", "Highway terror incarnate — the fear of God on every inter-city route", "transport,nostalgia"),
    ("culture", "Technopark Swipe Cards", "The mark of the IT Ambitions crowd — the badge that separates tech from the rest", "IT-crowd,weekday"),
    ("culture", "Beemapally Uroos", "Massive annual spiritual and market event — draws the whole city to the southern quarter", "festival,spiritual,weekend"),
    ("culture", "Onam Lighting", "Vellayambalam to East Fort glowing in festive lights — the city at its most beautiful", "festival,evening"),
    ("culture", "Chaver Bus Drivers", "The legendary private bus drivers who treat every route as a Formula 1 race", "transport,nostalgia"),
    ("culture", "Thampanoor Rush Hour", "The ultimate test of patience — every mode of transport colliding at once", "transport,morning"),
    ("culture", "Vazhuthacaud Coaching Vibe", "Thousands of students cramming for exams — the coaching centre capital of TVM", "students,morning,weekday"),
    ("culture", "Rainy Day Chaya", "The collective Malayali monsoon obsession — tea tastes better when it rains, fact", "monsoon,evening,social"),
    ("culture", "Technopark Friday Home-Runs", "Mass exodus of IT employees every Friday evening — entire Kazhakkoottam empties out", "IT-crowd,evening"),
    ("culture", "Padmanabhaswamy Treasure Mystery", "Endless speculation about Vault B — the rumour that never dies in TVM", "history,mystery"),
    ("culture", "Chalai Market Squeeze", "The beautiful chaos of buying everything from a pin to an elephant in one labyrinthine market", "market,heritage,nostalgia"),
    ("culture", "KD Puram Traffic Jam", "The legendary jam that defines TVM evenings — nothing moves, everyone accepts it", "transport,evening"),
    # ---- EXPRESSIONS ----
    ("expression", "Appi", "Term of endearment for a baby or child — true locals know its innocent Trivandrum roots", "language,local"),
    ("expression", "Kili poyi", "Literally the bird flew away — used when someone is utterly confused or shocked", "language,local"),
    ("expression", "Oola", "Useless, pathetic, or of very poor quality — the ultimate dismissal", "language,local"),
    ("expression", "Shokam", "A sad, boring, or pathetic situation — Trivandrum's favourite word for disappointment", "language,local"),
    ("expression", "Chumma", "Simply or for no reason — a universal Malayali word heavily overused in TVM", "language,local"),
    ("expression", "Eda / Edi", "Informal hey used constantly among friends — gender variant matters in Trivandrum", "language,local"),
    ("expression", "Thirontharam", "How locals casually pronounce Thiruvananthapuram at speed — the true insider marker", "language,local"),
    ("expression", "Vayye?", "Are you not well? or Can't you do it? — frequently sarcastic", "language,local"),
    ("expression", "Pillacha", "Respectful but familiar address for an older man — shopkeeper or neighbour energy", "language,local"),
    ("expression", "Kidilam / Kidu", "Absolutely awesome or fantastic — the highest praise in the TVM lexicon", "language,local"),
    ("expression", "Vishayam", "Matter, issue, situation — as in what is this vishayam?", "language,local"),
    ("expression", "Lokam", "World or scene — IT lokam means the tech crowd and their universe", "language,local"),
    ("expression", "Chetta", "Elder brother; respectful address for older men you don't know well", "language,local"),
    ("expression", "Mone", "Son; affectionate address that can also sound patronising depending on tone", "language,local"),
    ("expression", "IT Ambitions", "The Technopark crowd who believe they have escaped Thirontharam — they haven't", "language,local,IT-crowd"),
]


def seed_local_knowledge(conn: sqlite3.Connection, force: bool = False) -> None:
    """Populate the knowledge table from curated data. Skips if already seeded unless force=True."""
    count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    if count > 0 and not force:
        logger.info("knowledge already seeded (%d rows) — skipping.", count)
        return

    def _write() -> None:
        conn.execute("DELETE FROM knowledge")
        conn.executemany(
            """
            INSERT OR IGNORE INTO knowledge (category, term, description, tags, status)
            VALUES (?, ?, ?, ?, 'active')
            """,
            [(cat, term, desc, tags) for cat, term, desc, tags in _LOCAL_KNOWLEDGE_DATA],
        )
        conn.commit()

    _db_write(_write)
    logger.info("Seeded knowledge with %d entries.", len(_LOCAL_KNOWLEDGE_DATA))


def get_random_knowledge_terms(conn: sqlite3.Connection, num_categories: int = 3) -> list[dict]:
    """Return one random term per randomly-selected category for Navi Challenge."""
    cats = conn.execute("SELECT DISTINCT category FROM knowledge WHERE status = 'active'").fetchall()
    cat_list = [r[0] for r in cats]
    if not cat_list:
        return []
    selected_cats = random.sample(cat_list, min(num_categories, len(cat_list)))
    results = []
    for cat in selected_cats:
        rows = conn.execute(
            "SELECT term, description FROM knowledge WHERE category = ? AND status = 'active' ORDER BY RANDOM() LIMIT 1",
            [cat],
        ).fetchall()
        if rows:
            results.append({"category": cat, "term": rows[0][0], "description": rows[0][1]})
    return results
