from dropship_desk.db import get_candidate_by_asin, list_candidates, prune_rejected, upsert_candidate
from dropship_desk.evaluate_service import run_evaluate
from dropship_desk.models import EvaluateRequest, OfferIn


def test_upsert_same_asin(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")

    offer = OfferIn(
        title="Widget",
        amazon_total=20.0,
        seller_country="CN",
        asin="B0TESTASI1",
    )
    a = run_evaluate(
        EvaluateRequest(asin_or_url="B0TESTASI1", offer=offer, ebay_price=55.0, save=True)
    )
    b = run_evaluate(
        EvaluateRequest(
            asin_or_url="B0TESTASI1",
            offer=offer.model_copy(update={"amazon_total": 22.0, "title": "Widget v2"}),
            ebay_price=60.0,
            save=True,
        )
    )
    assert a.candidate_id == b.candidate_id
    rows = list_candidates()
    assert len(rows) == 1
    assert rows[0]["amazon_total"] == 22.0
    assert rows[0]["title"] == "Widget v2"
    assert rows[0]["created_at"] <= rows[0]["updated_at"]


def test_pass_only_skips_new_rejects(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")

    offer = OfferIn(title="Cheap", amazon_total=20.0, seller_country="CN", asin="B0TESTASI2")
    r = run_evaluate(
        EvaluateRequest(asin_or_url="B0TESTASI2", offer=offer, ebay_price=22.0, save=True),
        persist="pass_only",
    )
    assert r.passed is False
    assert r.candidate_id is None
    assert list_candidates() == []


def test_protect_listed_status(tmp_path, monkeypatch):
    import dropship_desk.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")

    cid = upsert_candidate(
        asin="B0TESTASI3",
        title="Listed one",
        amazon_total=20.0,
        ebay_price=45.0,
        max_amazon_buy=20.0,
        status="listed",
        offer={"asin": "B0TESTASI3"},
        margin={"passed": True},
        hard_reject=[],
    )
    run_evaluate(
        EvaluateRequest(
            asin_or_url="B0TESTASI3",
            offer=OfferIn(title="Listed one", amazon_total=21.0, asin="B0TESTASI3", seller_country="CN"),
            ebay_price=45.0,
            save=True,
        )
    )
    row = get_candidate_by_asin("B0TESTASI3")
    assert row is not None
    assert row["id"] == cid
    assert row["status"] == "listed"
    assert row["amazon_total"] == 21.0


def test_prune_rejected(tmp_path, monkeypatch):
    import dropship_desk.config as cfg
    from dropship_desk import db as dbmod

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "dropship.sqlite3")

    upsert_candidate(
        asin="B0OLDREJ001",
        title="Old",
        amazon_total=10.0,
        ebay_price=12.0,
        max_amazon_buy=10.0,
        status="rejected",
        offer={},
        margin={},
        hard_reject=[],
    )
    # Force old timestamp
    with dbmod.connect() as conn:
        conn.execute(
            "UPDATE candidates SET updated_at = ? WHERE asin = ?",
            ("2020-01-01T00:00:00+00:00", "B0OLDREJ001"),
        )
    deleted = prune_rejected(older_than_days=7)
    assert deleted == 1
    assert get_candidate_by_asin("B0OLDREJ001") is None
