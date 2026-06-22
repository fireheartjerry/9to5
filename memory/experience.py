"""Experience Ledger -- Layer 0 of the Self-Improvement Engine.

A best-effort, structured, append-only SQLite store of every run and subtask, so the
brain can later learn from its own history (retrieval, consolidation, distillation).
Stdlib ``sqlite3`` only (zero new deps); WAL mode so the multi-process ControlBus world
can read while a run writes.

Design rules:
  * **Never block a run.** Every public mutation is wrapped so a ledger failure degrades
    to a logged warning, never an exception that reaches the orchestrator.
  * **Idempotent / resumable.** Rows upsert by natural key (``run_id`` / ``(run_id, st_id)``),
    so a re-run or a crash-resume double-counts nothing.
  * **Decoupled.** This module imports ``config`` only; it never imports ``state`` at
    module load (``state.task`` imports us). The one place we need ``TaskState`` -- the
    backfill -- imports it lazily.

See docs/superpowers/specs/2026-06-22-self-improvement-engine-design.md (Layer 0).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import config

LOG = config.getLogger("sie.experience")

# Serialize writes within this process; WAL guards cross-process readers.
_WRITE_LOCK = threading.Lock()

# CREATE-IF-NOT-EXISTS statements run on every connection, so adding a table in a later
# phase is just appending a statement here -- no migration machinery needed.
_SCHEMA: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS runs (
        run_id          TEXT PRIMARY KEY,
        task_id         TEXT,
        goal_raw        TEXT,
        goal_elaborated TEXT,
        goal_embedding  BLOB,
        universe_json   TEXT,
        control_mode    TEXT,
        status          TEXT,
        fitness_json    TEXT,
        prompt_set_id   TEXT,
        adapter_id      TEXT,
        started_at      TEXT,
        ended_at        TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS subtasks (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id                  TEXT,
        st_id                   TEXT,
        position                INTEGER,
        title                   TEXT,
        signature_tags          TEXT,
        effort                  TEXT,
        model                   TEXT,
        skills_json             TEXT,
        subagents_json          TEXT,
        invocation_spec_json    TEXT,
        cost_usd                REAL,
        num_turns               INTEGER,
        session_id              TEXT,
        verify_cmd              TEXT,
        verify_expect           TEXT,
        verify_passed           INTEGER,
        attempt_count           INTEGER,
        adversary_verdict       TEXT,
        adversary_concerns_json TEXT,
        replan_delta_json       TEXT,
        status                  TEXT,
        predicted_success       REAL,
        embedding               BLOB,
        started_at              TEXT,
        ended_at                TEXT,
        UNIQUE(run_id, st_id)
    )""",
    """CREATE TABLE IF NOT EXISTS eval_runs (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        suite_version  TEXT,
        prompt_set_id  TEXT,
        adapter_id     TEXT,
        ran_at         TEXT,
        score_json     TEXT,
        passed_gate    INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS lessons (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        scope          TEXT,
        signature_tags TEXT,
        text           TEXT,
        support_count  INTEGER,
        win_rate       REAL,
        last_seen_at   TEXT,
        embedding      BLOB,
        UNIQUE(scope, signature_tags, text)
    )""",
    """CREATE TABLE IF NOT EXISTS policy_arms (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        context_key   TEXT,
        action_json   TEXT,
        pulls         INTEGER,
        reward_sum    REAL,
        reward_sq_sum REAL,
        UNIQUE(context_key, action_json)
    )""",
    """CREATE TABLE IF NOT EXISTS prompt_variants (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        role        TEXT,
        version     INTEGER,
        parent_id   INTEGER,
        body_hash   TEXT,
        body        TEXT,
        file_path   TEXT,
        created_at  TEXT,
        state       TEXT,
        UNIQUE(role, body_hash)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_subtasks_run ON subtasks(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_subtasks_passed ON subtasks(verify_passed)",
    "CREATE INDEX IF NOT EXISTS idx_arms_ctx ON policy_arms(context_key)",
)


def _db_path(db_path: Optional[Path] = None) -> Path:
    """Resolve the ledger path at call time (so tests can monkeypatch the config const)."""
    return Path(db_path) if db_path is not None else Path(config.EXPERIENCE_DB_PATH)


@contextmanager
def _connect(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """Open a WAL connection with the schema ensured. Caller commits on success."""
    p = _db_path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        for stmt in _SCHEMA:
            conn.execute(stmt)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(db_path: Optional[Path] = None) -> None:
    """Create the database + schema if absent (idempotent)."""
    with _connect(db_path):
        pass


def _nowIso() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _j(value: Any) -> Optional[str]:
    """JSON-encode a value for storage, or None."""
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- writes

def record_run(run: dict[str, Any], db_path: Optional[Path] = None) -> bool:
    """Upsert a run row keyed by ``run_id``. Returns True on success (best-effort)."""
    if not config.EXPERIENCE_LEDGER_ENABLED:
        return False
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute(
                """INSERT INTO runs
                   (run_id, task_id, goal_raw, goal_elaborated, universe_json,
                    control_mode, status, fitness_json, prompt_set_id, adapter_id,
                    started_at, ended_at)
                   VALUES (:run_id, :task_id, :goal_raw, :goal_elaborated, :universe_json,
                    :control_mode, :status, :fitness_json, :prompt_set_id, :adapter_id,
                    :started_at, :ended_at)
                   ON CONFLICT(run_id) DO UPDATE SET
                    task_id=excluded.task_id, goal_raw=excluded.goal_raw,
                    goal_elaborated=excluded.goal_elaborated, universe_json=excluded.universe_json,
                    control_mode=excluded.control_mode, status=excluded.status,
                    fitness_json=COALESCE(excluded.fitness_json, runs.fitness_json),
                    prompt_set_id=COALESCE(excluded.prompt_set_id, runs.prompt_set_id),
                    adapter_id=COALESCE(excluded.adapter_id, runs.adapter_id),
                    ended_at=excluded.ended_at""",
                {
                    "run_id": run["run_id"],
                    "task_id": run.get("task_id"),
                    "goal_raw": run.get("goal_raw"),
                    "goal_elaborated": run.get("goal_elaborated"),
                    "universe_json": _j(run.get("universe")),
                    "control_mode": run.get("control_mode"),
                    "status": run.get("status"),
                    "fitness_json": _j(run.get("fitness")),
                    "prompt_set_id": run.get("prompt_set_id"),
                    "adapter_id": run.get("adapter_id"),
                    "started_at": run.get("started_at"),
                    "ended_at": run.get("ended_at"),
                },
            )
        return True
    except Exception as e:  # noqa: BLE001 -- ledger must never break a run
        LOG.warning("record_run failed (ignored): %s", e)
        return False


def record_subtask(run_id: str, st: dict[str, Any], db_path: Optional[Path] = None) -> bool:
    """Upsert a subtask row keyed by ``(run_id, st_id)``. Best-effort."""
    if not config.EXPERIENCE_LEDGER_ENABLED:
        return False
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute(
                """INSERT INTO subtasks
                   (run_id, st_id, position, title, signature_tags, effort, model,
                    skills_json, subagents_json, invocation_spec_json, cost_usd, num_turns,
                    session_id, verify_cmd, verify_expect, verify_passed, attempt_count,
                    adversary_verdict, adversary_concerns_json, replan_delta_json, status,
                    predicted_success, started_at, ended_at)
                   VALUES
                   (:run_id, :st_id, :position, :title, :signature_tags, :effort, :model,
                    :skills_json, :subagents_json, :invocation_spec_json, :cost_usd, :num_turns,
                    :session_id, :verify_cmd, :verify_expect, :verify_passed, :attempt_count,
                    :adversary_verdict, :adversary_concerns_json, :replan_delta_json, :status,
                    :predicted_success, :started_at, :ended_at)
                   ON CONFLICT(run_id, st_id) DO UPDATE SET
                    position=excluded.position, title=excluded.title,
                    signature_tags=COALESCE(excluded.signature_tags, subtasks.signature_tags),
                    effort=COALESCE(excluded.effort, subtasks.effort),
                    model=COALESCE(excluded.model, subtasks.model),
                    skills_json=COALESCE(excluded.skills_json, subtasks.skills_json),
                    subagents_json=COALESCE(excluded.subagents_json, subtasks.subagents_json),
                    invocation_spec_json=COALESCE(excluded.invocation_spec_json, subtasks.invocation_spec_json),
                    cost_usd=COALESCE(excluded.cost_usd, subtasks.cost_usd),
                    num_turns=COALESCE(excluded.num_turns, subtasks.num_turns),
                    session_id=COALESCE(excluded.session_id, subtasks.session_id),
                    verify_cmd=COALESCE(excluded.verify_cmd, subtasks.verify_cmd),
                    verify_expect=COALESCE(excluded.verify_expect, subtasks.verify_expect),
                    verify_passed=COALESCE(excluded.verify_passed, subtasks.verify_passed),
                    attempt_count=COALESCE(excluded.attempt_count, subtasks.attempt_count),
                    adversary_verdict=COALESCE(excluded.adversary_verdict, subtasks.adversary_verdict),
                    adversary_concerns_json=COALESCE(excluded.adversary_concerns_json, subtasks.adversary_concerns_json),
                    replan_delta_json=COALESCE(excluded.replan_delta_json, subtasks.replan_delta_json),
                    status=COALESCE(excluded.status, subtasks.status),
                    predicted_success=COALESCE(excluded.predicted_success, subtasks.predicted_success),
                    ended_at=excluded.ended_at""",
                _subtask_params(run_id, st),
            )
        return True
    except Exception as e:  # noqa: BLE001
        LOG.warning("record_subtask failed (ignored): %s", e)
        return False


def set_subtask_embedding(run_id: str, st_id: str, blob: bytes,
                          db_path: Optional[Path] = None) -> bool:
    """Attach an embedding BLOB to an existing subtask row (Layer 1 retrieval). Best-effort."""
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute("UPDATE subtasks SET embedding=? WHERE run_id=? AND st_id=?",
                         (blob, run_id, st_id))
        return True
    except Exception as e:  # noqa: BLE001
        LOG.warning("set_subtask_embedding failed (ignored): %s", e)
        return False


def embedded_subtasks(only_passed: bool = True,
                      db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Subtask rows that carry an embedding -- the candidate pool for top-K retrieval."""
    with _connect(db_path) as conn:
        sql = "SELECT * FROM subtasks WHERE embedding IS NOT NULL"
        if only_passed:
            sql += " AND verify_passed=1"
        return [dict(r) for r in conn.execute(sql)]


def record_eval(score: dict[str, Any], *, suite_version: str = "v1",
                prompt_set_id: Optional[str] = None, adapter_id: Optional[str] = None,
                passed_gate: Optional[bool] = None, db_path: Optional[Path] = None) -> Optional[int]:
    """Append an eval-harness result row; returns its rowid (or None on failure)."""
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            cur = conn.execute(
                """INSERT INTO eval_runs
                   (suite_version, prompt_set_id, adapter_id, ran_at, score_json, passed_gate)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (suite_version, prompt_set_id, adapter_id, _nowIso(), _j(score),
                 None if passed_gate is None else int(passed_gate)),
            )
            return int(cur.lastrowid)
    except Exception as e:  # noqa: BLE001
        LOG.warning("record_eval failed (ignored): %s", e)
        return None


# ----------------------------------------------------------------- shape translation

def _subtask_params(run_id: str, st: dict[str, Any]) -> dict[str, Any]:
    """Translate a TaskState lean-subtask dict into a row's bind params.

    Tolerant of partially-filled subtasks: any absent field maps to None and the upsert
    COALESCE keeps the previously-stored value, so repeated syncs only ever add detail.
    """
    verify = st.get("verify") or {}
    vres = st.get("verify_result") or {}
    session = st.get("session") or {}
    passed = vres.get("passed")
    return {
        "run_id": run_id,
        "st_id": st.get("subtask_id"),
        "position": st.get("_position"),
        "title": st.get("title"),
        "signature_tags": st.get("signature_tags"),
        "effort": session.get("effort") or st.get("effort_level"),
        "model": session.get("model"),
        "skills_json": _j(session.get("skills")),
        "subagents_json": _j(session.get("subagents")),
        "invocation_spec_json": _j(session.get("invocation_spec")),
        "cost_usd": session.get("cost_usd"),
        "num_turns": session.get("num_turns"),
        "session_id": session.get("session_id"),
        "verify_cmd": verify.get("cmd"),
        "verify_expect": verify.get("expect"),
        "verify_passed": None if passed is None else int(bool(passed)),
        "attempt_count": session.get("attempts") or vres.get("attempt_count"),
        "adversary_verdict": st.get("_adversary_verdict"),
        "adversary_concerns_json": _j(st.get("_adversary_concerns")),
        "replan_delta_json": _j(st.get("_replan_delta")),
        "status": st.get("status"),
        "predicted_success": st.get("predicted_success"),
        "started_at": st.get("started_at"),
        "ended_at": st.get("completed_at"),
    }


def sync_run(state_data: dict[str, Any], db_path: Optional[Path] = None) -> bool:
    """Best-effort upsert of the run row from a TaskState's lean ``data`` dict.

    ``run_id`` == ``task_id`` (one run per task; resume continues the same run).
    """
    meta = state_data.get("meta", {}) or {}
    return record_run({
        "run_id": state_data.get("task_id"),
        "task_id": state_data.get("task_id"),
        "goal_raw": meta.get("goal_raw"),
        "goal_elaborated": meta.get("goal_elaborated"),
        "universe": meta.get("universe"),
        "control_mode": meta.get("control_mode"),
        "status": meta.get("status"),
        "started_at": meta.get("started_at"),
        "ended_at": _nowIso() if meta.get("status") in _TERMINAL else None,
    }, db_path=db_path)


def sync_subtask(state_data: dict[str, Any], st: dict[str, Any],
                 db_path: Optional[Path] = None) -> bool:
    """Best-effort upsert of one subtask, enriching it with position + the latest
    adversary verdict found in the run's ``adversary_reviews`` before storing."""
    subs = (state_data.get("plan", {}) or {}).get("subtasks", []) or []
    enriched = dict(st)
    try:
        enriched["_position"] = next(
            i for i, s in enumerate(subs) if s.get("subtask_id") == st.get("subtask_id"))
    except StopIteration:
        enriched["_position"] = None
    verdict = None
    for rv in state_data.get("adversary_reviews", []) or []:
        if rv.get("subtask_id") == st.get("subtask_id"):
            verdict = rv.get("verdict")  # last wins
    enriched["_adversary_verdict"] = verdict
    return record_subtask(state_data.get("task_id"), enriched, db_path=db_path)


_TERMINAL = ("done", "complete", "aborted", "partial", "blocked", "failed")


# --------------------------------------------------------------------------- reads

# ---------------------------------------------------------------- lessons (L2) + policy (L4)

def upsert_lesson(scope: str, signature_tags: str, text: str, *, support_count: int,
                  win_rate: float, db_path: Optional[Path] = None) -> bool:
    """Insert/refresh a consolidated lesson (keyed by scope+tags+text). Best-effort."""
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute(
                """INSERT INTO lessons (scope, signature_tags, text, support_count, win_rate, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scope, signature_tags, text) DO UPDATE SET
                     support_count=excluded.support_count, win_rate=excluded.win_rate,
                     last_seen_at=excluded.last_seen_at""",
                (scope, signature_tags, text, int(support_count), float(win_rate), _nowIso()))
        return True
    except Exception as e:  # noqa: BLE001
        LOG.warning("upsert_lesson failed (ignored): %s", e)
        return False


def fetch_lessons(scope: Optional[str] = None,
                  db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        if scope is None:
            rows = conn.execute("SELECT * FROM lessons ORDER BY support_count DESC")
        else:
            rows = conn.execute(
                "SELECT * FROM lessons WHERE scope=? ORDER BY support_count DESC", (scope,))
        return [dict(r) for r in rows]


def clear_lessons(db_path: Optional[Path] = None) -> None:
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("DELETE FROM lessons")


def set_arm(context_key: str, action_json: str, *, pulls: int, reward_sum: float,
            reward_sq_sum: float, db_path: Optional[Path] = None) -> bool:
    """Write a policy arm's accumulated stats (keyed by context+action). Best-effort."""
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute(
                """INSERT INTO policy_arms (context_key, action_json, pulls, reward_sum, reward_sq_sum)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(context_key, action_json) DO UPDATE SET
                     pulls=excluded.pulls, reward_sum=excluded.reward_sum,
                     reward_sq_sum=excluded.reward_sq_sum""",
                (context_key, action_json, int(pulls), float(reward_sum), float(reward_sq_sum)))
        return True
    except Exception as e:  # noqa: BLE001
        LOG.warning("set_arm failed (ignored): %s", e)
        return False


def fetch_arms(context_key: Optional[str] = None,
               db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        if context_key is None:
            rows = conn.execute("SELECT * FROM policy_arms")
        else:
            rows = conn.execute(
                "SELECT * FROM policy_arms WHERE context_key=?", (context_key,))
        return [dict(r) for r in rows]


def clear_arms(db_path: Optional[Path] = None) -> None:
    with _WRITE_LOCK, _connect(db_path) as conn:
        conn.execute("DELETE FROM policy_arms")


# ---------------------------------------------------------------- prompt variants (L3)

def register_variant(role: str, body: str, *, state: str = "challenger",
                     parent_id: Optional[int] = None, file_path: Optional[str] = None,
                     db_path: Optional[Path] = None) -> Optional[int]:
    """Register a prompt variant (deduped by role+body hash). Returns its id. If the body
    already exists for the role, returns the existing id without changing its state."""
    import hashlib
    h = hashlib.sha256(body.encode("utf-8")).hexdigest()
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            row = conn.execute(
                "SELECT id FROM prompt_variants WHERE role=? AND body_hash=?", (role, h)).fetchone()
            if row:
                return int(row["id"])
            ver = conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 AS v FROM prompt_variants WHERE role=?",
                (role,)).fetchone()["v"]
            cur = conn.execute(
                """INSERT INTO prompt_variants
                   (role, version, parent_id, body_hash, body, file_path, created_at, state)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (role, ver, parent_id, h, body, file_path, _nowIso(), state))
            return int(cur.lastrowid)
    except Exception as e:  # noqa: BLE001
        LOG.warning("register_variant failed (ignored): %s", e)
        return None


def get_champion(role: str, db_path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM prompt_variants WHERE role=? AND state='champion' "
            "ORDER BY version DESC LIMIT 1", (role,)).fetchone()
        return dict(row) if row else None


def get_champion_body(role: str, db_path: Optional[Path] = None) -> Optional[str]:
    champ = get_champion(role, db_path=db_path)
    return champ["body"] if champ else None


def fetch_variants(role: str, state: Optional[str] = None,
                   db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        if state is None:
            rows = conn.execute(
                "SELECT * FROM prompt_variants WHERE role=? ORDER BY version", (role,))
        else:
            rows = conn.execute(
                "SELECT * FROM prompt_variants WHERE role=? AND state=? ORDER BY version",
                (role, state))
        return [dict(r) for r in rows]


def promote_variant(role: str, variant_id: int, db_path: Optional[Path] = None) -> bool:
    """Make ``variant_id`` the champion for ``role``; retire the previous champion(s).
    Atomic: a single transaction so there is never two champions or none."""
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute(
                "UPDATE prompt_variants SET state='retired' WHERE role=? AND state='champion'",
                (role,))
            conn.execute(
                "UPDATE prompt_variants SET state='champion' WHERE id=? AND role=?",
                (variant_id, role))
        return True
    except Exception as e:  # noqa: BLE001
        LOG.warning("promote_variant failed (ignored): %s", e)
        return False


def tag_run_prompt(run_id: str, prompt_set_id: str, db_path: Optional[Path] = None) -> bool:
    """Record which prompt champion authored a run (so per-variant field metrics exist)."""
    try:
        with _WRITE_LOCK, _connect(db_path) as conn:
            conn.execute("UPDATE runs SET prompt_set_id=? WHERE run_id=?",
                         (str(prompt_set_id), run_id))
        return True
    except Exception as e:  # noqa: BLE001
        LOG.warning("tag_run_prompt failed (ignored): %s", e)
        return False


def prompt_field_stats(prompt_set_id: str, db_path: Optional[Path] = None) -> dict[str, int]:
    """First-pass field outcomes for subtasks of runs authored by ``prompt_set_id``:
    {n, first_pass}. The raw signal the promotion proportion test consumes."""
    with _connect(db_path) as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n,
                      SUM(CASE WHEN s.verify_passed=1
                                AND (s.attempt_count IS NULL OR s.attempt_count<=1)
                               THEN 1 ELSE 0 END) AS fp
               FROM subtasks s JOIN runs r ON s.run_id = r.run_id
               WHERE r.prompt_set_id = ?""", (str(prompt_set_id),)).fetchone()
    return {"n": int(row["n"] or 0), "first_pass": int(row["fp"] or 0)}


def fetch_runs(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY started_at")]


def fetch_subtasks(run_id: Optional[str] = None,
                   db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        if run_id is None:
            rows = conn.execute("SELECT * FROM subtasks ORDER BY run_id, position")
        else:
            rows = conn.execute(
                "SELECT * FROM subtasks WHERE run_id=? ORDER BY position", (run_id,))
        return [dict(r) for r in rows]


def gold_examples(db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """First-attempt, verify-passing, adversary-approved subtasks -- the clean training
    signal later phases distill from. (Defined now so downstream phases can rely on it.)"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM subtasks
               WHERE verify_passed=1 AND (attempt_count IS NULL OR attempt_count<=1)
                 AND (adversary_verdict IS NULL OR adversary_verdict IN ('approved','approve'))
               ORDER BY run_id, position""")
        return [dict(r) for r in rows]


def fitness_series(limit: int = 90, db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Recent eval-harness scores, oldest-first -- the visible months-long progress curve."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ran_at, score_json, passed_gate FROM eval_runs ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    out = []
    for r in reversed(rows):
        try:
            score = json.loads(r["score_json"]) if r["score_json"] else {}
        except Exception:  # noqa: BLE001
            score = {}
        out.append({"ran_at": r["ran_at"], "score": score, "passed_gate": r["passed_gate"]})
    return out


def counts(db_path: Optional[Path] = None) -> dict[str, int]:
    """Row counts per table -- handy for backfill/health summaries."""
    with _connect(db_path) as conn:
        return {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
                for t in ("runs", "subtasks", "eval_runs")}


# --------------------------------------------------------------------------- backfill

def backfill_from_store(db_path: Optional[Path] = None) -> dict[str, int]:
    """Seed the ledger from the existing task-JSON store so months-long learning never
    starts cold. Lazy-imports TaskState to avoid an import cycle. Idempotent (upserts)."""
    from state.task import TaskState  # lazy: state.task imports this module

    runs = subs = 0
    for _f, data in TaskState.iterStored():
        if sync_run(data, db_path=db_path):
            runs += 1
        for st in (data.get("plan", {}) or {}).get("subtasks", []) or []:
            if sync_subtask(data, st, db_path=db_path):
                subs += 1
    LOG.info("backfill complete: %d runs, %d subtasks", runs, subs)
    return {"runs": runs, "subtasks": subs}


if __name__ == "__main__":  # pragma: no cover -- manual backfill/inspection entrypoint
    init()
    result = backfill_from_store()
    print(f"backfilled {result['runs']} runs, {result['subtasks']} subtasks")
    print("counts:", counts())
