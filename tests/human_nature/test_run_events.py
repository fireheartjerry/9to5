from human_nature.run_events import EVENT_TYPES, new_event_log, record_event, event_sequence


def test_new_event_log_empty():
    assert new_event_log() == []


def test_record_event_appends_in_order_with_seq():
    log = new_event_log()
    record_event(log, "SUBTASK_STARTED")
    record_event(log, "PATCH_LARGE", size=800)
    record_event(log, "TESTS_SKIPPED")

    assert [e["seq"] for e in log] == [0, 1, 2]
    assert event_sequence(log) == ["SUBTASK_STARTED", "PATCH_LARGE", "TESTS_SKIPPED"]


def test_record_event_ignores_unknown_type():
    log = new_event_log()
    record_event(log, "SUBTASK_STARTED")
    record_event(log, "BOGUS")

    assert len(log) == 1
    assert "BOGUS" not in EVENT_TYPES


def test_record_event_stores_fields():
    log = new_event_log()
    record_event(log, "PATCH_LARGE", size=800)

    assert log[0]["fields"] == {"size": 800}
