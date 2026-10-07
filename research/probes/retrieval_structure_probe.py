"""Second diagnostic: auto-extracted JSON/AST relations, same frozen questions.

Adds natural JSON objects and short Python branch/schema spans to BOTH arms.
Compares lexical + aliases with/without relation boosts on that shared corpus.
This is an exploratory follow-up after seeing first-run failures, not holdout.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import time

from retrieval_probe import Chunk, Lexical, corpus, digest, expanded, select


def structures(root, chunks, manifest):
    records, json_nodes = [], []
    for file in manifest:
        path = file["path"]
        source = (root / path).read_text(encoding="utf-8-sig")
        lines = source.splitlines()
        if path.endswith(".json"):
            # JSONDecoder establishes real object boundaries; no string brace counting.
            for match in re.finditer(r'^\s*"([^"\n]+)"\s*:\s*(\{)', source, re.MULTILINE):
                brace = match.start(2)
                value, consumed = json.JSONDecoder().raw_decode(source[brace:])
                first = source.count("\n", 0, match.start(1)) + 1
                last = source.count("\n", 0, brace + consumed) + 1
                body = "\n".join(lines[first - 1:last])
                if len(body) > 2200:
                    continue
                scalars = {key:val for key,val in value.items() if isinstance(val, (str, int, float, bool))}
                chunk = Chunk(path, first, last, body)
                records.append((chunk, {"type":"json_object","entity_id":match.group(1),"fields":scalars}))
        if not path.endswith(".py"):
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                first, last = max(1, node.lineno - 3), min(len(lines), node.end_lineno + 3)
                records.append((Chunk(path, first, last, "\n".join(lines[first - 1:last])),
                                {"type":"schema_field","field":node.target.id}))
            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                test = node.test
                if (isinstance(test.left, ast.Attribute) and len(test.ops) == 1
                    and isinstance(test.ops[0], ast.Eq) and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)):
                    first, last = node.lineno, max(stmt.end_lineno for stmt in node.body)
                    body = "\n".join(lines[first - 1:last])
                    if len(body) <= 2200:
                        records.append((Chunk(path, first, last, body),
                                        {"type":"value_branch","field":test.left.attr,"value":test.comparators[0].value}))
    # Keep exactly the same enriched corpus in control and relation arms.
    enriched = list(chunks)
    keys = {(c.path,c.start,c.end):i for i,c in enumerate(enriched)}
    metadata = defaultdict(list)
    for chunk, record in records:
        key = (chunk.path,chunk.start,chunk.end)
        if key not in keys:
            keys[key] = len(enriched)
            enriched.append(chunk)
        index = keys[key]
        metadata[index].append(record)
        if record["type"] == "json_object":
            json_nodes.append((index, record))
    # Field reads are parsed Attributes, not guessed from Chinese labels or test gold.
    reads = defaultdict(set)
    schemas = defaultdict(set)
    branches = defaultdict(set)
    for file in manifest:
        if not file["path"].endswith(".py"):
            continue
        tree = ast.parse((root / file["path"]).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                for index, chunk in enumerate(enriched):
                    if chunk.path == file["path"] and chunk.start <= node.lineno <= chunk.end:
                        reads[node.attr].add(index)
    for index, rows in metadata.items():
        for row in rows:
            if row["type"] == "schema_field":
                schemas[row["field"]].add(index)
            if row["type"] == "value_branch":
                branches[(row["field"],str(row["value"]))].add(index)
    return enriched, json_nodes, reads, schemas, branches


def relations(query, aliases, chunks, nodes, reads, schemas, branches):
    # Exact ID query is also valid. This does not inspect case id, kind, or gold.
    seeds = set(aliases)
    for _, node in nodes:
        identifier = node["entity_id"]
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(identifier) + r"(?![A-Za-z0-9_])", query):
            seeds.add(identifier)
    paths = defaultdict(list)
    for index, node in nodes:
        if node["entity_id"] not in seeds:
            continue
        entity = node["entity_id"]
        paths[index].append({"weight":1.2,"relation":["name_or_exact_id",entity,"json_object"]})
        fields = node["fields"]
        # Only fields actually used by source/contract. Rarity ranks generic edges.
        field_names = [f for f in fields if reads[f] or schemas[f]]
        field_names.sort(key=lambda f:(len(reads[f])+len(schemas[f]),f))
        for field in field_names[:4]:
            for target in reads[field]:
                paths[target].append({"weight":.55,"relation":[entity,"field",field,"ast_attribute_read"]})
            for target in schemas[field]:
                paths[target].append({"weight":.45,"relation":[entity,"field",field,"ast_schema_field"]})
        for field, value in fields.items():
            for target in branches[(field,str(value))]:
                paths[target].append({"weight":.95,"relation":[entity,field,str(value),"ast_equality_branch"]})
    return paths, sorted(seeds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,default=Path("D:/Desktop/combat-foundation"))
    parser.add_argument("--cases",type=Path,default=Path(__file__).with_name("retrieval_cases.json"))
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    raw = args.cases.read_bytes()
    spec = json.loads(raw)
    original, manifest = corpus(args.source)
    chunks, nodes, reads, schemas, branches = structures(args.source, original, manifest)
    lexical = Lexical(chunks)
    catalog = json.loads((args.source/"configs/combat/v2/content-catalog.json").read_text(encoding="utf-8-sig"))
    results=[]
    for case in spec["cases"]:
        query, aliases = expanded(case["query"],catalog)
        for method in ["shared_structured_corpus_lexical_alias","shared_structured_corpus_relations"]:
            timings=[]
            for _ in range(10):
                start=time.perf_counter()
                ranking=lexical.rank(query)
                edges, seeds = {}, []
                if method.endswith("relations"):
                    edges,seeds=relations(query,aliases,chunks,nodes,reads,schemas,branches)
                    scores={index:score for score,index in ranking}
                    scale=max(scores.values(),default=1.0)
                    for index,paths in edges.items():
                        # One bounded max boost avoids multiplying repeated references.
                        scores[index]=scores.get(index,0)+scale*max(p["weight"] for p in paths)
                    ranking=sorted(((s,i) for i,s in scores.items()),key=lambda x:(-x[0],chunks[x[1]].path,chunks[x[1]].start))
                selected,used=select(ranking,chunks,spec["context_max_chars"],spec["max_chunks"])
                timings.append((time.perf_counter()-start)*1000)
            hits=[any(c.path==g["path"] and g["anchor"] in c.text for _,c in selected) for g in case["gold"]]
            results.append({"case_id":case["id"],"method":method,"query":case["query"],"expanded_query":query,"relation_seeds":seeds,
                            "hit_gold":hits,"evidence_group_recall":sum(hits)/len(hits),"all_required_evidence_found":all(hits),
                            "context_chars":used,"latency_ms_median":statistics.median(timings),
                            "selected":[{"path":c.path,"start":c.start,"end":c.end,"score":round(score,6),"text":c.text,
                                         "relations":edges.get(next(i for i,x in enumerate(chunks) if x is c),[])} for score,c in selected]})
    summary={}
    for method in sorted({r["method"] for r in results}):
        rows=[r for r in results if r["method"]==method]
        summary[method]={"macro_evidence_group_recall":statistics.mean(r["evidence_group_recall"] for r in rows),
                         "all_evidence_cases":sum(r["all_required_evidence_found"] for r in rows),"cases":len(rows),
                         "latency_ms_median":statistics.median(r["latency_ms_median"] for r in rows)}
    output={"created_at":datetime.now(timezone.utc).isoformat(),"probe":"exploratory_json_ast_relations_v1",
            "cases_sha256":digest(raw),"script_sha256":digest(Path(__file__).read_bytes()),
            "base_script_sha256":digest(Path(__file__).with_name("retrieval_probe.py").read_bytes()),
            "source_manifest":manifest,"original_chunks":len(original),"shared_enriched_chunks":len(chunks),
            "context_max_chars":spec["context_max_chars"],"max_chunks":spec["max_chunks"],
            "limitations":["Exploratory follow-up motivated by the first result, same 6 questions, not held out.",
                           "Both new arms share natural JSON object and short AST chunks; old results preserved separately.",
                           "Relations reflect field reads/type comparisons, not verified full data flow or execution effects.",
                           "No embeddings, model/provider calls, production index, or task completion measurements."],
            "summary":summary,"results":results}
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(args.output),"original_chunks":len(original),"shared_enriched_chunks":len(chunks),"summary":summary,
                      "per_case":[{k:r[k] for k in ["case_id","method","hit_gold","context_chars"]} for r in results]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
