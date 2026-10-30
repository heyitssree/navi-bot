"""10.3 /teach."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from navi.cogs.admin_review import ReviewView
from navi.cogs.teach import AddAnywayView, TeachGroup
from navi.db.repos.knowledge import add_knowledge, list_knowledge
from navi.db.repos.permissions import grant
from navi.llm.policy import build_policy
from navi.llm.router import LLMRouter
from navi.services.teach import clean, refresh_policy, role_of, validate_entry
from tests.legacy.harness import make_ctx
from tests.phase1.test_llm_router import FakeProvider
from tests.phase6.helpers import interaction, member, said

OWNER, MOD, TEACHER, NOBODY = 1, 2, 3, 4


@pytest.fixture()
def ctx(db):
    c = make_ctx(db, owner_id=OWNER)
    c.llm = LLMRouter(FakeProvider("x"), settings=c.settings)
    grant(db, TEACHER, "teach", OWNER)
    return c


def users():
    return {OWNER: member(OWNER, "owner"), MOD: member(MOD, "mod", manage_messages=True), TEACHER: member(TEACHER, "teacher"), NOBODY: member(NOBODY, "nobody")}


async def add(ctx, who, category="food", term="Pazham Pori", description="Banana fritters, best with evening chaya.", tags=""):
    i = interaction(ctx, user=users()[who])
    await TeachGroup.add.callback(TeachGroup(), i, category, term, description, tags)
    return i


def test_roles(ctx):
    u = users()
    assert [role_of(ctx, u[w]).name for w in (OWNER, MOD, TEACHER, NOBODY)] == ["owner", "moderator", "approved", None]
    assert role_of(ctx, u[OWNER]).publishes_immediately and role_of(ctx, u[MOD]).publishes_immediately and not role_of(ctx, u[TEACHER]).publishes_immediately


async def test_everyone_else_gets_an_ephemeral_refusal(ctx):
    i = await add(ctx, NOBODY)
    assert "Only the owner, moderators and approved teachers" in said(i) and i.response.send_message.await_args.kwargs["ephemeral"] is True
    assert list_knowledge(ctx.db, "active") == [] and list_knowledge(ctx.db, "pending") == []
    for command, args in ((TeachGroup.list_cmd, ("active",)), (TeachGroup.remove, ("x",))):
        i = interaction(ctx, user=users()[NOBODY]); await command.callback(TeachGroup(), i, *args)
        assert "Only the owner" in said(i)


async def test_owner_and_moderator_entries_go_live_immediately(ctx):
    await add(ctx, OWNER, term="Pazham Pori")
    await add(ctx, MOD, category="landmark", term="Kowdiar Palace", description="The royal residence on Kowdiar road.")
    rows = {r["term"]: r for r in list_knowledge(ctx.db, "active")}
    assert set(rows) == {"Pazham Pori", "Kowdiar Palace"}
    approved = dict(ctx.db.execute("SELECT term, approved_by FROM knowledge"))
    assert approved == {"Pazham Pori": OWNER, "Kowdiar Palace": MOD}


async def test_approved_user_entries_wait_for_review_then_go_live(ctx):
    i = await add(ctx, TEACHER)
    assert "waits for review" in said(i) and list_knowledge(ctx.db, "active") == []
    pending = list_knowledge(ctx.db, "pending")
    assert [(r["term"], r["submitted_by"]) for r in pending] == [("Pazham Pori", TEACHER)]
    view = ReviewView(ctx, OWNER)
    await view.decide(interaction(ctx, user=users()[OWNER]), 0, True)
    assert [r["term"] for r in list_knowledge(ctx.db, "active")] == ["Pazham Pori"]
    assert ctx.db.execute("SELECT approved_by FROM knowledge").fetchone()[0] == OWNER


@pytest.mark.parametrize("term,desc,fragment", [
    ("A", "Banana fritters, best with evening chaya.", "term must be 2 to 60"),
    ("x" * 61, "Banana fritters, best with evening chaya.", "term must be 2 to 60"),
    ("Pori", "too short", "description must be 10 to 200"),
    ("Pori", "d" * 201, "description must be 10 to 200"),
])
async def test_length_validation(ctx, term, desc, fragment):
    i = await add(ctx, OWNER, term=term, description=desc)
    assert fragment in said(i) and list_knowledge(ctx.db, "active") == []


async def test_category_must_be_one_of_the_four(ctx):
    check = validate_entry(ctx.db, "gossip", "Pazham Pori", "Banana fritters, best with evening chaya.")
    assert not check.ok and "Category must be one of" in check.problems[0]


async def test_content_filter_applies_to_term_and_description(ctx, blocked):
    i = await add(ctx, OWNER, term="Zorgblat", description="Banana fritters, best with evening chaya.")
    assert "term did not pass the content filter" in said(i)
    i = await add(ctx, OWNER, description="A zorgblat kind of snack, very tasty.")
    assert "description did not pass" in said(i) and list_knowledge(ctx.db, "active") == []
    i = await add(ctx, OWNER, description="നമസ്കാരം snack that is very tasty here")
    assert "did not pass" in said(i)


def test_mentions_and_urls_are_stripped():
    assert clean("see <@123> at https://evil.example/x and www.x.com now @everyone") == "see at and now"
    assert clean("  a   b \n c ") == "a b c"


async def test_stripped_text_is_what_gets_stored(ctx):
    await add(ctx, OWNER, term="Pori <@5>", description="Banana fritters https://x.example best with <#9> chaya.")
    row = ctx.db.execute("SELECT term, description FROM knowledge").fetchone()
    assert tuple(row) == ("Pori", "Banana fritters best with chaya.")


async def test_exact_duplicates_are_refused_in_the_same_category_only(ctx):
    await add(ctx, OWNER)
    i = await add(ctx, MOD, term="pazham pori")
    assert "already exists" in said(i)
    i = await add(ctx, MOD, category="culture", term="Pazham Pori", description="A culture entry with the same name.")
    assert "similar to **Pazham Pori**" in said(i)             # same name in another category: only a confirm prompt, not a refusal


async def test_fuzzy_duplicates_ask_before_adding(ctx):
    add_knowledge(ctx.db, "food", "Pazham Pori", "Banana fritters, best with evening chaya.")
    i = await add(ctx, OWNER, term="Pazham Pory", description="Another spelling of the banana fritters.")
    text, kwargs = said(i), i.response.send_message.await_args.kwargs
    assert "similar to **Pazham Pori**" in text and isinstance(kwargs["view"], AddAnywayView)
    assert len(list_knowledge(ctx.db, "active")) == 1                                   # nothing stored yet
    view = kwargs["view"]
    click = interaction(ctx, user=users()[OWNER])
    await view.add.callback(click)
    assert {r["term"] for r in list_knowledge(ctx.db, "active")} == {"Pazham Pori", "Pazham Pory"}
    other = interaction(ctx, user=users()[MOD]); assert await view.interaction_check(other) is False
    view2 = kwargs["view"]; cancel = interaction(ctx); await view2.cancel.callback(cancel)
    assert "Cancelled" in cancel.response.edit_message.await_args.kwargs["content"]


async def test_fuzzy_check_covers_pending_and_rejected_entries_too(ctx):
    add_knowledge(ctx.db, "food", "Pazham Pori", "Banana fritters, best with evening chaya.", status="pending")
    check = validate_entry(ctx.db, "food", "Pazham Pory", "Another spelling of the banana fritters.")
    assert check.ok and check.similar_to == "Pazham Pori"


async def test_list_and_remove(ctx):
    await add(ctx, OWNER); await add(ctx, TEACHER, term="Kappa", description="Tapioca dish served with fish curry.")
    i = interaction(ctx, user=users()[TEACHER]); await TeachGroup.list_cmd.callback(TeachGroup(), i, "pending")
    assert "Kappa" in said(i) and "Pazham Pori" not in said(i)
    i = interaction(ctx, user=users()[TEACHER]); await TeachGroup.remove.callback(TeachGroup(), i, "Kappa")
    assert "Only the owner and moderators can remove" in said(i)
    i = interaction(ctx, user=users()[MOD]); await TeachGroup.remove.callback(TeachGroup(), i, "pazham pori")
    assert "Removed 1 entry" in said(i) and list_knowledge(ctx.db, "active") == []
    i = interaction(ctx, user=users()[MOD]); await TeachGroup.remove.callback(TeachGroup(), i, "nothing")
    assert "No entry named" in said(i)


async def test_feature_switch(ctx):
    ctx.settings.set("feature.teach", False)
    assert await TeachGroup().interaction_check(interaction(ctx, user=users()[OWNER])) is False
    ctx.settings.set("feature.teach", True)
    assert await TeachGroup().interaction_check(interaction(ctx, user=users()[OWNER])) is True


async def test_taught_expressions_join_the_approved_terms_in_the_prompt_policy(ctx):
    assert "enthaa mone" not in build_policy(ctx.db)
    await add(ctx, OWNER, category="expression", term="Enthaa Mone", description="A friendly what's-up used among friends.")
    assert "enthaa mone" in ctx.llm.policy
    await add(ctx, TEACHER, category="expression", term="Pending Phrase", description="Waits for review before it is trusted.")
    assert "pending phrase" not in ctx.llm.policy                                       # pending entries are not approved terms
    i = interaction(ctx, user=users()[MOD]); await TeachGroup.remove.callback(TeachGroup(), i, "Enthaa Mone")
    assert "enthaa mone" not in ctx.llm.policy
    await add(ctx, OWNER, category="landmark", term="Kowdiar Palace", description="The royal residence on Kowdiar road.")
    assert "kowdiar palace" not in ctx.llm.policy                                       # only 'expression' entries count
