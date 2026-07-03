from memory.conviction_ledger import record_judgment, score_judgment, track_record

def test_unscored_judgments_do_not_count(tmp_path):
    db = tmp_path / "c.db"
    record_judgment(judgment_type="opinion", domain="async", conviction=0.7, db_path=db)
    tr = track_record("opinion", "async", db_path=db)
    assert tr == {"hits": 0, "total": 0, "rate": 0.0}

def test_scored_judgments_build_track_record(tmp_path):
    db = tmp_path / "c.db"
    j1 = record_judgment(judgment_type="opinion", domain="async", conviction=0.7, db_path=db)
    j2 = record_judgment(judgment_type="opinion", domain="async", conviction=0.7, db_path=db)
    assert score_judgment(j1, True, db_path=db) is True
    assert score_judgment(j2, False, db_path=db) is True
    tr = track_record("opinion", "async", db_path=db)
    assert tr["total"] == 2
    assert tr["hits"] == 1
    assert abs(tr["rate"] - 0.5) < 1e-9

def test_track_record_is_domain_scoped(tmp_path):
    db = tmp_path / "c.db"
    j = record_judgment(judgment_type="opinion", domain="async", conviction=0.7, db_path=db)
    score_judgment(j, True, db_path=db)
    assert track_record("opinion", "windows", db_path=db)["total"] == 0

def test_score_nonexistent_returns_false(tmp_path):
    db = tmp_path / "c.db"
    assert score_judgment("no-such-id", True, db_path=db) is False
