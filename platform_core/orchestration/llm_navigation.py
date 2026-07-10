"""Compact, dependency-aware navigation packets for runtime LLM prompts.

Exact query hits are retained, then sparse BM25-like ranking and bounded traversal of
the SCC-condensed module graph add only nearby context.  Stdlib-only by design.
"""
from __future__ import annotations

import math
import re
from collections import Counter, deque
from functools import lru_cache
from typing import Any


def build_projection(repo_map: dict) -> dict:
    modules = {}
    for name, rec in (repo_map.get("modules") or {}).items():
        exports = [e.get("name", "") if isinstance(e, dict) else str(e) for e in rec.get("exports", ())]
        modules[name] = {"path": rec.get("path", ""), "purpose": rec.get("purpose", ""),
                         "exports": exports,
                         "depends_on": list(rec.get("depends_on", ())),
                         "callers": list(rec.get("callers", ())), "test": list(rec.get("test", ()))}
    return {"schema": 2, "modules": modules}


def _terms(text: str) -> list[str]:
    return [p.lower() for p in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text or "") if len(p) > 2]


def _document(name: str, rec: dict) -> list[str]:
    return _terms(" ".join([name, rec.get("path", ""), rec.get("purpose", ""), *rec.get("exports", ())]))


def _scc(graph: dict[str, list[str]]) -> tuple[dict[str, int], list[list[str]]]:
    """Iterative Kosaraju: small, deterministic condensation for bounded expansion."""
    nodes = sorted(set(graph) | {v for vs in graph.values() for v in vs})
    rev = {n: [] for n in nodes}
    for u, vs in graph.items():
        for v in vs:
            if v in rev:
                rev[v].append(u)
    seen, order = set(), []
    for root in nodes:
        if root in seen: continue
        seen.add(root); stack = [(root, iter(graph.get(root, ())))]
        while stack:
            node, it = stack[-1]
            try: nxt = next(it)
            except StopIteration: order.append(node); stack.pop(); continue
            if nxt in rev and nxt not in seen:
                seen.add(nxt); stack.append((nxt, iter(graph.get(nxt, ()))))
    comp_of, comps = {}, []
    for root in reversed(order):
        if root in comp_of: continue
        cid, members, stack = len(comps), [], [root]
        comp_of[root] = cid
        while stack:
            node = stack.pop(); members.append(node)
            for nxt in rev[node]:
                if nxt not in comp_of: comp_of[nxt] = cid; stack.append(nxt)
        comps.append(sorted(members))
    return comp_of, comps


def build_context_packet(projection: dict, query: str, *, budget_chars: int = 3000) -> dict:
    modules = projection.get("modules") or {}
    query_terms = _terms(query)
    docs = {name: _document(name, rec) for name, rec in modules.items()}
    direct = sorted(name for name, rec in modules.items()
                    if any(t in " ".join([name, rec.get("path", ""), *rec.get("exports", ())]).lower()
                           for t in query_terms))
    df = Counter(t for doc in docs.values() for t in set(doc)); n = max(1, len(docs))
    def bm25(name: str) -> float:
        doc = docs[name]; dl = max(1, len(doc)); avg = max(1.0, sum(map(len, docs.values())) / n)
        score = 0.0
        for t in query_terms:
            freq = doc.count(t)
            if freq: score += math.log((n - df[t] + .5) / (df[t] + .5) + 1) * freq * 2.2 / (freq + 1.2 * (.25 + .75 * dl / avg))
        return score
    ranked = sorted((name for name in modules if bm25(name) > 0 and name not in direct),
                    key=lambda x: (-bm25(x), x))
    graph = {name: [x for x in rec.get("depends_on", ()) + rec.get("callers", ()) if x in modules]
             for name, rec in modules.items()}
    comp_of, _ = _scc(graph)
    selected = list(direct) + ranked[:6]
    seen, queue = set(selected), deque(selected)
    while queue and len(selected) < 16:
        node = queue.popleft()
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen.add(nxt); selected.append(nxt); queue.append(nxt)
                if len(selected) >= 16: break
    rows, used, truncated = [], 0, False
    for name in selected:
        rec = {"module": name, "scc": comp_of.get(name, -1), **modules[name]}
        size = len(str(rec))
        if name not in direct and used + size > budget_chars:
            truncated = True; continue
        rows.append(rec); used += size
    return {"schema": 2, "query": query, "modules": rows, "direct_modules": direct,
            "context_chars": used, "budget_chars": budget_chars, "truncated": truncated or used > budget_chars,
            "over_budget_direct_context": used > budget_chars}
