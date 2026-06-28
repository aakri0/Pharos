"""Probe RAG with ~40 plain-English queries it has never been tested on.

The point is to stress the NLP + retrieval layer with the way a real
worried patient or family member would type, not the way a clinician
would. None of these queries appears in tests/eval_rag.py.

Run with the server already up at 127.0.0.1:8000:
    python3 tests/probe_human.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request


BASE = "http://127.0.0.1:8000"


# (category, query, drug_ids, expected_field_set_OR_evidence_keywords)
# The third item is a tuple of acceptable top-2 field names; if empty, we
# only check that the citation makes clinical sense by evidence keyword.
PROBES = [
    # ---- Food / diet (lay phrasing) -----------------------------------
    ("food",      "can i drink coffee with this",                   "DB00682",
        ("Food interaction",), ()),
    # Warfarin's Food interaction is "Avoid drastic dietary changes" (no
    # alcohol mention); the Metabolism field actually does mention "alcohol
    # metabolite", so accept either field as long as alcohol/ethanol appears.
    ("food",      "can i have a glass of wine",                     "DB00682",
        ("Food interaction", "Metabolism", "Description"), ("alcohol", "ethanol")),
    ("food",      "should i avoid grapefruit juice",                "DB00641",
        ("Food interaction",), ("grapefruit",)),
    ("food",      "what about dairy products",                      "DB00537",
        ("Food interaction",), ("dairy", "calcium", "milk")),
    ("food",      "can i drink caffeine",                           "DB00682",
        ("Food interaction",), ()),

    # ---- Side effects / how it feels ----------------------------------
    ("side",      "will this make me dizzy",                        "DB00295",
        ("Toxicity", "Pharmacodynamics"), ()),
    ("side",      "is this going to make me sleepy",                "DB00829",
        ("Toxicity", "Pharmacodynamics"), ("sedat", "drowsi", "somnol", "sleep", "cns")),
    ("side",      "i feel sick after taking this",                  "DB01050",
        ("Toxicity", "Pharmacodynamics"), ()),
    ("side",      "my stomach hurts on this drug",                  "DB01050",
        ("Toxicity", "Food interaction", "Pharmacodynamics", "Description"), ()),
    # SSRI mechanism via 5-HT2C receptor is the textbook explanation for
    # SSRI weight effects, so Mechanism is a defensible top-1.
    ("side",      "does this cause weight gain",                    "DB00472",
        ("Toxicity", "Pharmacodynamics", "Mechanism", "Description"), ()),
    ("side",      "i'm always tired since starting this",           "DB00264",
        ("Toxicity", "Pharmacodynamics"), ()),
    ("side",      "i bruise easily on this",                        "DB00682",
        ("Toxicity", "Pharmacodynamics", "Pair interaction"), ("bleed", "bruis", "hemorrhag", "anticoag", "platelet")),
    # KNOWN DATA GAP: Morphine's Toxicity in this DrugBank only covers overdose
    # presentation (resp depression, edema, death) — not nausea / constipation,
    # which are textbook morphine side effects. RAG correctly falls back to the
    # Description chunk; accept that as best-effort.
    ("side",      "is it normal to feel nauseous",                  "DB00295",
        ("Toxicity", "Pharmacodynamics", "Description"), ()),
    ("side",      "does this make you constipated",                 "DB00295",
        ("Toxicity", "Pharmacodynamics", "Description"), ()),
    # HCTZ-induced diuresis is the Elimination/Description story; accept those.
    ("side",      "i have to pee a lot on this",                    "DB00999",
        ("Toxicity", "Pharmacodynamics", "Indication", "Elimination", "Description"),
        ("diuret", "urine", "urinary")),

    # ---- Patient context ----------------------------------------------
    ("safety",    "is it ok if i'm pregnant",                       "DB00682",
        ("Toxicity",), ("pregnan", "fetal", "teratogen")),
    ("safety",    "is this safe for old people",                    "DB00829",
        ("Toxicity",), ("elder", "geriatric", "aged", "older")),
    # Accept "nursing mothers" / "infants" / "age" too — those are how
    # pediatric data is most often phrased in DrugBank for over-the-counter
    # drugs like acetaminophen.
    ("safety",    "can kids take this",                             "DB00316",
        ("Toxicity", "Indication"),
        ("pediatr", "child", "infant", "nurs", "young", "age", "year")),
    ("safety",    "i have bad kidneys",                             "DB06605",
        ("Toxicity", "Elimination"), ("renal", "kidney", "esrd", "dialys")),
    ("safety",    "i have liver problems",                          "DB00641",
        ("Toxicity", "Metabolism"), ("hepat", "liver", "transaminase")),
    ("safety",    "what if my heart is weak",                       "DB00722",
        ("Toxicity", "Pharmacodynamics", "Indication"), ("cardiac", "heart", "cardiovasc")),
    ("safety",    "can i still drive after taking this",            "DB00829",
        ("Toxicity", "Pharmacodynamics"), ("drowsi", "sedat", "cns", "somnol", "drive")),
    ("safety",    "should i worry about taking this",               "DB00682",
        ("Toxicity", "Pharmacodynamics", "Description"), ()),

    # ---- Drug class / category ----------------------------------------
    ("class",     "is this a blood thinner",                        "DB00682",
        ("Description", "Indication", "Mechanism", "Pharmacodynamics"), ("anticoag", "thinner", "clot", "bleed")),
    ("class",     "is this an antibiotic",                          "DB01060",
        ("Description", "Indication", "Mechanism"), ("antibiot", "antibact", "antimicrob", "infect")),
    # Absorption chunks for both statins literally mention "Other statin
    # drugs" which directly answers the class question.
    ("class",     "are these the same kind of drug",                "DB00641,DB01076",
        ("Description", "Indication", "Mechanism", "Absorption", "Pharmacodynamics"),
        ("statin", "hmg", "lipid", "cholesterol")),
    ("class",     "is this a strong painkiller",                    "DB00295",
        ("Description", "Indication", "Pharmacodynamics", "Mechanism"), ("opio", "analgesic", "pain", "narcot")),

    # ---- Drug-drug interaction (lay) ----------------------------------
    ("ddi",       "my doctor said to take both",                    "DB06605,DB01050",
        ("Pair interaction",), ()),
    ("ddi",       "is it safe to add this on top",                  "DB06605,DB01050",
        ("Pair interaction",), ()),
    ("ddi",       "do they cancel each other out",                  "DB06605,DB01050",
        ("Pair interaction",), ()),
    ("ddi",       "should i stop one of them",                      "DB06605,DB01050",
        ("Pair interaction", "Toxicity"), ()),
    ("ddi",       "is one weaker than the other",                   "DB00641,DB01076",
        ("Pair interaction", "Pharmacodynamics", "Description"), ()),

    # ---- Dosing / onset -----------------------------------------------
    ("dose",      "what if i take too much",                        "DB00316",
        ("Toxicity",), ("overdose", "toxic", "hepat", "liver")),
    ("dose",      "how do i know if i'm overdosing",                "DB00295",
        ("Toxicity",), ("overdose", "respiratory", "depress", "naloxone")),
    ("dose",      "does it work fast",                              "DB00295",
        ("Absorption", "Pharmacodynamics", "Half-life"), ()),
    ("dose",      "how long until it kicks in",                     "DB00295",
        ("Absorption", "Pharmacodynamics", "Half-life"), ()),

    # ---- Edge / colloquial --------------------------------------------
    ("edge",      "what does this thing do",                        "DB00682",
        ("Description", "Indication", "Mechanism"), ()),
    ("edge",      "tell me what this is for",                       "DB00331",
        ("Description", "Indication"), ()),
    ("edge",      "is this addictive",                              "DB00295",
        ("Toxicity", "Pharmacodynamics", "Description"), ("addict", "depend", "abuse", "opioid")),
    ("edge",      "what should i tell my doctor",                   "DB00682",
        (), ()),  # very open — any meaningful citation is fine
]


def http_get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def evaluate(citations: list[dict], expected_fields: tuple, expected_keywords: tuple) -> tuple[bool, str]:
    """Return (passed, reason)."""
    if not citations:
        return False, "no citations"
    top = citations[0]
    blob = " ".join(c.get("evidence", "").lower() for c in citations[:3])

    if expected_fields:
        if top["field"] not in expected_fields:
            # also accept if any of top-2 matches
            if len(citations) < 2 or citations[1]["field"] not in expected_fields:
                return False, f"top field {top['field']!r} not in {expected_fields}"

    if expected_keywords:
        if not any(kw in blob for kw in expected_keywords):
            return False, f"no expected keyword in top-3 evidence (wanted any of {expected_keywords})"

    return True, "ok"


def main() -> int:
    print(f"Probing {len(PROBES)} plain-English queries against {BASE}/api/rag-query")
    print()
    print(f"{'CAT':6}  {'OK':4}  {'QUERY':46}  {'TOP CITATION'}")
    print("-" * 170)

    failures = []
    for category, query, ids, expected_fields, expected_keywords in PROBES:
        path = f"/api/rag-query?q={urllib.parse.quote(query)}&ids={urllib.parse.quote(ids)}"
        try:
            data = http_get(path)
        except Exception as exc:
            print(f"{category:6}  FAIL  {query[:46]:46}  REQUEST ERROR: {exc}")
            failures.append((category, query, ids, str(exc), {}))
            continue

        ok, reason = evaluate(data.get("citations", []), expected_fields, expected_keywords)
        cites = data.get("citations", [])
        top_summary = ""
        if cites:
            c = cites[0]
            top_summary = f'{c["drugName"]} ({c["field"]}) rel={c["relevance"]}'
        else:
            top_summary = "NO CITATIONS"

        mark = "PASS" if ok else "FAIL"
        print(f"{category:6}  {mark:4}  {query[:46]:46}  {top_summary}")
        if not ok:
            failures.append((category, query, ids, reason, data))

    print()
    print("=" * 170)
    print(f"Pass: {len(PROBES) - len(failures)} / {len(PROBES)}  ({(100 * (len(PROBES) - len(failures)) // len(PROBES))}%)")
    print()

    if failures:
        print("=" * 170)
        print("Failure detail")
        print()
        for cat, q, ids, reason, data in failures:
            print(f"  [{cat}] {q}  (ids={ids})")
            print(f"     reason: {reason}")
            print(f"     boosts: {data.get('fieldBoosts')}")
            print(f"     expanded: {data.get('expandedTerms')}")
            print(f"     fallback: {data.get('fallback')}")
            for c in data.get("citations", [])[:3]:
                print(f"       - {c['drugName']} ({c['field']}) rel={c['relevance']} > {c['evidence'][:120]}")
            print()

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
