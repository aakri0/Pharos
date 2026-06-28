from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
from collections import Counter
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlparse

from .db import DB_PATH, STATIC_DIR, get_db
from .rag import (
    RAG_FIELDS,
    rag_bm25_score,
    rag_chunk,
    rag_expand_query,
    rag_field_boosts,
    rag_intent_extras,
    rag_split_sentences,
    rag_tokenize,
)
from .risk import (
    PATIENT_CONTEXT_RULES,
    RISK_ESCALATORS,
    row_to_drug,
    severity_for,
)
from .text import clean_text, compact


# ---------------------------------------------------------------------------
# Deployment knobs (all optional — unset = current local-dev behaviour)
# ---------------------------------------------------------------------------
# When set, every /api/* request must carry an X-API-Key header that matches.
# Lets a public-internet backend stay quiet for casual scrapers without
# adding any real auth infrastructure.
_API_KEY = os.environ.get("PHAROS_API_KEY", "").strip()
# CORS Access-Control-Allow-Origin value. Default "" means no CORS headers
# emitted (same-origin only). Use "*" for fully open or a specific URL for
# locked-down cross-origin (Vercel frontend → HF Space backend).
_ALLOWED_ORIGIN = os.environ.get("PHAROS_ALLOWED_ORIGIN", "").strip()


class NeuroPharmHandler(BaseHTTPRequestHandler):
    server_version = "NeuroPharmDB/1.1"

    # ---- shared CORS / auth helpers --------------------------------------

    def _emit_cors_headers(self) -> None:
        if not _ALLOWED_ORIGIN:
            return
        self.send_header("Access-Control-Allow-Origin", _ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.send_header("Access-Control-Max-Age", "86400")
        # If the browser cached an Origin-less response, make sure it
        # doesn't reuse it when the Origin header changes.
        self.send_header("Vary", "Origin")

    def _api_key_ok(self) -> bool:
        if not _API_KEY:
            return True
        return self.headers.get("X-API-Key", "") == _API_KEY

    def do_OPTIONS(self) -> None:  # noqa: N802 — required name
        self.send_response(204)
        self._emit_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        # API-key gate on every /api/* path. The index page and static assets
        # are always public so the page can load (and prompt the browser for
        # the key via window.PHAROS_API_KEY before making API calls).
        if path.startswith("/api/") and not self._api_key_ok():
            self.send_json({"error": "unauthorized"}, status=401)
            return

        try:
            if path == "/":
                self.send_index()
            elif path.startswith("/static/"):
                self.send_static(path.removeprefix("/static/"))
            elif path == "/api/stats":
                self.send_json(self.stats())
            elif path == "/api/search":
                params = parse_qs(parsed.query)
                self.send_json(self.search(params.get("q", [""])[0]))
            elif path == "/api/options":
                params = parse_qs(parsed.query)
                self.send_json(self.options(params.get("q", [""])[0]))
            elif path == "/api/check":
                params = parse_qs(parsed.query)
                self.send_json(
                    self.check_pair(
                        params.get("drug1", [""])[0],
                        params.get("drug2", [""])[0],
                    )
                )
            elif path == "/api/check-many":
                params = parse_qs(parsed.query)
                self.send_json(self.check_many(params.get("ids", [""])[0]))
            elif path == "/api/ai-insights":
                params = parse_qs(parsed.query)
                self.send_json(self.ai_insights(params.get("ids", [""])[0]))
            elif path == "/api/patient-risk":
                params = parse_qs(parsed.query)
                self.send_json(
                    self.patient_risk(
                        params.get("ids", [""])[0],
                        params.get("contexts", [""])[0],
                    )
                )
            elif path == "/api/similar":
                params = parse_qs(parsed.query)
                self.send_json(self.similar_drugs(params.get("drug", [""])[0]))
            elif path == "/api/rag-query":
                params = parse_qs(parsed.query)
                self.send_json(
                    self.rag_query(
                        params.get("q", [""])[0],
                        params.get("ids", [""])[0],
                    )
                )
            elif path.startswith("/api/drugs/") and path.endswith("/interactions"):
                drug_id = path.removeprefix("/api/drugs/").removesuffix("/interactions").strip("/")
                params = parse_qs(parsed.query)
                self.send_json(self.drug_interactions(drug_id, params.get("q", [""])[0]))
            elif path.startswith("/api/drugs/"):
                drug_id = path.removeprefix("/api/drugs/").strip("/")
                self.send_json(self.drug_detail(drug_id))
            else:
                self.send_error(404, "Not found")
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_index(self) -> None:
        html_doc = (STATIC_DIR / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_doc)))
        self._emit_cors_headers()
        self.end_headers()
        self.wfile.write(html_doc)

    def send_static(self, filename: str) -> None:
        safe_path = (STATIC_DIR / filename).resolve()
        if not str(safe_path).startswith(str(STATIC_DIR.resolve())) or not safe_path.is_file():
            self.send_error(404, "Static file not found")
            return

        content = safe_path.read_bytes()
        mime_type = mimetypes.guess_type(safe_path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self._emit_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._emit_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def stats(self) -> dict:
        with get_db() as db:
            drugs = db.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
            interactions = db.execute("SELECT COUNT(*) FROM drug_interactions").fetchone()[0]
            food = db.execute("SELECT COUNT(*) FROM food_interactions").fetchone()[0]
        return {"drugs": drugs, "interactions": interactions, "foodInteractions": food}

    def search(self, query: str) -> dict:
        q = " ".join(query.strip().split())
        if len(q) < 2:
            return {"results": []}

        prefix = f"{q}%"
        contains = f"%{q}%"
        with get_db() as db:
            rows = db.execute(
                """
                WITH matched AS (
                    SELECT drugbank_id, name, NULL AS matched_synonym, 0 AS rank
                    FROM drugs
                    WHERE name LIKE ?
                    UNION
                    SELECT drugbank_id, name, NULL AS matched_synonym, 1 AS rank
                    FROM drugs
                    WHERE name LIKE ?
                    UNION
                    SELECT d.drugbank_id, d.name, s.synonym AS matched_synonym, 2 AS rank
                    FROM synonyms s
                    JOIN drugs d ON d.drugbank_id = s.drug_id
                    WHERE s.synonym LIKE ?
                )
                SELECT drugbank_id, name, matched_synonym, MIN(rank) AS rank
                FROM matched
                GROUP BY drugbank_id, name
                ORDER BY rank, LENGTH(name), name
                LIMIT 60
                """,
                (prefix, contains, contains),
            ).fetchall()

        return {
            "results": [
                {
                    "id": row["drugbank_id"],
                    "name": row["name"] or row["drugbank_id"],
                    "synonym": row["matched_synonym"],
                }
                for row in rows
            ]
        }

    def options(self, query: str) -> dict:
        q = " ".join(query.strip().split())
        if q:
            return self.search(q)

        preferred = [
            "Acetylsalicylic acid",
            "Warfarin",
            "Apixaban",
            "Metformin",
            "Atorvastatin",
            "Ibuprofen",
            "Acetaminophen",
            "Amoxicillin",
            "Omeprazole",
            "Clopidogrel",
            "Simvastatin",
            "Lisinopril",
            "Amlodipine",
            "Prednisone",
            "Fluoxetine",
            "Sertraline",
            "Ciprofloxacin",
            "Levothyroxine",
        ]

        with get_db() as db:
            preferred_rows = db.execute(
                """
                SELECT drugbank_id, name, NULL AS matched_synonym
                FROM drugs
                WHERE name IN ({})
                """.format(",".join("?" for _ in preferred)),
                preferred,
            ).fetchall()
            preferred_by_name = {row["name"]: row for row in preferred_rows}
            rows = [preferred_by_name[name] for name in preferred if name in preferred_by_name]

            alphabetic_rows = db.execute(
                """
                SELECT drugbank_id, name, NULL AS matched_synonym
                FROM drugs
                WHERE name IS NOT NULL
                  AND TRIM(name) != ''
                  AND name NOT IN ({})
                ORDER BY name COLLATE NOCASE
                LIMIT 102
                """.format(",".join("?" for _ in preferred)),
                preferred,
            ).fetchall()
            rows.extend(alphabetic_rows)

        return {
            "results": [
                {
                    "id": row["drugbank_id"],
                    "name": row["name"] or row["drugbank_id"],
                    "synonym": row["matched_synonym"],
                }
                for row in rows
            ]
        }

    def check_many(self, raw_ids: str) -> dict:
        ids: list[str] = []
        for drug_id in raw_ids.split(","):
            clean_id = drug_id.strip()
            if clean_id and clean_id not in ids:
                ids.append(clean_id)

        if len(ids) < 2:
            return {"error": "Select at least two drugs to check."}
        if len(ids) > 12:
            return {"error": "Please check 12 drugs or fewer at a time."}

        placeholders = ",".join("?" for _ in ids)
        with get_db() as db:
            drug_rows = db.execute(
                f"""
                SELECT * FROM drugs
                WHERE drugbank_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            drugs_by_id = {row["drugbank_id"]: row for row in drug_rows}

            missing = [drug_id for drug_id in ids if drug_id not in drugs_by_id]
            if missing:
                return {"error": f"Could not find: {', '.join(missing)}"}

            interaction_rows = db.execute(
                f"""
                SELECT drug1_id, drug2_id, description
                FROM drug_interactions
                WHERE drug1_id IN ({placeholders})
                  AND drug2_id IN ({placeholders})
                """,
                [*ids, *ids],
            ).fetchall()

        interactions: dict[frozenset[str], sqlite3.Row] = {}
        for row in interaction_rows:
            key = frozenset((row["drug1_id"], row["drug2_id"]))
            interactions.setdefault(key, row)

        pairs = []
        for index, drug1_id in enumerate(ids):
            for drug2_id in ids[index + 1 :]:
                row = interactions.get(frozenset((drug1_id, drug2_id)))
                drug1 = row_to_drug(drugs_by_id[drug1_id])
                drug2 = row_to_drug(drugs_by_id[drug2_id])
                item = {
                    "drug1": drug1,
                    "drug2": drug2,
                    "found": row is not None,
                }
                if row is not None:
                    level, label = severity_for(row["description"])
                    item["interaction"] = {
                        "description": clean_text(row["description"]),
                        "severity": level,
                        "label": label,
                    }
                pairs.append(item)

        return {
            "drugs": [row_to_drug(drugs_by_id[drug_id]) for drug_id in ids],
            "pairs": pairs,
            "summary": {
                "selected": len(ids),
                "checked": len(pairs),
                "found": sum(1 for pair in pairs if pair["found"]),
            },
        }

    def parsed_ids(self, raw_ids: str, max_ids: int = 12) -> tuple[list[str], str | None]:
        ids: list[str] = []
        for drug_id in raw_ids.split(","):
            clean_id = drug_id.strip()
            if clean_id and clean_id not in ids:
                ids.append(clean_id)
        if len(ids) < 2:
            return ids, "Select at least two drugs."
        if len(ids) > max_ids:
            return ids, f"Please use {max_ids} drugs or fewer."
        return ids, None

    def parsed_contexts(self, raw_contexts: str) -> list[str]:
        contexts = []
        for context in raw_contexts.split(","):
            clean_context = context.strip()
            if clean_context in PATIENT_CONTEXT_RULES and clean_context not in contexts:
                contexts.append(clean_context)
        return contexts

    def evidence_excerpt(self, text: str, terms: tuple[str, ...], limit: int = 220) -> str:
        clean = clean_text(text)
        if not clean:
            return ""
        lower = clean.lower()
        positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
        if not positions:
            return compact(clean, limit)
        start = max(0, min(positions) - 70)
        end = min(len(clean), min(positions) + limit)
        excerpt = clean[start:end].strip()
        if start:
            excerpt = f"...{excerpt}"
        if end < len(clean):
            excerpt = f"{excerpt}..."
        return excerpt

    def risk_level(self, score: int) -> str:
        if score >= 70:
            return "critical"
        if score >= 45:
            return "high"
        if score >= 22:
            return "moderate"
        if score > 0:
            return "low"
        return "none"

    def patient_risk(self, raw_ids: str, raw_contexts: str) -> dict:
        ids, error = self.parsed_ids(raw_ids)
        if error:
            return {"error": error}

        contexts = self.parsed_contexts(raw_contexts)
        if not contexts:
            return {"error": "Select at least one patient context."}

        placeholders = ",".join("?" for _ in ids)
        with get_db() as db:
            drug_rows = db.execute(
                f"""
                SELECT drugbank_id, name, description, indication, pharmacodynamics,
                       mechanism_of_action, toxicity, metabolism, absorption,
                       half_life, route_of_elimination
                FROM drugs
                WHERE drugbank_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            drugs_by_id = {row["drugbank_id"]: row for row in drug_rows}
            if len(drugs_by_id) != len(ids):
                return {"error": "One or more selected drugs could not be found."}

            food_rows = db.execute(
                f"""
                SELECT drug_id, description
                FROM food_interactions
                WHERE drug_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            interaction_rows = db.execute(
                f"""
                SELECT drug1_id, drug2_id, description
                FROM drug_interactions
                WHERE drug1_id IN ({placeholders})
                  AND drug2_id IN ({placeholders})
                """,
                [*ids, *ids],
            ).fetchall()

        field_map = {
            "description": "Description",
            "indication": "Indication",
            "pharmacodynamics": "Pharmacodynamics",
            "mechanism_of_action": "Mechanism",
            "toxicity": "Toxicity",
            "metabolism": "Metabolism",
            "absorption": "Absorption",
            "half_life": "Half-life",
            "route_of_elimination": "Elimination",
        }

        context_results = []
        all_signals = []
        for context in contexts:
            rule = PATIENT_CONTEXT_RULES[context]
            terms = rule["terms"]
            signals = []
            context_points = 0

            for drug_id in ids:
                drug = drugs_by_id[drug_id]
                for field, label in field_map.items():
                    text = clean_text(drug[field])
                    if not text:
                        continue
                    lower = text.lower()
                    matched = [term for term in terms if term in lower]
                    if not matched:
                        continue
                    escalator_points = sum(points for term, points in RISK_ESCALATORS.items() if term in lower)
                    points = min(rule["points"] + escalator_points, 24)
                    signal = {
                        "drugId": drug_id,
                        "drugName": drug["name"] or drug_id,
                        "source": label,
                        "matched": matched[:4],
                        "excerpt": self.evidence_excerpt(text, terms),
                        "points": points,
                    }
                    signals.append(signal)
                    context_points += points

            for row in food_rows:
                text = clean_text(row["description"])
                lower = text.lower()
                matched = [term for term in terms if term in lower]
                if not matched:
                    continue
                drug = drugs_by_id[row["drug_id"]]
                points = min(rule["points"] + 3, 18)
                signal = {
                    "drugId": row["drug_id"],
                    "drugName": drug["name"] or row["drug_id"],
                    "source": "Food interaction",
                    "matched": matched[:4],
                    "excerpt": self.evidence_excerpt(text, terms),
                    "points": points,
                }
                signals.append(signal)
                context_points += points

            unique_interactions: dict[frozenset[str], sqlite3.Row] = {}
            for row in interaction_rows:
                unique_interactions.setdefault(frozenset((row["drug1_id"], row["drug2_id"])), row)

            for row in unique_interactions.values():
                text = clean_text(row["description"])
                lower = text.lower()
                matched = [term for term in terms if term in lower]
                if not matched:
                    continue
                severity, label = severity_for(text)
                points = rule["points"] + (12 if severity == "high" else 6 if severity == "moderate" else 3)
                signal = {
                    "drugId": f"{row['drug1_id']}+{row['drug2_id']}",
                    "drugName": f"{drugs_by_id[row['drug1_id']]['name']} + {drugs_by_id[row['drug2_id']]['name']}",
                    "source": f"Pair interaction · {label}",
                    "matched": matched[:4],
                    "excerpt": self.evidence_excerpt(text, terms),
                    "points": min(points, 28),
                }
                signals.append(signal)
                context_points += signal["points"]

            signals.sort(key=lambda item: (-item["points"], item["drugName"], item["source"]))
            score = min(100, context_points)
            context_result = {
                "id": context,
                "label": rule["label"],
                "score": score,
                "level": self.risk_level(score),
                "monitor": rule["monitor"],
                "signalCount": len(signals),
                "signals": signals[:8],
            }
            context_results.append(context_result)
            all_signals.extend(signals)

        context_results.sort(key=lambda item: (-item["score"], item["label"]))
        overall_score = min(100, sum(item["score"] for item in context_results) // max(1, len(context_results)) + min(20, len(all_signals) * 2))
        top_context = context_results[0] if context_results else None
        explanation = [
            "The model scans local DrugBank text fields for patient-context terms, then attaches evidence snippets from the exact fields that matched.",
            "Signals from interaction text and high-risk language such as contraindicated, fatal, severe, toxicity, bleeding, and risk increase the score.",
            "The score is explainable decision support from local database text, not a diagnosis or a replacement for clinical judgment.",
        ]
        if top_context:
            explanation.insert(0, f"{top_context['label']} is the leading context because it produced {top_context['signalCount']} matched evidence signal(s).")

        return {
            "mode": "Explainable local patient-context risk scorer",
            "selectedContexts": [
                {"id": context, "label": PATIENT_CONTEXT_RULES[context]["label"]}
                for context in contexts
            ],
            "overall": {
                "score": overall_score,
                "level": self.risk_level(overall_score),
                "label": self.risk_level(overall_score).replace("_", " ").title(),
            },
            "contexts": context_results,
            "explanation": explanation,
            "method": {
                "fieldsScanned": list(field_map.values()) + ["Food interaction", "Pair interaction"],
                "escalators": list(RISK_ESCALATORS.keys()),
                "scoreRange": "0-100",
            },
        }

    def ai_insights(self, raw_ids: str) -> dict:
        ids, error = self.parsed_ids(raw_ids)
        if error:
            return {"error": error}

        placeholders = ",".join("?" for _ in ids)
        with get_db() as db:
            drug_rows = db.execute(
                f"SELECT drugbank_id, name FROM drugs WHERE drugbank_id IN ({placeholders})",
                ids,
            ).fetchall()
            drugs_by_id = {row["drugbank_id"]: row["name"] or row["drugbank_id"] for row in drug_rows}
            if len(drugs_by_id) != len(ids):
                return {"error": "One or more selected drugs could not be found."}

            interaction_rows = db.execute(
                f"""
                SELECT drug1_id, drug2_id, description
                FROM drug_interactions
                WHERE drug1_id IN ({placeholders})
                  AND drug2_id IN ({placeholders})
                """,
                [*ids, *ids],
            ).fetchall()
            food_rows = db.execute(
                f"""
                SELECT drug_id, description
                FROM food_interactions
                WHERE drug_id IN ({placeholders})
                ORDER BY drug_id
                """,
                ids,
            ).fetchall()
            category_rows = db.execute(
                f"""
                SELECT drug_id, category AS item
                FROM categories
                WHERE drug_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            target_rows = db.execute(
                f"""
                SELECT drug_id, name AS item
                FROM targets
                WHERE drug_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            enzyme_rows = db.execute(
                f"""
                SELECT drug_id, name AS item
                FROM enzymes
                WHERE drug_id IN ({placeholders})
                """,
                ids,
            ).fetchall()

        interaction_by_pair: dict[frozenset[str], sqlite3.Row] = {}
        for row in interaction_rows:
            interaction_by_pair.setdefault(frozenset((row["drug1_id"], row["drug2_id"])), row)

        edges = []
        found_edges = []
        high_count = 0
        for index, drug1_id in enumerate(ids):
            for drug2_id in ids[index + 1 :]:
                row = interaction_by_pair.get(frozenset((drug1_id, drug2_id)))
                edge = {
                    "source": drug1_id,
                    "target": drug2_id,
                    "sourceName": drugs_by_id[drug1_id],
                    "targetName": drugs_by_id[drug2_id],
                    "found": row is not None,
                    "severity": "none",
                    "label": "No listed interaction",
                    "description": "",
                }
                if row is not None:
                    severity, label = severity_for(row["description"])
                    edge.update(
                        {
                            "found": True,
                            "severity": severity,
                            "label": label,
                            "description": clean_text(row["description"]),
                        }
                    )
                    found_edges.append(edge)
                    if severity == "high":
                        high_count += 1
                edges.append(edge)

        food_by_drug: dict[str, list[str]] = {drug_id: [] for drug_id in ids}
        for row in food_rows:
            food_by_drug[row["drug_id"]].append(clean_text(row["description"]))

        def shared_items(rows: list[sqlite3.Row], limit: int = 8) -> list[dict]:
            item_map: dict[str, set[str]] = {}
            for row in rows:
                item = clean_text(row["item"])
                if item:
                    item_map.setdefault(item, set()).add(row["drug_id"])
            shared = [
                {
                    "name": item,
                    "drugs": [drugs_by_id[drug_id] for drug_id in drug_ids if drug_id in drugs_by_id],
                }
                for item, drug_ids in item_map.items()
                if len(drug_ids) > 1
            ]
            shared.sort(key=lambda item: (-len(item["drugs"]), item["name"].lower()))
            return shared[:limit]

        total_pairs = (len(ids) * (len(ids) - 1)) // 2
        food_count = sum(len(items) for items in food_by_drug.values())
        summary = []
        if found_edges:
            summary.append(f"{len(found_edges)} of {total_pairs} selected drug pairs have listed DrugBank interactions.")
        else:
            summary.append(f"No listed DrugBank interaction rows were found among the {total_pairs} selected pairs.")
        if high_count:
            summary.append(f"{high_count} interaction(s) contain high-attention risk language such as bleeding, hemorrhage, toxicity, or contraindication.")
        else:
            summary.append("No high-attention keyword pattern was detected in the selected interaction descriptions.")
        if food_count:
            summary.append(f"{food_count} food or supplement warning(s) were found for the selected drugs.")
        if len(shared_items(target_rows, 3)) or len(shared_items(enzyme_rows, 3)):
            summary.append("Shared target or enzyme signals suggest possible mechanistic overlap worth reviewing.")
        else:
            summary.append("No shared target/enzyme overlap was detected from the available structured fields.")

        return {
            "mode": "Local AI-style risk summarizer",
            "nodes": [{"id": drug_id, "name": drugs_by_id[drug_id]} for drug_id in ids],
            "edges": edges,
            "summary": summary,
            "foodWarnings": [
                {
                    "drugId": drug_id,
                    "drugName": drugs_by_id[drug_id],
                    "warnings": warnings,
                }
                for drug_id, warnings in food_by_drug.items()
                if warnings
            ],
            "shared": {
                "categories": shared_items(category_rows),
                "targets": shared_items(target_rows),
                "enzymes": shared_items(enzyme_rows),
            },
            "topInteractions": found_edges[:6],
        }

    def rag_query(self, raw_query: str, raw_ids: str) -> dict:
        query = " ".join((raw_query or "").strip().split())
        if not query:
            return {"error": "Ask a clinical question (e.g. \"Which drugs raise bleeding risk?\")."}
        if len(query) > 400:
            return {"error": "Question is too long. Please keep it under 400 characters."}

        original_query_tokens = rag_tokenize(query)
        if not original_query_tokens:
            return {"error": "Question needs at least one searchable term."}

        ids: list[str] = []
        for drug_id in (raw_ids or "").split(","):
            clean_id = drug_id.strip()
            if clean_id and clean_id not in ids:
                ids.append(clean_id)
        if not ids:
            return {"error": "Select at least one drug so RAG has a corpus to retrieve from."}
        if len(ids) > 12:
            return {"error": "Please limit RAG to 12 drugs or fewer."}

        placeholders = ",".join("?" for _ in ids)
        field_columns = ",".join(name for name, _ in RAG_FIELDS)
        with get_db() as db:
            drug_rows = db.execute(
                f"""
                SELECT drugbank_id, name, {field_columns}
                FROM drugs
                WHERE drugbank_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            drugs_by_id = {row["drugbank_id"]: row for row in drug_rows}
            missing = [drug_id for drug_id in ids if drug_id not in drugs_by_id]
            if missing:
                return {"error": f"Could not find: {', '.join(missing)}"}

            food_rows = db.execute(
                f"""
                SELECT drug_id, description
                FROM food_interactions
                WHERE drug_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            interaction_rows = db.execute(
                f"""
                SELECT drug1_id, drug2_id, description
                FROM drug_interactions
                WHERE drug1_id IN ({placeholders})
                  AND drug2_id IN ({placeholders})
                """,
                [*ids, *ids],
            ).fetchall()

        chunks: list[dict] = []

        def push_chunk(drug_id: str, drug_name: str, field_label: str, text: str) -> None:
            label_tokens = rag_tokenize(field_label)
            for piece in rag_chunk(text):
                body_tokens = rag_tokenize(piece)
                # Make each chunk searchable by its field name too. Without this,
                # a chunk whose body is just "12.7±8.55h" (Apixaban half-life)
                # could never be retrieved by a query like "half life".
                seen = set(body_tokens)
                merged = list(body_tokens)
                for tok in label_tokens:
                    if tok not in seen:
                        merged.append(tok)
                        seen.add(tok)
                if not merged:
                    continue
                chunks.append(
                    {
                        "drugId": drug_id,
                        "drugName": drug_name,
                        "field": field_label,
                        "text": piece,
                        "tokens": merged,
                    }
                )

        for drug_id in ids:
            row = drugs_by_id[drug_id]
            drug_name = row["name"] or drug_id
            for field_name, field_label in RAG_FIELDS:
                push_chunk(drug_id, drug_name, field_label, clean_text(row[field_name]))

        for row in food_rows:
            drug = drugs_by_id[row["drug_id"]]
            push_chunk(
                row["drug_id"],
                drug["name"] or row["drug_id"],
                "Food interaction",
                clean_text(row["description"]),
            )

        seen_pairs: set[frozenset[str]] = set()
        for row in interaction_rows:
            key = frozenset((row["drug1_id"], row["drug2_id"]))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            drug1 = drugs_by_id[row["drug1_id"]]
            drug2 = drugs_by_id[row["drug2_id"]]
            label = f"{drug1['name'] or row['drug1_id']} + {drug2['name'] or row['drug2_id']}"
            push_chunk(row["drug1_id"], label, "Pair interaction", clean_text(row["description"]))

        if not chunks:
            return {
                "error": "No DrugBank text was available to retrieve from for the selected drugs.",
            }

        total_docs = len(chunks)
        avg_doc_len = sum(len(chunk["tokens"]) for chunk in chunks) / total_docs
        doc_freqs: Counter = Counter()
        for chunk in chunks:
            for term in set(chunk["tokens"]):
                doc_freqs[term] += 1

        query_lower = query.lower()
        intent_extras = rag_intent_extras(original_query_tokens, query_lower, len(ids))
        query_tokens = rag_expand_query(original_query_tokens)
        for term in intent_extras:
            if term not in query_tokens:
                query_tokens.append(term)
        field_boosts = rag_field_boosts(original_query_tokens, query_lower, len(ids))

        scored = []
        for chunk in chunks:
            base = rag_bm25_score(query_tokens, chunk["tokens"], doc_freqs, avg_doc_len, total_docs)
            if base <= 0:
                continue
            multiplier = field_boosts.get(chunk["field"], 1.0)
            scored.append((base * multiplier, chunk))

        # Fallback: when BM25 returned no matches, surface a Description chunk
        # per selected drug so the user still gets a useful summary instead of
        # a dead end. Marked with tiny scores so any real future match will
        # still outrank them.
        fallback_used = False
        if not scored:
            seen_drugs: set[str] = set()
            fallback = []
            for chunk in chunks:
                if chunk["field"] == "Description" and chunk["drugId"] not in seen_drugs:
                    fallback.append((0.01, chunk))
                    seen_drugs.add(chunk["drugId"])
            if fallback:
                scored = fallback
                fallback_used = True

        if not scored:
            return {
                "query": query,
                "answer": "RAG retrieval found no DrugBank text matching that question for the selected drugs. Try rephrasing or add related drugs.",
                "citations": [],
                "retrieved": 0,
                "corpusSize": total_docs,
                "mode": "Local RAG (BM25 retrieval + extractive synthesis)",
                "queryTerms": sorted(set(original_query_tokens)),
                "expandedTerms": sorted(set(query_tokens) - set(original_query_tokens)),
                "fieldBoosts": field_boosts,
            }

        scored.sort(key=lambda item: (-item[0], item[1]["drugName"]))

        # Pair-intent guarantee: when interaction intent is detected and >=2
        # drugs are selected, ensure the best pair-interaction chunk lands at
        # position #1 even if other fields outscore it on raw BM25. Without
        # this, a single overlapping token like "interaction" on a long pair
        # text can lose to 4-5 overlapping tokens on a "Take with food" chunk.
        pair_intent_active = field_boosts.get("Pair interaction", 1.0) >= 2.0
        if pair_intent_active and len(ids) >= 2 and scored:
            for index, (_score, chunk) in enumerate(scored):
                if chunk["field"] == "Pair interaction":
                    if index != 0:
                        promoted = scored.pop(index)
                        # Re-score so the promoted chunk's relative position
                        # is preserved in the relevance display below.
                        scored.insert(0, (scored[0][0] * 1.01, promoted[1]))
                    break

        top = scored[: min(6, len(scored))]
        max_score = top[0][0] or 1.0

        query_term_set = set(query_tokens)

        def best_sentence(text: str) -> str:
            sentences = rag_split_sentences(text) or [text]
            best = sentences[0]
            best_overlap = -1
            for sentence in sentences:
                overlap = sum(1 for tok in set(rag_tokenize(sentence)) if tok in query_term_set)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best = sentence
            return best.strip()

        citations = []
        bullets = []
        seen_evidence: set[tuple[str, str, str]] = set()
        for score, chunk in top:
            evidence_sentence = best_sentence(chunk["text"])
            key = (chunk["drugId"], chunk["field"], evidence_sentence[:80])
            if key in seen_evidence:
                continue
            seen_evidence.add(key)
            citations.append(
                {
                    "drugId": chunk["drugId"],
                    "drugName": chunk["drugName"],
                    "field": chunk["field"],
                    "excerpt": self.evidence_excerpt(chunk["text"], tuple(query_term_set), limit=260),
                    "evidence": compact(evidence_sentence, 260),
                    "score": round(score, 3),
                    "relevance": round(score / max_score, 3),
                }
            )
            bullets.append(f"{chunk['drugName']} ({chunk['field']}): {compact(evidence_sentence, 220)}")

        top_drugs = []
        for citation in citations:
            if citation["drugName"] not in top_drugs:
                top_drugs.append(citation["drugName"])
        drug_list = ", ".join(top_drugs[:4]) if top_drugs else "the selected drugs"

        answer_lines = [
            f"Based on DrugBank evidence retrieved for {drug_list}:",
        ]
        for index, bullet in enumerate(bullets[:4], start=1):
            answer_lines.append(f"{index}. {bullet}")
        answer_lines.append(
            "This answer is extractive: it surfaces only the highest-scoring sentences from local DrugBank fields, with citations below."
        )

        return {
            "query": query,
            "mode": "Local RAG (BM25 retrieval + extractive synthesis)",
            "answer": "\n".join(answer_lines),
            "citations": citations,
            "retrieved": len(scored),
            "corpusSize": total_docs,
            "queryTerms": sorted(set(original_query_tokens)),
            "expandedTerms": sorted(set(query_tokens) - set(original_query_tokens)),
            "fieldBoosts": field_boosts,
            "fallback": fallback_used,
        }

    def check_pair(self, drug1: str, drug2: str) -> dict:
        if not drug1 or not drug2:
            return {"error": "Select two drugs to check."}
        if drug1 == drug2:
            return {"error": "Choose two different drugs."}

        with get_db() as db:
            d1 = db.execute("SELECT * FROM drugs WHERE drugbank_id = ?", (drug1,)).fetchone()
            d2 = db.execute("SELECT * FROM drugs WHERE drugbank_id = ?", (drug2,)).fetchone()
            interaction = db.execute(
                """
                SELECT * FROM drug_interactions
                WHERE (drug1_id = ? AND drug2_id = ?)
                   OR (drug1_id = ? AND drug2_id = ?)
                LIMIT 1
                """,
                (drug1, drug2, drug2, drug1),
            ).fetchone()

        if d1 is None or d2 is None:
            return {"error": "One or both selected drugs were not found."}

        result = {
            "drug1": row_to_drug(d1),
            "drug2": row_to_drug(d2),
            "found": interaction is not None,
        }
        if interaction is not None:
            level, label = severity_for(interaction["description"])
            result["interaction"] = {
                "description": clean_text(interaction["description"]),
                "severity": level,
                "label": label,
            }
        return result

    def similar_drugs(self, drug_id: str) -> dict:
        if not drug_id:
            return {"error": "Choose a drug first."}

        with get_db() as db:
            drug = db.execute("SELECT drugbank_id, name FROM drugs WHERE drugbank_id = ?", (drug_id,)).fetchone()
            if drug is None:
                return {"error": "Drug not found."}

            category_rows = db.execute(
                "SELECT DISTINCT category AS item FROM categories WHERE drug_id = ? AND category IS NOT NULL",
                (drug_id,),
            ).fetchall()
            enzyme_rows = db.execute(
                "SELECT DISTINCT name AS item FROM enzymes WHERE drug_id = ? AND name IS NOT NULL",
                (drug_id,),
            ).fetchall()
            target_rows = db.execute(
                "SELECT DISTINCT name AS item FROM targets WHERE drug_id = ? AND name IS NOT NULL",
                (drug_id,),
            ).fetchall()

            categories = [row["item"] for row in category_rows if clean_text(row["item"])]
            enzymes = [row["item"] for row in enzyme_rows if clean_text(row["item"])]
            targets = [row["item"] for row in target_rows if clean_text(row["item"])]

            candidates: dict[str, dict] = {}

            def collect(table: str, column: str, items: list[str], weight: int, label: str) -> None:
                if not items:
                    return
                placeholders = ",".join("?" for _ in items)
                rows = db.execute(
                    f"""
                    SELECT d.drugbank_id, d.name, COUNT(DISTINCT src.{column}) AS matches
                    FROM {table} src
                    JOIN drugs d ON d.drugbank_id = src.drug_id
                    WHERE src.{column} IN ({placeholders})
                      AND src.drug_id != ?
                      AND d.name IS NOT NULL
                      AND TRIM(d.name) != ''
                    GROUP BY d.drugbank_id, d.name
                    ORDER BY matches DESC, d.name COLLATE NOCASE
                    LIMIT 80
                    """,
                    [*items, drug_id],
                ).fetchall()
                for row in rows:
                    entry = candidates.setdefault(
                        row["drugbank_id"],
                        {
                            "id": row["drugbank_id"],
                            "name": row["name"],
                            "score": 0,
                            "signals": [],
                        },
                    )
                    match_count = int(row["matches"] or 0)
                    entry["score"] += match_count * weight
                    if match_count:
                        entry["signals"].append(f"{match_count} shared {label}")

            collect("categories", "category", categories[:30], 2, "category")
            collect("enzymes", "name", enzymes[:20], 4, "enzyme")
            collect("targets", "name", targets[:20], 5, "target")

        ranked = sorted(candidates.values(), key=lambda item: (-item["score"], item["name"].lower()))[:8]
        return {
            "source": {"id": drug["drugbank_id"], "name": drug["name"] or drug["drugbank_id"]},
            "results": ranked,
        }

    def drug_detail(self, drug_id: str) -> dict:
        with get_db() as db:
            drug = db.execute("SELECT * FROM drugs WHERE drugbank_id = ?", (drug_id,)).fetchone()
            if drug is None:
                return {"error": "Drug not found."}

            categories = db.execute(
                "SELECT category FROM categories WHERE drug_id = ? ORDER BY category LIMIT 10",
                (drug_id,),
            ).fetchall()
            food = db.execute(
                "SELECT description FROM food_interactions WHERE drug_id = ? LIMIT 8",
                (drug_id,),
            ).fetchall()
            targets = db.execute(
                "SELECT name, organism, action FROM targets WHERE drug_id = ? LIMIT 8",
                (drug_id,),
            ).fetchall()
            enzymes = db.execute(
                "SELECT name, organism FROM enzymes WHERE drug_id = ? LIMIT 8",
                (drug_id,),
            ).fetchall()
            carriers = db.execute(
                "SELECT name FROM carriers WHERE drug_id = ? LIMIT 8",
                (drug_id,),
            ).fetchall()
            transporters = db.execute(
                "SELECT name FROM transporters WHERE drug_id = ? LIMIT 8",
                (drug_id,),
            ).fetchall()
            products = db.execute(
                """
                SELECT name, manufacturer, dosage_form, route
                FROM products
                WHERE drug_id = ?
                LIMIT 8
                """,
                (drug_id,),
            ).fetchall()
            dosages = db.execute(
                "SELECT form, route, strength FROM dosages WHERE drug_id = ? LIMIT 8",
                (drug_id,),
            ).fetchall()
            interaction_count = db.execute(
                """
                SELECT COUNT(*) FROM drug_interactions
                WHERE drug1_id = ? OR drug2_id = ?
                """,
                (drug_id, drug_id),
            ).fetchone()[0]

        return {
            "drug": row_to_drug(drug),
            "categories": [row["category"] for row in categories],
            "foodInteractions": [clean_text(row["description"]) for row in food],
            "targets": [
                {
                    "name": clean_text(row["name"]),
                    "organism": clean_text(row["organism"]),
                    "action": clean_text(row["action"]),
                }
                for row in targets
            ],
            "enzymes": [
                {
                    "name": clean_text(row["name"]),
                    "organism": clean_text(row["organism"]),
                }
                for row in enzymes
            ],
            "carriers": [clean_text(row["name"]) for row in carriers],
            "transporters": [clean_text(row["name"]) for row in transporters],
            "products": [
                {
                    "name": clean_text(row["name"]),
                    "manufacturer": clean_text(row["manufacturer"]),
                    "form": clean_text(row["dosage_form"]),
                    "route": clean_text(row["route"]),
                }
                for row in products
            ],
            "dosages": [
                {
                    "form": clean_text(row["form"]),
                    "route": clean_text(row["route"]),
                    "strength": clean_text(row["strength"]),
                }
                for row in dosages
            ],
            "interactionCount": interaction_count,
        }

    def drug_interactions(self, drug_id: str, query: str) -> dict:
        q = " ".join(query.strip().split())
        values: list[str] = [drug_id, drug_id]
        name_filter = ""
        if q:
            name_filter = "AND other.name LIKE ?"
            values.append(f"%{q}%")

        with get_db() as db:
            rows = db.execute(
                f"""
                WITH paired AS (
                    SELECT drug2_id AS other_id, description
                    FROM drug_interactions
                    WHERE drug1_id = ?
                    UNION
                    SELECT drug1_id AS other_id, description
                    FROM drug_interactions
                    WHERE drug2_id = ?
                )
                SELECT DISTINCT
                    other.drugbank_id AS id,
                    other.name AS name,
                    paired.description AS description
                FROM paired
                JOIN drugs other ON other.drugbank_id = paired.other_id
                WHERE 1 = 1
                {name_filter}
                ORDER BY other.name
                LIMIT 50
                """,
                values,
            ).fetchall()

        return {
            "results": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": clean_text(row["description"]),
                    "severity": severity_for(row["description"])[0],
                    "label": severity_for(row["description"])[1],
                }
                for row in rows
            ]
        }


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    port = int(os.environ.get("PORT", "8000"))
    # Default to loopback for local dev safety. Containers should set
    # PHAROS_HOST=0.0.0.0 so the orchestrator can reach the port.
    host = os.environ.get("PHAROS_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), NeuroPharmHandler)
    print(f"NeuroPharmDB running at http://{host}:{port}")
    if _API_KEY:
        print("  API-key auth: ENABLED (X-API-Key header required on /api/*)")
    if _ALLOWED_ORIGIN:
        print(f"  CORS Access-Control-Allow-Origin: {_ALLOWED_ORIGIN}")
    server.serve_forever()
