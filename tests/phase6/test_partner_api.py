"""Regression: the partner API's endpoints must accept normal requests (they returned 422 when the request models
were annotations FastAPI could not resolve)."""
import os

from fastapi.testclient import TestClient

from navi.api.partner import create_app
from navi.db.repos.users import get_user_profile
from tests.legacy.harness import make_ctx


def client(db):
    os.environ["PARTNER_BOT_API_KEY"] = "k"
    os.environ["BOT_INTERNAL_SECRET"] = "s"
    ctx = make_ctx(db)
    return TestClient(create_app(db, None, ctx.settings, ctx.privacy)), ctx


def test_score_endpoint_awards_dedupes_and_validates(db):
    c, ctx = client(db)
    body = {"user_id": 5, "guild_id": 1, "username": "ben", "points": 40, "game_id": "g1", "game_type": "wordle"}
    assert c.post("/score", json=body).status_code in (401, 403)
    r = c.post("/score", json=body, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200 and r.json()["boli_awarded"] == 40 and r.json()["xp_awarded"] == 20
    p = get_user_profile(db, 5)
    assert (p["external_boli"], p["experience"]) == (40, 20)
    assert c.post("/score", json=body, headers={"Authorization": "Bearer k"}).status_code == 409
    assert c.post("/score", json={"user_id": "x"}, headers={"Authorization": "Bearer k"}).status_code == 422
    assert c.get("/score/recent", headers={"Authorization": "Bearer k"}).json()["logs"][0]["game_id"] == "g1"


def test_score_endpoint_respects_the_feature_switch_and_min_xp(db):
    c, ctx = client(db)
    ctx.settings.set("feature.partner_api", False)
    h = {"Authorization": "Bearer k"}
    assert c.post("/score", json={"user_id": 5, "guild_id": 1, "username": "b", "points": 4, "game_id": "g2"}, headers=h).status_code == 503
    ctx.settings.set("feature.partner_api", True); ctx.settings.set("partner.min_xp", 9)
    r = c.post("/score", json={"user_id": 5, "guild_id": 1, "username": "b", "points": 4, "game_id": "g2"}, headers=h)
    assert r.json()["xp_awarded"] == 9


def test_internal_batch_award(db):
    c, _ = client(db)
    body = {"game_id": "bam1", "awards": {"5": 30, "6": 10, "x": 5}}
    assert c.post("/internal/boli/award", json=body).status_code == 401
    r = c.post("/internal/boli/award", json=body, headers={"X-Internal-Secret": "s"})
    assert r.status_code == 200 and get_user_profile(db, 5)["external_boli"] == 30
    assert c.post("/internal/boli/award", json=body, headers={"X-Internal-Secret": "s"}).status_code == 409
