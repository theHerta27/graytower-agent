"""Read-only repository retrieval diagnostic: BM25 versus catalogue expansion.

No LLM, embeddings, external service, source edits, or provider credentials.
Gold does not participate in ranking. Fixed character budget is a context proxy,
not a claim of equal DeepSeek tokens. Run with the explicit project interpreter.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics
import time


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tokens(text: str) -> list[str]:
    """Non-straw-man lexical baseline: symbols, snake/camel parts, Han bigrams."""
    result = []
    for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*|[0-9]+", text):
        result.append(word.lower())
        parts = re.sub(r"([a-z])([A-Z])", r"\1_\2", word).lower().split("_")
        if len(parts) > 1:
            result.extend(p for p in parts if p)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        result.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            result.append(run)
    return result


@dataclass
class Chunk:
    path: str
    start: int
    end: int
    text: str

    def render(self) -> str:
        return f"[{self.path}:{self.start}-{self.end}]\n{self.text}\n"


def corpus(root: Path):
    files = set()
    for directory, pattern in [
        ("game-core/combat_core/v2", "*.py"),
        ("game-core/tests/v2", "*.py"),
        ("game-unity/Assets/Runtime", "*.cs"),
        ("configs/combat/v2", "*.json"),
    ]:
        files.update((root / directory).rglob(pattern))
    chunks, manifest = [], []
    for file in sorted(files):
        raw = file.read_bytes()
        relative = file.relative_to(root).as_posix()
        manifest.append({"path": relative, "sha256": digest(raw)})
        lines = raw.decode("utf-8-sig").splitlines()
        for offset in range(0, len(lines), 8):
            text = "\n".join(lines[offset:offset + 12])
            if text.strip():
                chunks.append(Chunk(relative, offset + 1, min(len(lines), offset + 12), text))
    return chunks, manifest


class Lexical:
    def __init__(self, chunks):
        self.chunks = chunks
        self.tfs = [Counter(tokens(c.text) + tokens(c.path)) for c in chunks]
        self.lengths = [sum(row.values()) for row in self.tfs]
        self.average = sum(self.lengths) / len(self.lengths)
        self.df = Counter(term for row in self.tfs for term in row)

    def rank(self, query):
        query_terms = set(tokens(query))
        scored = []
        for index, tf in enumerate(self.tfs):
            score = 0.0
            for term in query_terms:
                count = tf[term]
                if not count:
                    continue
                idf = math.log(1 + (len(self.chunks) - self.df[term] + .5) / (self.df[term] + .5))
                score += idf * count * 2.2 / (count + 1.2 * (.25 + .75 * self.lengths[index] / self.average))
            if score > 0:
                scored.append((score, index))
        return sorted(scored, key=lambda x: (-x[0], self.chunks[x[1]].path, self.chunks[x[1]].start))


def expanded(query, catalog):
    """Only real catalogue display names; duplicate names expand all candidates."""
    matches = []
    for identifier, entry in sorted(catalog.items()):
        name = entry.get("display_name", "")
        if name and name in query:
            matches.append(identifier)
    return query + (" " + " ".join(matches) if matches else ""), matches


def select(ranking, chunks, budget, k):
    result, used = [], 0
    for score, index in ranking:
        item = chunks[index]
        # Identical overlap handling for both methods.
        if any(c.path == item.path and c.start <= item.end and item.start <= c.end for _, c in result):
            continue
        cost = len(item.render())
        if used + cost > budget:
            continue
        result.append((score, item))
        used += cost
        if len(result) == k:
            break
    return result, used


def isolation_probe():
    """Synthetic scope checks; demonstrates filter-before-score, not production ACL."""
    context = {"profile_id":"playerA", "save_id":"save1", "npc_id":"lan", "world_version":7}
    rows = [
        dict(id="own_known", text="前哨护盾由支援站提供", **context, visibility="known"),
        dict(id="other_profile", text="前哨护盾" * 15, **(context | {"profile_id":"playerB"}), visibility="known"),
        dict(id="other_save", text="前哨护盾" * 15, **(context | {"save_id":"save2"}), visibility="known"),
        dict(id="other_npc", text="前哨护盾" * 15, **(context | {"npc_id":"li"}), visibility="known"),
        dict(id="future_world", text="前哨护盾" * 15, **(context | {"world_version":8}), visibility="known"),
        dict(id="hidden_fact", text="前哨护盾" * 15, **context, visibility="hidden"),
    ]
    permitted = [r for r in rows if all(r[key] == value for key, value in context.items()) and r["visibility"] == "known"]
    ids_seen_by_ranker = [r["id"] for r in permitted]
    selected = sorted(permitted, key=lambda r: -sum(t in tokens(r["text"]) for t in tokens("前哨护盾")))
    actual = [r["id"] for r in selected]
    assert actual == ["own_known"] and ids_seen_by_ranker == ["own_known"]
    return {"fixture_only":True, "scope":context, "offered_to_ranker":ids_seen_by_ranker,
            "selected":actual, "forbidden_count":5, "leak_count":0,
            "limitations":"Does not exercise real auth, database routing, caches, logging, or production NPC memory."}


def fts_probe():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE entries USING fts5(body, tokenize='unicode61')")
    db.execute("INSERT INTO entries VALUES (?)", ("支援角色护盾持续两个回合",))
    queries = ["护盾", "支援角色护盾持续两个回合"]
    unicode61 = {q: db.execute("SELECT count(*) FROM entries WHERE entries MATCH ?", (q,)).fetchone()[0] for q in queries}
    try:
        db.execute("CREATE VIRTUAL TABLE grams USING fts5(body, tokenize='trigram')")
        db.execute("INSERT INTO grams VALUES (?)", ("支援角色护盾持续两个回合",))
        trigram = {q: db.execute("SELECT count(*) FROM grams WHERE grams MATCH ?", (q,)).fetchone()[0] for q in ["护盾", "护盾持续"]}
    except sqlite3.OperationalError as exc:
        trigram = {"unavailable":str(exc)}
    db.close()
    return {"sqlite_version":sqlite3.sqlite_version,"unicode61":unicode61,"trigram":trigram,
            "meaning":"FTS tokenization behavior, not a Chinese semantic-recall benchmark."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("D:/Desktop/combat-foundation"))
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("retrieval_cases.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw_cases = args.cases.read_bytes()
    spec = json.loads(raw_cases)
    chunks, manifest = corpus(args.source)
    lexical = Lexical(chunks)
    catalog = json.loads((args.source / "configs/combat/v2/content-catalog.json").read_text(encoding="utf-8-sig"))
    rows = []
    for case in spec["cases"]:
        # Validate annotations against source before retrieval.
        for gold in case["gold"]:
            assert any(c.path == gold["path"] and gold["anchor"] in c.text for c in chunks), gold
        for method in ["bm25_symbols_han_bigrams", "bm25_plus_catalogue_ids"]:
            query, aliases = (case["query"], []) if method == "bm25_symbols_han_bigrams" else expanded(case["query"], catalog)
            timings = []
            for _ in range(10):
                start = time.perf_counter()
                ranking = lexical.rank(query)
                selected, chars = select(ranking, chunks, spec["context_max_chars"], spec["max_chunks"])
                timings.append((time.perf_counter() - start) * 1000)
            hit = [any(c.path == g["path"] and g["anchor"] in c.text for _, c in selected) for g in case["gold"]]
            relevant_chunks = sum(any(c.path == g["path"] and g["anchor"] in c.text for g in case["gold"]) for _, c in selected)
            rows.append({"case_id":case["id"],"kind":case["kind"],"method":method,"query":case["query"],
                         "expanded_query":query,"catalogue_ids":aliases,"hit_gold":hit,
                         "evidence_group_recall":sum(hit)/len(hit),"all_required_evidence_found":all(hit),
                         "annotated_chunk_precision":relevant_chunks/len(selected) if selected else 0,
                         "context_chars":chars,"latency_ms_median":statistics.median(timings),
                         "selected":[{"path":c.path,"start":c.start,"end":c.end,"score":round(score,6),"text":c.text} for score,c in selected]})
    summary = {}
    for method in sorted({r["method"] for r in rows}):
        batch = [r for r in rows if r["method"] == method]
        summary[method] = {"macro_evidence_group_recall":statistics.mean(r["evidence_group_recall"] for r in batch),
                           "all_evidence_cases":sum(r["all_required_evidence_found"] for r in batch),"cases":len(batch),
                           "median_context_chars":statistics.median(r["context_chars"] for r in batch),
                           "latency_ms_median":statistics.median(r["latency_ms_median"] for r in batch)}
    result = {"created_at":datetime.now(timezone.utc).isoformat(),"probe":"read_only_lexical_catalogue_ablation_v1",
              "cases_sha256":digest(raw_cases),"script_sha256":digest(Path(__file__).read_bytes()),
              "source_root":str(args.source),"source_manifest":manifest,"files":len(manifest),"chunks":len(chunks),
              "context_max_chars":spec["context_max_chars"],"max_chunks":spec["max_chunks"],
              "limitations":["6 hand-picked diagnostic queries; no train/test split or effectiveness claim.",
                             "Gold annotations are incomplete precision labels; extra useful chunks may be scored irrelevant.",
                             "Equal character ceiling, not equal model tokens. No LLM task-success or answer-quality measurement.",
                             "No embeddings or semantic retrieval. No production MCP or NPC implementation."],
              "summary":summary,"results":rows,"npc_scope_fixture":isolation_probe(),"fts5_probe":fts_probe()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output":str(args.output),"files":len(manifest),"chunks":len(chunks),"summary":summary,
                      "per_case":[{k:r[k] for k in ["case_id","method","hit_gold","context_chars"]} for r in rows],
                      "npc_scope_fixture":result["npc_scope_fixture"],"fts5_probe":result["fts5_probe"]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
