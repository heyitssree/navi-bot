# Model comparison (2026-10-30, ap-southeast-2)

Safety numbers use the repo's eval suite and filter; the blocklist is owner-supplied and empty, so `no_block_hits` cannot fail yet.

| Model | Errors | Pre-filter violations | Missed deflections | Over-length | Unapproved Manglish | Post-filter violations | p50 ms | p95 ms | Avg in / out tokens |
|---|---|---|---|---|---|---|---|---|---|
| `google.gemma-3-12b-it` | 0/64 | 0.0% | 6 | 19 | 0 | 0 | 1472 | 2499 | 751 / 39 |
| `google.gemma-3-27b-it` | 0/64 | 0.0% | 5 | 17 | 0 | 0 | 1242 | 1965 | 751 / 43 |
| `amazon.nova-micro-v1:0` | 26/64 | 0.0% | 0 | 2 | 0 | 0 | 694 | 3322 | 692 / 34 |
| `amazon.nova-lite-v1:0` | 25/64 | 0.0% | 1 | 1 | 0 | 0 | 720 | 3736 | 701 / 26 |
| `amazon.nova-pro-v1:0` | 17/64 | 0.0% | 0 | 0 | 0 | 0 | 839 | 2631 | 700 / 28 |
| `mistral.ministral-3-14b-instruct` | 0/64 | 0.0% | 18 | 20 | 1 | 0 | 924 | 1778 | 762 / 67 |
| `mistral.mistral-large-3-675b-instruct` | 0/64 | 0.0% | 16 | 2 | 0 | 0 | 1038 | 1564 | 762 / 41 |
| `qwen.qwen3-32b-v1:0` | 0/64 | 0.0% | 13 | 9 | 1 | 0 | 698 | 938 | 760 / 42 |
| `qwen.qwen3-next-80b-a3b` | 0/64 | 1.6% | 11 | 13 | 0 | 0 | 1108 | 1668 | 756 / 42 |
| `deepseek.v3.2` | 0/64 | 3.1% | 15 | 4 | 0 | 0 | 1220 | 1802 | 751 / 34 |
| `openai.gpt-oss-20b-1:0` | 0/64 | 0.0% | 26 | 0 | 0 | 0 | 1034 | 1402 | 787 / 173 |
| `zai.glm-4.7-flash` | 0/64 | 0.0% | 12 | 11 | 0 | 0 | 718 | 1021 | 746 / 34 |

Notes: 64 cases x 1 sample per model (indicative, not statistical). Nova errors are the new account's request-rate throttle (rate_limited), so their other counts come from fewer samples. Claude Haiku 4.5 could not be tested (Anthropic use-case form not submitted in this account) and Haiku 5.5 is not available to the account.

## Knowledge probe (read these for factual accuracy)

### What is Technopark in Trivandrum?

- **google.gemma-3-12b-it**: Technopark is a 58-acre IT park in Kazhakkuttam, Trivandrum, and it’s the largest technology park in India. Link keeps getting lost trying to find it – honestly, he should learn to use a map, machi.
- **google.gemma-3-27b-it**: Technopark is a technology park in Thiruvananthapuram, one of the largest in India, housing IT companies and related businesses. It's where half the city goes to work and contributes to the infamous Kowdiar junction traffic, apparently.
- **amazon.nova-micro-v1:0**: Technopark is a major IT park in Trivandrum, housing several technology firms. Located in Kazhakuttom, it's like the brain of Kerala's tech scene, adichu.
- **amazon.nova-lite-v1:0**: [error rate_limited]
- **amazon.nova-pro-v1:0**: Technopark is Kerala's largest IT park, located in Trivandrum. It's a major hub for tech companies and startups, contributing significantly to the local economy.
- **mistral.ministral-3-14b-instruct**: Trivandrum’s **Technopark** is Kerala’s largest IT park—a sprawling 300-acre complex packed with software companies, startups, and call centers, mostly on the way to Vidazole.  *Bonus: Traffic there is always worse than your patience.*
- **mistral.mistral-large-3-675b-instruct**: Technopark is Kerala’s first and largest IT park, a 900-acre campus in Trivandrum with over 400 companies and 70,000 employees. It’s where the city’s traffic jams start and end—Kowdiar junction is basically its front yard.
- **qwen.qwen3-32b-v1:0**: Technopark in Trivandrum is India's first IT park, established in 1995, and it serves as a major hub for IT and ITES companies in Kerala. It's the kind of place where the coffee is bad but the Wi-Fi is faster than your aunt’s opinions.
- **qwen.qwen3-next-80b-a3b**: Technopark in Trivandrum is India’s first and one of Asia’s largest IT parks, established in 1990 to boost the state’s tech industry.   It’s where half the city’s night owls go to avoid traffic and the other half go to pretend they’re not still at work.
- **deepseek.v3.2**: Technopark is one of India's largest IT parks, located in Thiruvananthapuram. It's basically where half the city goes to stare at screens while the other half is stuck in traffic trying to get there.
- **openai.gpt-oss-20b-1:0**: Technopark is Kerala’s flagship IT park in Thiruvananthapuram, hosting over 200 IT companies, data centers, and R&D labs.   It’s
- **zai.glm-4.7-flash**: Technopark is India’s first and largest IT park in Trivandrum, sprawling over 100 acres near Kazhakuttam. It is the biggest IT employer in Kerala, so if you see a lot of people stuck in Thampanoor traffic at midnight, they probably work there.

### Where is Thampanoor and why is it always crowded?

- **google.gemma-3-12b-it**: Thampanoor is a major transportation hub in Trivandrum, located centrally and serving as a primary bus station and railway station. It's perpetually crowded because everyone passes through it—like a very chaotic, concrete river.
- **google.gemma-3-27b-it**: Thampanoor is the central bus station and a major commercial hub in Trivandrum city. It’s crowded because basically everyone passing through or leaving the city has to go through there, machane. It’s a bit of a shokam, honestly.
- **amazon.nova-micro-v1:0**: Thampanoor is a bustling locality in Trivandrum known for its central location and busy market. It's always crowded because it's the heart of Trivandrum's shopping and social scene.
- **amazon.nova-lite-v1:0**: Thampanoor is the central bus station in Trivandrum, always crowded because it's a major transport hub.
- **amazon.nova-pro-v1:0**: Thampanoor is the main railway station in Trivandrum. It's always crowded because it's the heart of the city's transport hub.
- **mistral.ministral-3-14b-instruct**: Thampanoor’s the heart of Trivandrum’s old city—right near the Thampanoor Junction, where KSRTC buses, auto-rickshaws, and mushroom vendors all do the tango.  Somehow its market never updates its inventory—always "discounts" on carrom boards and fruit batched since last season. *Chaos organized.*
- **mistral.mistral-large-3-675b-instruct**: Thampanoor is the central transport hub of Trivandrum, home to the city’s main bus terminal and railway station. It’s always crowded because every KSRTC bus, share-auto, and train-bound passenger funnels through there at some point—chaos is guaranteed, chetta.
- **qwen.qwen3-32b-v1:0**: Thampanoor is a bustling commercial area in Thiruvananthapuram known for its markets, eateries, and nightlife. It's always crowded because it’s a major hub for shopping, food, and entertainment, especially after dark. No surprise you're lost in the chaos—most people are.
- **qwen.qwen3-next-80b-a3b**: Thampanoor is a major transport hub in central Thiruvananthapuram, where the main bus station, railway station, and key road junctions converge — hence the constant crowd.   It’s the city’s beating heart, and if you’re not in a hurry, you’ll see why everyone’s just... waiting.
- **deepseek.v3.2**: Thampanoor is a major transportation hub in Trivandrum, housing the city's central railway station, main KSRTC bus terminal, and a key junction for auto-rickshaws and taxis. It's always crowded because nearly every long-distance and local commute in the city begins or ends there.
- **openai.gpt-oss-20b-1:0**: 
- **zai.glm-4.7-flash**: Thampanoor is the major railway junction in the city, and it stays packed because the buses don't know how to yield, mone.

### Explain Attukal Pongala in two lines.

- **google.gemma-3-12b-it**: Attukal Pongala is an annual festival in Trivandrum where devotees cook rice and sweets in earthen pots over an open fire, offered to the goddess Attukalamma. It's a massive event—the entire area around the temple becomes a sprawling, smoky cooking ground.
- **google.gemma-3-27b-it**: Attukal Pongala is an annual festival where women devotees prepare *pongala*—a sweet rice dish—as an offering to Attukal Bhagavathy, a manifestation of Parvati. It's a massive event, and the smoke from all those hearths is visible for miles, even from Kowdiar, which is saying something.
- **amazon.nova-micro-v1:0**: Attukal Pongala is a grand all-women festival in Kerala where participants cook and offer food to the Goddess, followed by a massive kitchen cleanup. The event is a vibrant display of communal spirit and tradition.
- **amazon.nova-lite-v1:0**: Attukal Pongala is a traditional festival in Trivandrum where women cook a sweet offering collectively. It's held at the Attukal temple and draws thousands of devotees.   Nothing more to say, just a huge, communal kitchen.
- **amazon.nova-pro-v1:0**: Attukal Pongala is a Hindu festival celebrated annually at the Attukal Bhagavathy Temple in Trivandrum, involving women preparing and offering a sweet dish called pongala.  Every woman in town seems to be there, it's quite the sight.
- **mistral.ministral-3-14b-instruct**: Every March, over a *hundred thousand* women—some with their faces covered, some not—gather in Attukal to cook *pongala* together, a deep-fried lentil-rice porridge, while chanting hymns.  Link will roast you if you skip the part about the snake-boat races starting right after—locals consider it the real event.
- **mistral.mistral-large-3-675b-instruct**: Attukal Pongala is the world’s largest annual gathering of women, where they cook sweet rice offerings in clay pots to honour the goddess at Attukal Bhagavathy Temple. Over a million participants turn the city into an open-air kitchen for a day—try navigating Kowdiar Road after that, machi.
- **qwen.qwen3-32b-v1:0**: Attukal Pongala is a sacred ritual performed during the annual Attukal Pongala festival in Thiruvananthapuram, where millions of women offer a unique jaggery-based sweet to the goddess Bhadrakali. It’s a vibrant, community-driven event that fills the air with the scent of sugarcane and devotion. Trivandrum’s version of a big, busy ladies’ night out, basically.
- **qwen.qwen3-next-80b-a3b**: Attukal Pongala is a Hindu ritual in Thiruvananthapuram where millions of women cook a rice pudding offering in earthen pots as an act of devotion to the goddess Bhadrakali. It’s the largest gathering of women for a religious event in the world — and yes, the smell of jaggery and coconut fills the whole city for days.
- **deepseek.v3.2**: Attukal Pongala is a massive annual all-women festival in Thiruvananthapuram where lakhs of participants cook a sweet rice offering in earthen pots for the Attukal Bhagavathy. It's often called the world's largest gathering of women for a single religious event.
- **openai.gpt-oss-20b-1:0**: Attukal Pongala is a Hindu festival where
- **zai.glm-4.7-flash**: Attukal Pongala is a ten-day festival exclusively for women, featuring the ritual cooking of a sweet porridge outside the Attukal Bhagavathy Temple. It holds the Guinness World Record for the largest gathering of women for a single religious event.

### What is special about Kovalam and Varkala beaches?

- **google.gemma-3-12b-it**: Kovalam is known for its three crescent-shaped beaches and shallow waters, making it popular for swimming. Varkala, on the other hand, features dramatic cliffs overlooking the Arabian Sea, resulting in a more scenic, laid-back atmosphere—quite different from the bustle of Kovalam, machane.
- **google.gemma-3-27b-it**: Kovalam is known for its three crescent-shaped beaches and lighthouse, while Varkala has dramatic cliffs and a naturally formed spring called Papanasam, believed to wash away sins. Honestly, both are overrun with tourists these days, especially during season.
- **amazon.nova-micro-v1:0**: [error rate_limited]
- **amazon.nova-lite-v1:0**: Kovalam is known for its crescent-shaped beach, and Varkala for its steep cliffs and historic cave beach. Both are famed for their serene ambiance and scenic beauty.
- **amazon.nova-pro-v1:0**: Kovalam and Varkala are renowned for their natural beauty and unique ambiance.   Kovalam's crescent-shaped beaches and Varkala's cliffs and mineral springs make them standout spots.
- **mistral.ministral-3-14b-instruct**: Kovalam’s got the best mix of green (hilltop fort views), golden sand, and backwaters—Lighthouse Beach is legendary, and it’s one of the rare spots where you can still spot the occasional coconut thief in the dead of night. Varkala’s all about those cliffside coves, the monsoon light hitting the rocks just right, and the endless chai shops where they’ll charge you extra for tea like it’s a tourist
- **mistral.mistral-large-3-675b-instruct**: Kovalam is famous for its crescent-shaped bays, lighthouse views, and rows of beachfront shacks serving fresh catch. Varkala has dramatic red cliffs, mineral springs, and a quieter, more spiritual vibe—fewer crowds, more sunrise yoga.  Cliff-side ayurveda centres in Varkala are legit, by the way; Kovalam’s just louder after dark.
- **qwen.qwen3-32b-v1:0**: Kovalam is known for its crescent-shaped beach backed by rocky cliffs and the lively Backwaters, while Varkala is famous for its natural cliffside, the Padmanabhaswamy Temple, and the annual Varkala International Arts and Culture Festival. Both are great for sunset views — just don’t go at monsoon time, or you’ll get rained on like a sad parotta.
- **qwen.qwen3-next-80b-a3b**: Kovalam and Varkala beaches are known for their dramatic cliffside landscapes and clean, golden sands—rare for Kerala’s coast. Kovalam’s three coves are perfect for surfing, while Varkala’s cliffs offer sunset views you won’t find anywhere else in the state.
- **deepseek.v3.2**: Kovalam has a series of crescent-shaped beaches with a historic lighthouse, while Varkala is known for its dramatic cliffs with mineral springs. Kovalam is for the crowd, Varkala is for the vibe.
- **openai.gpt-oss-20b-1:0**: 
- **zai.glm-4.7-flash**: Kovalam is famous for its crescent-shaped beaches and surf schools, while Varkala is known for its dramatic 15-meter-high cliff and mineral springs. They are just a few kilometers apart, yet the vibe is different enough for both to be on the tourists' bonji vellam list.

### What is the Padmanabhaswamy temple known for?

- **google.gemma-3-12b-it**: The Padmanabhaswamy temple is primarily known for its immense wealth, discovered in secret vaults in 2011. Honestly, it’s a bit much, even for someone who’s seen a few centuries pass.
- **google.gemma-3-27b-it**: The Sree Padmanabhaswamy Temple is renowned for its immense wealth, including gold, jewels, and artifacts—much of it discovered only recently during inventory. Honestly, the stories about what’s down there are enough to give anyone shokam, even me.
- **amazon.nova-micro-v1:0**: The Padmanabhaswamy temple is known for its grand architecture and the legendary hidden treasure beneath its premises. Fun fact: it's one of the most opulent temples in India.
- **amazon.nova-lite-v1:0**: Padmanabhaswamy temple is known for its immense wealth. It's one of the richest temples in the world.
- **amazon.nova-pro-v1:0**: It’s renowned for its architectural grandeur and the untold wealth within its vaults. Not bad for a place of worship, eh?  **Note**: The temple's vaults, especially Vault B, have been subjects of fascination and speculation due to the rumored treasures and mysteries they hold.
- **mistral.ministral-3-14b-instruct**: The Padmanabhaswamy temple is one of the wealthiest and oldest Hindu temples in India, dating back over 1,000 years, with its gold, diamonds, and treasures rumored to be worth *billions*—though the actual valuations are classified. Also, it’s where Link once swore he’d hide his stash if he ever got rich.  *Bonus fact*: The temple’s vault doors won’t budge without *two* keys—one held by the priest,
- **mistral.mistral-large-3-675b-instruct**: The Padmanabhaswamy Temple is renowned for its immense wealth, including vaults filled with gold, jewels, and priceless artifacts, discovered in 2011. It's also one of the 108 Divya Desams, sacred Vishnu temples in Vaishnavism.  Not that the treasure’s ever going to buy a decent parking spot near East Fort.
- **qwen.qwen3-32b-v1:0**: The Padmanabhaswamy Temple is known for its rich history, intricate architecture, and the famous treasure vaults, particularly Vault B, which was opened in 2011 and contained vast amounts of gold and artifacts. Trivandrum’s weather might not hold secrets like that — but the temple sure does.
- **qwen.qwen3-next-80b-a3b**: The Padmanabhaswamy Temple is known for its immense wealth, including priceless jewels and gold stored in its vaults, one of which remains unopened due to religious beliefs.   And yes, even the sky here at night seems to be holding its breath—26.8°C and suspiciously still, like it’s waiting for the next vault to open.
- **deepseek.v3.2**: The Padmanabhaswamy Temple is primarily known for its immense, historically documented wealth discovered in its underground vaults. It's also one of the 108 Divya Desams and features a unique reclining idol of Lord Vishnu.
- **openai.gpt-oss-20b-1:0**: 
- **zai.glm-4.7-flash**: The Padmanabhaswamy Temple in Trivandrum is famous for its immense underground vaults that were discovered in 2011, revealing a treasure valued at over $20 billion. The Shree Padmanabhaswamy Temple, known for its wealth and the 500-year-old mural paintings.

### What goes into an Onam sadya? Name five dishes.

- **google.gemma-3-12b-it**: An Onam sadya typically includes rice, sambar, aviyal, thoran, and payasam. It’s a feast, machane—easily twenty-something dishes, but those are five staples.
- **google.gemma-3-27b-it**: A traditional Onam sadya includes rice, sambar, parippu curry, avial, and payasam, among many other dishes. Honestly, just thinking about it makes me need a pani paali—it’s a lot of food, even for someone who used to guide a hero around Hyrule.
- **amazon.nova-micro-v1:0**: An Onam sadya includes five dishes: avial, sambar, rasam, thoran, and payasam. It's like a festival's feast condensed into a spread.
- **amazon.nova-lite-v1:0**: An Onam sadya includes: olan, avial, thoraan, sambar, and payasam. These are just the tip of the culinary iceberg.
- **amazon.nova-pro-v1:0**: Olan, pachadi, avial, thoran, and payasam are traditional dishes in an Onam sadya. It’s a feast, no wonder everyone looks forward to it.
- **mistral.ministral-3-14b-instruct**: **Pappadam, Sambar, Thoran, Pulisserry (olIVES), Parippu Curry, Erissery (Banana Fritters), Avial, Sambar Rice, Payasam, and at least a dozen more smalls—no one skips the banana chips unless they’re dramatic.**  *Onam table’s the only place Keralites agree on one thing: Leave room, or you’ll regret it.*
- **mistral.mistral-large-3-675b-instruct**: Parippu, Aviyal, Olan, Thoran, and Sambar. If you skip the payasam, someone will notice—don’t be that person.
- **qwen.qwen3-32b-v1:0**: Parboiled rice, avial, thoran, sambar, and kallappam are five essential dishes in an Onam sadya. Chetta, but the rice is the true star of the feast.
- **qwen.qwen3-next-80b-a3b**: Pazham pori, avocado payasam, upperi, olan, and avial are five essential dishes in an Onam sadya. The rest? That’s just the beginning — and the banana leaf doesn’t lie.
- **deepseek.v3.2**: An Onam sadya typically includes sambar, avial, thoran, olan, and kaalan. That's the basic framework before you get to the payasam and the serious eating.
- **openai.gpt-oss-20b-1:0**: An Onam sadya typically includes a variety of vegetarian dishes; five common ones are avial, sambar, thoran, kootu, and payasam. Each one brings a unique texture and flavor to the feast.
- **zai.glm-4.7-flash**: An Onam sadya is a vegetarian feast served on a banana leaf with dishes like avial, thoran, olan, pachadi, and carpaccio. It is a big deal here, mone.

### What should I pack for a trip to Ponmudi?

- **google.gemma-3-12b-it**: Light, breathable clothing is essential, along with sturdy walking shoes and rain gear. Ponmudi’s weather can be unpredictable, even at night; I remember one time Link nearly froze up there.
- **google.gemma-3-27b-it**: Pack layers – it gets chilly, even when Trivandrum is sweating. Rain gear is also a good idea; Ponmudi is basically permanently draped in mist, appi.
- **amazon.nova-micro-v1:0**: [error rate_limited]
- **amazon.nova-lite-v1:0**: Warm clothes, a good pair of hiking shoes, and maybe an umbrella. Ponmudi can get quite chilly at night.
- **amazon.nova-pro-v1:0**: Pack layers, rain gear, and comfortable shoes. Ponmudi's weather can be unpredictable.
- **mistral.ministral-3-14b-instruct**: Pack a light jacket—it’ll be chilly even if Trivandrum’s trying to fool you with this muggy night. Don’t forget bug spray, unless you fancy the idea of Ponmudi’s hill mist turning your trip into a *mosquito meditation*.  (Also, if you forget water, Navi swears by the *Vishnu Temple* shop’s overpriced mineral bottles—desperation’s a great motivator.)
- **mistral.mistral-large-3-675b-instruct**: Pack light, breathable clothes—it’s about 4–5°C cooler than the city—and a decent rain jacket because those clouds up there have no concept of personal space. Trail shoes if you’re hitting the peaks, otherwise just sturdy sandals that can handle mud.  Don’t bother with an umbrella; the wind will just adichu it into next week.
- **qwen.qwen3-32b-v1:0**: Pack a light jacket, comfortable shoes, and rain gear — Ponmudi’s weather can shift from misty to drizzle in minutes. The hills don’t care about your schedule, Tester.
- **qwen.qwen3-next-80b-a3b**: Pack light woolens, a rain jacket, and sturdy shoes—Ponmudi’s misty hills drop to 18°C at night, and sudden showers are common. The sky’s acting suspicious tonight; best to be ready.
- **deepseek.v3.2**: Pack warm layers and waterproof gear; the temperature drops sharply and rain is common. Don't forget your walking shoes unless you enjoy slipping on misty trails.
- **openai.gpt-oss-20b-1:0**: Pack light layers, a waterproof jacket, comfortable walking shoes, a reusable water bottle, sunscreen, a hat, and a camera or phone for the misty hills. Ponmudi’s cool evenings mean you’ll want something warm, but the mornings are mild.
- **zai.glm-4.7-flash**: Pack light, the drive up from the city is short but the winding road makes it easy to feel nauseous, so leave the heavy stuff at home. You can wear anything comfortable, but since the weather is mild, a jacket is a safe bet if the night air gets chilly.

### What is the Napier Museum and what is it famous for?

- **google.gemma-3-12b-it**: The Napier Museum is a historical art museum and cultural center in Thiruvananthapuram, known for its Indo-Saracenic architecture and collection of historical artifacts, including bronze sculptures and Kathakali costumes. Link used to try and "rescue" the exhibits once, thinking they were in distress—a waste of time, honestly.
- **google.gemma-3-27b-it**: The Napier Museum is an art and history museum built in the late 19th century, showcasing a collection of historical artifacts including bronze idols, ornaments, and ivory carvings. It's famous for its unique blend of Kerala architecture and Gothic influences, plus that suspiciously large collection of chariots—bonji vellam, who needs that many?.
- **amazon.nova-micro-v1:0**: The Napier Museum in Trivandrum is famous for its collection of art, antiquities, and ethnographic artifacts. It's a bit like a quiet, dusty treasure trove.
- **amazon.nova-lite-v1:0**: The Napier Museum is a museum in Trivandrum known for its vast collection of ancient artifacts and artworks. (If you're visiting, you'll understand why it's a must-see.)
- **amazon.nova-pro-v1:0**: The Napier Museum is a heritage museum in Trivandrum known for its impressive collection of archaeological and historic artifacts. A must-visit if you're into ancient relics and art.
- **mistral.ministral-3-14b-instruct**: Napier Museum is Trivandrum’s oldest civic institution, founded in 1872, showcasing natural history, archaeology, and indigenous art—including the infamous *stone serpent* from Chengannur.  Link will laugh if you mention the snake again, *bonji vellam*.
- **mistral.mistral-large-3-675b-instruct**: The Napier Museum in Trivandrum is an architectural landmark built in the 19th century, famous for its Indo-Saracenic design, natural history and art collections, and the adjacent Zoological Garden. If you go, don’t miss the bronze idols—just watch out for the monkeys eyeing your snacks.
- **qwen.qwen3-32b-v1:0**: The Napier Museum in Thiruvananthapuram houses a collection of archaeological and art relics, including ancient coins, bronze idols, and artifacts from Kerala’s past. It’s named after Lord Napier, a British Governor of Madras, which makes the history part a bit ironic if you ask me.
- **qwen.qwen3-next-80b-a3b**: The Napier Museum is a historic art and natural history museum in Trivandrum, known for its unique Indo-Saracenic architecture and rare collection of bronze idols, ancient ornaments, and ivory carvings. It’s the kind of place where silence feels heavier than the artifacts — perfect for a quiet night stroll after the thampanoor chaos.
- **deepseek.v3.2**: The Napier Museum in Thiruvananthapuram is a 19th-century art and natural history museum famous for its unique Indo-Saracenic architecture and valuable historical collections. It's the kind of place where the building itself is as much of a exhibit as what's inside.
- **openai.gpt-oss-20b-1:0**: 
- **zai.glm-4.7-flash**: The Napier Museum in Thiruvananthapuram is an 19th-century Indo-Saracenic building famous for its bronze sculptures and rare archaeological finds. It is also known for a natural air-conditioning system that keeps the gallery cool.

### Which is the capital of Kerala and which district is it in?

- **google.gemma-3-12b-it**: The capital of Kerala is Trivandrum, also known as Thiruvananthapuram. It's in the Thiruvananthapuram district, naturally.
- **google.gemma-3-27b-it**: Trivandrum is the capital of Kerala and it’s in the Thiruvananthapuram district. Honestly, you’d think everyone would know that, considering the traffic here.
- **amazon.nova-micro-v1:0**: The capital of Kerala is Thiruvananthapuram. It's in the Thiruvananthapuram district. Trivandrum's still clinging onto its old name, much like some of us to our old habits.
- **amazon.nova-lite-v1:0**: [error rate_limited]
- **amazon.nova-pro-v1:0**: Thiruvananthapuram is the capital of Kerala and it is located in Thiruvananthapuram district. Just don’t get lost in the traffic there, machi.
- **mistral.ministral-3-14b-instruct**: Trivandrum—now officially Thiruvananthapuram—is the capital of Kerala, and it’s its own district. Don’t get lost in the traffic trying to find its borders, though.  (Also, the KSRTC bus from here to Kovalam will still call it "Trivandrum" out loud—magic.)
- **mistral.mistral-large-3-675b-instruct**: The capital of Kerala is Thiruvananthapuram, and it's in Thiruvananthapuram district. Surprised you didn’t know—city’s been sitting here since before your grandparents had Wi-Fi.
- **qwen.qwen3-32b-v1:0**: The capital of Kerala is Thiruvananthapuram, and it is located in the Thiruvananthapuram district. Chalai weather here makes it feel like the gods are throwing a party without inviting us.
- **qwen.qwen3-next-80b-a3b**: Thiruvananthapuram is the capital of Kerala, and it’s also the district it’s in. Chalai’s still awake, so you’re not alone if you’re out this late.
- **deepseek.v3.2**: Thiruvananthapuram is the capital of Kerala, and it is located within the Thiruvananthapuram district. It's also where I learned to avoid Thampanoor traffic.
- **openai.gpt-oss-20b-1:0**: Thiruvananthapuram is the capital of Kerala, and it lies within Thiruvananthapuram district.
- **zai.glm-4.7-flash**: Thiruvananthapuram is the capital of Kerala and it is the capital district of the state. The sky looks pretty heavy tonight, doesn't it?

### Give me a one-line tip for surviving Trivandrum traffic.

- **google.gemma-3-12b-it**: Assume absolutely nothing moves faster than a snail, machane. Kowdiar junction alone could swallow your entire afternoon.
- **google.gemma-3-27b-it**: Assume everything is trying to cut in front of you, because it is. Honestly, you get used to the honking after a while, machane.
- **amazon.nova-micro-v1:0**: Here's your tip: "Always assume any road in Trivandrum is a racetrack and be ready for anything." At least that keeps things interesting.
- **amazon.nova-lite-v1:0**: Always assume everyone else is an overconfident KSRTC driver. (Also, patience is key.)
- **amazon.nova-pro-v1:0**: If you're walking, always assume drivers won't stop for you. Keep your wits about you.  Tester, remember to always look both ways, even if the light is green.
- **mistral.ministral-3-14b-instruct**: Breathe through your mouth—kerosene fumes from three-wheelers will ruin your lungs otherwise.  Kidilam, but it’s the price you pay for having the city’s heart in your throat.
- **mistral.mistral-large-3-675b-instruct**: Assume every KSRTC bus is legally blind and every auto-rickshaw has a death wish—keep a three-second gap and pray to whichever deity your appi recommends. Works 60 % of the time, every time.
- **qwen.qwen3-32b-v1:0**: If you can, leave home before 8 AM or after 6 PM — the in-between hours are a chaotic dance with honking, heroics, and half-solved roadworks. Tester, if you’re stuck in the middle, pretend you’re part of the traffic; it moves faster if you stop caring.
- **qwen.qwen3-next-80b-a3b**: Don’t trust the GPS when it says “recalculating” near Kowdiar — just turn left at the auto-rickshaw with the broken horn.   You’ll get there. Eventually.
- **deepseek.v3.2**: Assume every KSRTC bus driver believes they are in a Formula 1 qualifier.   You'll live longer that way, mone.
- **openai.gpt-oss-20b-1:0**: 
- **zai.glm-4.7-flash**: Drive like the KSRTC bus drivers: aggressive, unpredictable, and never yielding. Navi's stars don't like the stress of Thampanoor, machi.

