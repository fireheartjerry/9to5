"""Bounded generational loop: generation count, budget/plateau stops, diverse-elite seeding."""
from platform_core.orchestration import generational as gen
from platform_core.orchestration.invention_types import QDCell, QDElite
from platform_core.orchestration.qd_archive import QDArchive


def _elite(subsys, eid, verification=1.0, novelty=0.5):
    m = {"verification_score": verification, "impact_score": 0.6, "maintainability_score": 0.5,
         "adoption_score": 0.5, "cost_efficiency_score": 0.5, "reversibility_score": 0.5,
         "measured_novelty": novelty, "risk_inverse": 0.5}
    return QDElite(id=eid, candidate_id=eid, cell=QDCell(subsystem=subsys), metrics=m,
                   evidence_refs=["r1"])


def test_qd_plateaued():
    assert gen.qd_plateaued([1.0, 1.0], 2) is False         # not enough samples yet
    assert gen.qd_plateaued([1.0, 1.0, 1.0], 2) is True     # 2 flat gens after baseline
    assert gen.qd_plateaued([1.0, 1.0, 1.0, 1.0], 2) is True
    assert gen.qd_plateaued([1.0, 1.0, 2.0, 3.0], 2) is False  # still improving


def test_generation_count_respects_config():
    def run_gen(g, seeds):
        return [_elite(f"c{g}", f"e{g}")]                    # distinct cell each gen -> qd grows
    r = gen.run_generational(generations=3, run_gen=run_gen, base_angles=["A", "B"])
    assert r["generations_run"] == 3
    assert r["coverage"] == 3
    assert r["stop_reason"] == "generations_exhausted"


def test_cost_ceiling_stops_search():
    spent = {"v": 0.0}

    def cost_fn():
        return spent["v"]

    def run_gen(g, seeds):
        spent["v"] += 10.0                                  # each gen costs 10
        return [_elite(f"c{g}", f"e{g}")]
    r = gen.run_generational(generations=5, run_gen=run_gen, base_angles=["A"],
                             cost_ceiling=5.0, cost_fn=cost_fn)
    assert r["generations_run"] == 1                        # gen1 blocked by ceiling
    assert r["stop_reason"] == "cost_ceiling"


def test_plateau_stops_early():
    def run_gen(g, seeds):
        return [_elite("same", "same")]                     # same elite -> qd_score flat
    r = gen.run_generational(generations=6, run_gen=run_gen, base_angles=["A"], patience=2)
    assert r["generations_run"] < 6
    assert r["stop_reason"] == "qd_plateau"


def test_next_generation_seeds_reference_elites():
    a = QDArchive()
    a.add(_elite("memory", "e1"))
    a.add(_elite("explore", "e2"))
    seeds = gen.next_generation_seeds(a, ["baseA"], n=3)
    assert "baseA" in seeds
    assert any("build on elite" in s for s in seeds)        # seeded from diverse elites
    assert any("graft" in s for s in seeds)                 # recombination seed present


def test_best_is_highest_fitness():
    def run_gen(g, seeds):
        return [_elite(f"c{g}", f"e{g}", verification=0.3 + 0.2 * g)]  # later gens stronger
    r = gen.run_generational(generations=3, run_gen=run_gen, base_angles=["A"])
    assert r["best"].candidate_id == "e2"                   # highest verification


def test_failing_generation_does_not_crash():
    def run_gen(g, seeds):
        if g == 1:
            raise RuntimeError("boom")
        return [_elite(f"c{g}", f"e{g}")]
    r = gen.run_generational(generations=3, run_gen=run_gen, base_angles=["A"])
    assert r["generations_run"] == 3                        # survived the bad generation
    assert r["coverage"] == 2                               # gen1 contributed nothing
