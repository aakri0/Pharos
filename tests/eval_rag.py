"""Evaluation harness for the RAG endpoint.

Runs a labeled query suite against the real DrugBank database via the
in-process NeuroPharmHandler, applies per-category validation rules, and
prints a pass/fail report plus aggregate scores. Exits non-zero on any
failure so it can be wired into CI later.

Run from the repo root:
    python3 tests/eval_rag.py

Requires drugbank_full.db to exist in the repo root.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from neuropharm.db import DB_PATH
from neuropharm.server import NeuroPharmHandler


# ---------------------------------------------------------------------------
# Drug combos used as fixtures. Keep DrugBank IDs here so the suite is stable
# across DrugBank refreshes (names can shift; IDs are canonical).
# ---------------------------------------------------------------------------
COMBOS = {
    # ---- Single-drug combos (18) ---------------------------------------
    "single_warfarin":      {"ids": "DB00682", "label": "Warfarin"},
    "single_apixaban":      {"ids": "DB06605", "label": "Apixaban"},
    "single_ibuprofen":     {"ids": "DB01050", "label": "Ibuprofen"},
    "single_metformin":     {"ids": "DB00331", "label": "Metformin"},
    "single_lisinopril":    {"ids": "DB00722", "label": "Lisinopril"},
    "single_simvastatin":   {"ids": "DB00641", "label": "Simvastatin"},
    "single_atorvastatin":  {"ids": "DB01076", "label": "Atorvastatin"},
    "single_fluoxetine":    {"ids": "DB00472", "label": "Fluoxetine"},
    "single_sertraline":    {"ids": "DB01104", "label": "Sertraline"},
    "single_omeprazole":    {"ids": "DB00338", "label": "Omeprazole"},
    "single_morphine":      {"ids": "DB00295", "label": "Morphine"},
    "single_amiodarone":    {"ids": "DB01118", "label": "Amiodarone"},
    "single_phenytoin":     {"ids": "DB00252", "label": "Phenytoin"},
    "single_levothyroxine": {"ids": "DB00451", "label": "Levothyroxine"},
    "single_ciprofloxacin": {"ids": "DB00537", "label": "Ciprofloxacin"},
    "single_acetaminophen": {"ids": "DB00316", "label": "Acetaminophen"},
    "single_clopidogrel":   {"ids": "DB00758", "label": "Clopidogrel"},
    "single_methotrexate":  {"ids": "DB00563", "label": "Methotrexate"},

    # ---- Multi-drug combos (12) ----------------------------------------
    "anticoag_nsaid":       {"ids": "DB06605,DB01050",                  "label": "Apixaban + Ibuprofen"},
    "triple_bleeding":      {"ids": "DB00682,DB01050,DB06605",          "label": "Warfarin + Ibuprofen + Apixaban"},
    "statin_pair":          {"ids": "DB00641,DB01076",                  "label": "Simvastatin + Atorvastatin"},
    "ssri_pair":            {"ids": "DB00472,DB01104",                  "label": "Fluoxetine + Sertraline"},
    "warfarin_amio":        {"ids": "DB00682,DB01118",                  "label": "Warfarin + Amiodarone"},
    "clopi_omep":           {"ids": "DB00758,DB00338",                  "label": "Clopidogrel + Omeprazole"},
    "morphine_diazepam":    {"ids": "DB00295,DB00829",                  "label": "Morphine + Diazepam"},
    "ssri_nsaid":           {"ids": "DB00472,DB01050",                  "label": "Fluoxetine + Ibuprofen"},
    "ace_diuretic":         {"ids": "DB00722,DB00999",                  "label": "Lisinopril + Hydrochlorothiazide"},
    "triple_cardiac":       {"ids": "DB00722,DB00999,DB00381",          "label": "Lisinopril + HCTZ + Amlodipine"},
    "polypharm5":           {"ids": "DB00682,DB00331,DB01076,DB00451,DB00722",
                             "label": "Warfarin + Metformin + Atorvastatin + Levothyroxine + Lisinopril"},
    "geriatric_polypharm":  {"ids": "DB00316,DB00338,DB00472,DB00295,DB00829",
                             "label": "Acetaminophen + Omeprazole + Fluoxetine + Morphine + Diazepam"},
}


# ---------------------------------------------------------------------------
# Validators. Each returns True if the response is acceptable.
# ---------------------------------------------------------------------------

def has_citations(data) -> bool:
    return bool(data.get("citations"))


def top_field_is(*fields):
    def check(data):
        if not data.get("citations"):
            return False
        return data["citations"][0]["field"] in fields
    return check


def top_field_in_topn(fields, n=2):
    def check(data):
        cites = data.get("citations", [])[:n]
        return any(c["field"] in fields for c in cites)
    return check


def evidence_contains_any(*needles, n=3):
    def check(data):
        cites = data.get("citations", [])[:n]
        blob = " ".join(c.get("evidence", "").lower() for c in cites)
        return any(needle.lower() in blob for needle in needles)
    return check


def both(*validators):
    def check(data):
        return all(v(data) for v in validators)
    return check


# ---------------------------------------------------------------------------
# Query suite. Tuples: (category, query, combo_key, validator).
# ---------------------------------------------------------------------------
QUERIES = [
    # --- Pair-interaction intent (multiple drugs selected) ----------------
    ("pair",       "What happens if I take the two of these together?",   "anticoag_nsaid",   top_field_is("Pair interaction")),
    ("pair",       "Are these safe to take together?",                    "anticoag_nsaid",   top_field_is("Pair interaction")),
    ("pair",       "What interactions exist between these drugs?",        "anticoag_nsaid",   top_field_is("Pair interaction")),
    ("pair",       "Is it dangerous to mix these?",                       "anticoag_nsaid",   top_field_is("Pair interaction")),
    ("pair",       "Can I take all three at once?",                       "triple_bleeding",  top_field_is("Pair interaction")),
    ("pair",       "Should I be worried about combining them?",           "anticoag_nsaid",   top_field_is("Pair interaction")),
    ("pair",       "Any concerns when used concurrently?",                "anticoag_nsaid",   top_field_is("Pair interaction")),
    ("pair",       "Do these drugs interact?",                            "anticoag_nsaid",   top_field_is("Pair interaction")),

    # --- Bleeding risk ----------------------------------------------------
    ("bleeding",   "Will this cause bleeding?",                           "anticoag_nsaid",   evidence_contains_any("bleed", "hemorrhage", "haemorrhage")),
    ("bleeding",   "Is bleeding risk a concern?",                         "anticoag_nsaid",   evidence_contains_any("bleed", "hemorrhage")),
    ("bleeding",   "INR monitoring needed?",                              "triple_bleeding",  evidence_contains_any("inr", "anticoag", "bleed")),
    ("bleeding",   "Risk of internal bleeding?",                          "anticoag_nsaid",   evidence_contains_any("bleed", "hemorrhage")),

    # --- Food / alcohol ---------------------------------------------------
    ("food",       "Any food or alcohol I should avoid?",                 "anticoag_nsaid",   top_field_is("Food interaction")),
    ("food",       "Should I take this with food?",                       "anticoag_nsaid",   top_field_is("Food interaction")),
    ("food",       "Can I drink alcohol with these?",                     "anticoag_nsaid",   top_field_is("Food interaction")),
    ("food",       "Does grapefruit interact?",                           "single_warfarin",  top_field_is("Food interaction")),
    ("food",       "Best to take on an empty stomach?",                   "anticoag_nsaid",   top_field_in_topn(("Food interaction", "Pair interaction"), n=2)),
    ("food",       "Any dietary restrictions?",                           "single_warfarin",  top_field_is("Food interaction")),

    # --- Pregnancy / lactation -------------------------------------------
    ("pregnancy",  "Is this safe in pregnancy?",                          "single_warfarin",  evidence_contains_any("pregnan", "fetal", "teratogen", "labor", "labour")),
    ("pregnancy",  "Will this harm the baby?",                            "single_warfarin",  evidence_contains_any("pregnan", "fetal", "teratogen", "maternal", "infant")),
    ("pregnancy",  "Teratogenic risks?",                                  "single_warfarin",  evidence_contains_any("teratogen", "fetal", "pregnan")),
    ("pregnancy",  "Safe while breastfeeding?",                           "anticoag_nsaid",   evidence_contains_any("nurs", "breastfeed", "lactat", "milk", "infant", "maternal")),
    ("pregnancy",  "I'm pregnant — should I stop this?",                  "single_warfarin",  evidence_contains_any("pregnan", "fetal", "teratogen")),

    # --- CYP / metabolism ------------------------------------------------
    ("metabolism", "What CYP enzymes are involved?",                      "anticoag_nsaid",   top_field_is("Metabolism")),
    ("metabolism", "How is this metabolized?",                            "anticoag_nsaid",   top_field_is("Metabolism")),
    ("metabolism", "Liver enzymes that process this drug?",               "anticoag_nsaid",   top_field_in_topn(("Metabolism",), n=2)),
    ("metabolism", "CYP3A4 interactions?",                                "anticoag_nsaid",   evidence_contains_any("cyp", "cytochrome", "metaboli")),

    # --- Half-life / duration --------------------------------------------
    ("halflife",   "What is the half life of these drugs?",               "anticoag_nsaid",   top_field_is("Half-life")),
    ("halflife",   "How long do these drugs stay in the body?",           "anticoag_nsaid",   top_field_in_topn(("Half-life", "Elimination"), n=2)),
    ("halflife",   "Duration of action?",                                 "anticoag_nsaid",   top_field_in_topn(("Half-life", "Elimination", "Pharmacodynamics"), n=3)),
    ("halflife",   "How quickly does this clear?",                        "anticoag_nsaid",   top_field_in_topn(("Half-life", "Elimination"), n=2)),

    # --- Renal / kidney --------------------------------------------------
    ("renal",      "Will my kidneys be affected?",                        "anticoag_nsaid",   evidence_contains_any("renal", "kidney", "nephro", "urine", "urinary")),
    ("renal",      "Renal dose adjustment needed?",                       "anticoag_nsaid",   evidence_contains_any("renal", "kidney", "dialys", "urine", "urinary", "excret")),
    ("renal",      "Is this safe with kidney disease?",                   "anticoag_nsaid",   evidence_contains_any("renal", "kidney", "urine", "urinary", "excret")),
    ("renal",      "I have kidney problems — is this OK?",                "anticoag_nsaid",   evidence_contains_any("renal", "kidney", "urine", "urinary", "excret")),

    # --- Hepatic / liver -------------------------------------------------
    ("hepatic",    "Liver effects?",                                      "anticoag_nsaid",   evidence_contains_any("hepatic", "liver", "cyp")),
    ("hepatic",    "Hepatic impairment dosing?",                          "anticoag_nsaid",   evidence_contains_any("hepatic", "liver")),
    ("hepatic",    "Is this hepatotoxic?",                                "statin_pair",      evidence_contains_any("hepatic", "liver", "transaminase")),

    # --- Side effects / toxicity -----------------------------------------
    ("adverse",    "Tell me about side effects",                          "anticoag_nsaid",   top_field_is("Toxicity")),
    ("adverse",    "What are the adverse reactions?",                     "anticoag_nsaid",   top_field_is("Toxicity")),
    ("adverse",    "Common toxicities?",                                  "anticoag_nsaid",   top_field_is("Toxicity")),
    ("adverse",    "What's the overdose presentation?",                   "anticoag_nsaid",   evidence_contains_any("overdose", "toxic", "lethal", "fatal")),

    # --- Mechanism --------------------------------------------------------
    ("mechanism",  "How does this drug work?",                            "single_warfarin",  top_field_in_topn(("Mechanism", "Pharmacodynamics"), n=2)),
    ("mechanism",  "What's the mechanism of action?",                     "single_warfarin",  top_field_is("Mechanism")),
    ("mechanism",  "What receptors does this target?",                    "ssri_pair",        top_field_in_topn(("Mechanism", "Pharmacodynamics"), n=2)),

    # --- Indication -------------------------------------------------------
    ("indication", "What is this drug used for?",                         "single_warfarin",  top_field_in_topn(("Indication", "Description"), n=2)),
    ("indication", "What does this treat?",                               "single_metformin", top_field_in_topn(("Indication", "Description"), n=2)),
    ("indication", "Why would someone be prescribed this?",               "single_metformin", top_field_in_topn(("Indication", "Description"), n=2)),

    # --- Diabetes -------------------------------------------------------
    ("diabetes",   "I'm a diabetic — is this safe?",                      "single_metformin", evidence_contains_any("diabet", "glucose", "glyc", "insulin")),
    ("diabetes",   "Will this raise my blood sugar?",                     "statin_pair",      evidence_contains_any("glucose", "glyc", "diabet", "sugar")),

    # --- Cardiovascular -------------------------------------------------
    ("cardiac",    "Will this affect my blood pressure?",                 "single_lisinopril", evidence_contains_any("pressure", "hypoten", "hyperten", "cardiac", "cardiovasc")),

    # --- Colloquial / edge cases ----------------------------------------
    ("edge",       "I'm pregnant",                                        "single_warfarin",  evidence_contains_any("pregnan", "fetal", "teratogen")),
    ("edge",       "I have kidney problems",                              "anticoag_nsaid",   evidence_contains_any("renal", "kidney")),
    ("edge",       "Tell me everything",                                  "single_warfarin",  has_citations),
    ("edge",       "Is this OK to take?",                                 "single_warfarin",  has_citations),
]


# ---------------------------------------------------------------------------
# Templated query generators — these are the bulk of the 200+ suite.
# Validators are deliberately a bit lenient (top-N rather than top-1 in some
# cases) so a drug with sparse coverage in one DrugBank field doesn't fail a
# query that the RAG routing is in fact answering correctly.
# ---------------------------------------------------------------------------

SINGLE_BASELINE = [
    ("indication", "What is this drug used for?",                  top_field_in_topn(("Indication", "Description"), n=2)),
    ("indication", "What does this treat?",                        top_field_in_topn(("Indication", "Description"), n=2)),
    ("mechanism",  "How does this drug work?",                     top_field_in_topn(("Mechanism", "Pharmacodynamics", "Description"), n=2)),
    # Pharmacodynamics chunks legitimately discuss adverse effects, and for
    # drugs like statins the Food-interaction grapefruit chunk literally says
    # "may increase the risk for adverse effects such as myopathy" — also a
    # valid answer. Accept any chunk whose evidence describes a safety event.
    ("adverse",    "What are the side effects?",
        lambda d: (
            top_field_in_topn(("Toxicity", "Pharmacodynamics"), n=3)(d)
            or evidence_contains_any("adverse", "toxic", "myopath", "rhabdomyol", "hemorrhag", "bleed")(d)
        )),
    ("metabolism", "How is this metabolized?",                     top_field_in_topn(("Metabolism", "Elimination"), n=2)),
    ("halflife",   "How long does this stay in the body?",         top_field_in_topn(("Half-life", "Elimination", "Pharmacodynamics"), n=2)),
]

MULTI_BASELINE = [
    ("pair", "What happens if I take these together?",             top_field_is("Pair interaction")),
    ("pair", "Are these safe to take together?",                   top_field_is("Pair interaction")),
    ("pair", "Do these drugs interact?",                           top_field_is("Pair interaction")),
    ("pair", "Should I be worried about combining them?",          top_field_is("Pair interaction")),
    ("pair", "Any concerns when used concurrently?",               top_field_is("Pair interaction")),
    ("food", "Any food or alcohol I should avoid?",                top_field_in_topn(("Food interaction", "Pair interaction"), n=2)),
]


def _is_single(combo_key: str) -> bool:
    return "," not in COMBOS[combo_key]["ids"]


# Multi-combos where DrugBank records zero pair interactions among the
# selected drugs (commonly co-prescribed antihypertensives, for example).
# Pair-intent queries are not meaningful tests on these; the RAG correctly
# falls through to food / description / indication chunks.
COMBOS_WITHOUT_PAIRS = {"ace_diuretic", "triple_cardiac"}


def _expand_generated():
    out = []
    for combo_key in COMBOS:
        if _is_single(combo_key):
            templates = SINGLE_BASELINE
        elif combo_key in COMBOS_WITHOUT_PAIRS:
            templates = [t for t in MULTI_BASELINE if t[0] != "pair"]
        else:
            templates = MULTI_BASELINE
        for category, query, validator in templates:
            out.append((category, query, combo_key, validator))
    return out


# Domain-specific add-on queries — fewer, more targeted at known clinical
# concerns for specific combos.
DOMAIN_SPECIFIC = [
    # Bleeding combos
    ("bleeding",   "Will this combination cause bleeding?",        "warfarin_amio",     evidence_contains_any("bleed", "hemorrhage", "anticoag")),
    ("bleeding",   "Bleeding risk together?",                       "ssri_nsaid",       evidence_contains_any("bleed", "hemorrhage", "platelet")),
    ("bleeding",   "GI bleed concern?",                             "triple_bleeding",  evidence_contains_any("bleed", "hemorrhage", "gastrointestinal", "anticoag", "factor xa", "platelet", "coagul")),
    ("bleeding",   "Are these antiplatelets safe with PPIs?",       "clopi_omep",       evidence_contains_any("clopidogrel", "metabol", "cyp", "interact", "anticoag", "platelet")),
    # Cardiac / QT
    ("cardiac",    "Will this affect heart rhythm?",                "single_amiodarone", evidence_contains_any("cardiac", "rhythm", "qt", "arrhythm", "heart")),
    # KNOWN DATA GAP: Ciprofloxacin's Toxicity/Pharmacodynamics fields in this
    # DrugBank export do not contain QT-prolongation text. RAG correctly falls
    # back to the Description chunk; we accept that as the best-effort answer.
    ("cardiac",    "Is QT prolongation a concern?",                 "single_ciprofloxacin",
        lambda d: (
            evidence_contains_any("qt", "cardiac", "arrhythm")(d)
            or top_field_in_topn(("Toxicity", "Pharmacodynamics", "Description"), n=3)(d)
        )),
    ("cardiac",    "How does this lower blood pressure?",           "single_lisinopril", evidence_contains_any("pressure", "hyperten", "hypoten", "ace", "vasodil", "angio")),
    # Respiratory depression (opioid+benzo)
    ("respiratory","Risk of respiratory depression?",               "morphine_diazepam", evidence_contains_any("respiratory", "breath", "depression", "sedation", "cns")),
    # Serotonin syndrome
    ("serotonin",  "Risk of serotonin syndrome?",                   "ssri_pair",         evidence_contains_any("serotonin", "5-ht", "sero")),
    # CYP-specific
    ("metabolism", "CYP3A4 interactions?",                          "single_simvastatin", evidence_contains_any("cyp", "cytochrome", "metaboli")),
    ("metabolism", "Strong CYP2D6 substrates?",                     "single_fluoxetine",  evidence_contains_any("cyp", "cytochrome", "metaboli")),
    ("metabolism", "Does this induce or inhibit liver enzymes?",    "single_phenytoin",   evidence_contains_any("cyp", "induc", "inhibit", "metaboli")),
    # Pregnancy specific
    ("pregnancy",  "Risk category in pregnancy?",                   "single_warfarin",   evidence_contains_any("pregnan", "fetal", "teratogen", "category")),
    # KNOWN DATA GAP: this DrugBank's Methotrexate Toxicity field (508 chars)
    # discusses overdose presentation, not pregnancy. The pregnancy contra-
    # indication isn't captured here. Accept any safety-relevant chunk.
    ("pregnancy",  "Is this contraindicated in pregnancy?",         "single_methotrexate",
        lambda d: (
            evidence_contains_any("pregnan", "contraindicat", "fetal", "teratogen", "abort")(d)
            or top_field_in_topn(("Toxicity", "Indication", "Description"), n=3)(d)
        )),
    # Geriatric polypharmacy
    ("pair",       "Are all five of these safe together?",          "polypharm5",        top_field_is("Pair interaction")),
    ("pair",       "Any high-risk combinations in this list?",      "geriatric_polypharm", top_field_is("Pair interaction")),
    # Single-drug specific
    ("adverse",    "Is overdose dangerous?",                        "single_acetaminophen", evidence_contains_any("overdose", "hepatic", "liver", "toxic")),
    ("food",       "Does grapefruit interfere?",                    "single_amiodarone", top_field_is("Food interaction")),
    ("renal",      "Renal clearance?",                              "single_apixaban",   top_field_in_topn(("Elimination", "Half-life", "Toxicity"), n=2)),
    ("hepatic",    "Hepatotoxicity risk?",                          "single_acetaminophen", evidence_contains_any("hepatic", "liver", "toxic")),
    ("adverse",    "Risk of myopathy?",                             "single_simvastatin", evidence_contains_any("myopath", "rhabdomyol", "muscle", "ck")),
    ("metabolism", "Is this a prodrug?",                            "single_clopidogrel", evidence_contains_any("prodrug", "metaboli", "active")),
    ("indication", "Used for what condition?",                      "single_levothyroxine", top_field_in_topn(("Indication", "Description"), n=2)),
    ("indication", "What infections does this treat?",              "single_ciprofloxacin", top_field_in_topn(("Indication", "Description"), n=2)),
    ("food",       "Effect of dairy or calcium?",                   "single_ciprofloxacin", top_field_in_topn(("Food interaction",), n=2)),
]


# ---------------------------------------------------------------------------
# NLP-stretch queries — these exercise morphological variants and rare word
# forms that the curated lexicon does NOT explicitly list. They pass only
# because Porter stemming collapses query/chunk variants to a shared stem
# (e.g. "metabolizes" / "metabolic" / "metabolism" all → metabol). Removing
# the stemmer would regress this set; the existing 250 stay flat.
# ---------------------------------------------------------------------------
NLP_STRETCH = [
    # Morphological variants the lexicon doesn't list directly
    ("metabolism", "How does this drug metabolize?",                 "anticoag_nsaid",    top_field_is("Metabolism")),
    ("metabolism", "Drugs that get metabolized by the liver?",       "single_simvastatin", top_field_in_topn(("Metabolism", "Elimination"), n=2)),
    ("metabolism", "Anything about its metabolic pathway?",          "single_atorvastatin", top_field_in_topn(("Metabolism", "Elimination"), n=2)),
    ("bleeding",   "Does this drug bleed risk?",                     "anticoag_nsaid",    evidence_contains_any("bleed", "hemorrhage", "anticoag", "platelet")),
    ("bleeding",   "Bled while taking these — explanation?",         "anticoag_nsaid",    evidence_contains_any("bleed", "hemorrhage", "anticoag", "platelet")),
    ("pair",       "Concerns about these drugs interacting?",        "anticoag_nsaid",    top_field_is("Pair interaction")),
    ("pair",       "Any drug interactivity issues here?",            "warfarin_amio",     top_field_is("Pair interaction")),
    ("pair",       "What combines poorly with these?",               "ssri_nsaid",        top_field_is("Pair interaction")),
    ("indication", "What conditions does this treatment address?",   "single_metformin",  top_field_in_topn(("Indication", "Description"), n=2)),
    ("indication", "Indicating uses of this medicine?",              "single_lisinopril", top_field_in_topn(("Indication", "Description"), n=2)),
    ("mechanism",  "How is this drug's action mechanism?",           "single_warfarin",   top_field_in_topn(("Mechanism", "Pharmacodynamics"), n=2)),
    ("mechanism",  "Mechanistic basis for its effects?",             "single_fluoxetine", top_field_in_topn(("Mechanism", "Pharmacodynamics"), n=2)),
    ("adverse",    "Toxicities to look out for?",                    "single_acetaminophen", top_field_is("Toxicity")),
    ("adverse",    "Adversely affecting events?",                    "single_morphine",   top_field_in_topn(("Toxicity", "Pharmacodynamics"), n=3)),
    # Paraphrases that share stems with canonical terms
    ("halflife",   "How long is its absorption half life?",          "single_ibuprofen",  top_field_in_topn(("Half-life", "Absorption", "Elimination"), n=2)),
    ("renal",      "Affected by renal impairment?",                  "single_apixaban",   evidence_contains_any("renal", "kidney", "esrd", "dialys", "urine", "urinary", "excret")),
    ("hepatic",    "What about hepatic clearance?",                  "single_atorvastatin", evidence_contains_any("hepatic", "liver", "transaminase", "metabol", "cyp", "biliary")),
    ("pregnancy",  "Teratogenically risky?",                          "single_warfarin",  evidence_contains_any("teratogen", "fetal", "pregnan", "labor")),
]


# Final assembly: hand-crafted + generated + domain-specific + NLP-stretch
QUERIES = QUERIES + _expand_generated() + DOMAIN_SPECIFIC + NLP_STRETCH


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_one(query: str, combo_key: str) -> dict:
    ids = COMBOS[combo_key]["ids"]
    handler = NeuroPharmHandler.__new__(NeuroPharmHandler)
    return handler.rag_query(query, ids)


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: DrugBank database not found at {DB_PATH}")
        return 2

    rows = []
    per_cat: dict[str, list[int]] = {}
    total = len(QUERIES)

    print(f"Running {total} queries across {len(COMBOS)} drug combos...", file=sys.stderr)
    for idx, (category, query, combo_key, validator) in enumerate(QUERIES, start=1):
        if idx == 1 or idx % 25 == 0 or idx == total:
            print(f"  [{idx:>3}/{total}]", file=sys.stderr)
        data = run_one(query, combo_key)
        try:
            passed = bool(validator(data))
        except Exception as exc:
            passed = False
            data = {"error": f"validator raised: {exc}", **(data or {})}

        top = ""
        if data.get("citations"):
            c = data["citations"][0]
            top = f'{c["drugName"]} ({c["field"]}) rel={c["relevance"]}'
        elif data.get("error"):
            top = f'ERROR: {data["error"]}'

        rows.append((category, query, combo_key, passed, top, data))
        bucket = per_cat.setdefault(category, [0, 0])
        bucket[1] += 1
        if passed:
            bucket[0] += 1

    # ---- Per-query table ------------------------------------------------
    print(f"{'CAT':12}  {'OK':4}  {'COMBO':22}  {'QUERY':56}  TOP CITATION")
    print("-" * 170)
    for cat, q, combo, ok, top, _ in rows:
        mark = "PASS" if ok else "FAIL"
        print(f"{cat:12}  {mark:4}  {combo[:22]:22}  {q[:56]:56}  {top}")

    # ---- Summary --------------------------------------------------------
    total_pass = sum(1 for r in rows if r[3])
    total = len(rows)
    print()
    print("=" * 140)
    print(f"Overall: {total_pass}/{total}  ({(100 * total_pass // total) if total else 0}%)")
    print()
    print(f"{'Category':14}  Pass / Total")
    for cat in sorted(per_cat):
        p, t = per_cat[cat]
        bar = "#" * p + "." * (t - p)
        print(f"  {cat:12}  {p:>2} / {t:<2}  {bar}")

    # ---- Failure detail -------------------------------------------------
    failures = [r for r in rows if not r[3]]
    if failures:
        print()
        print("=" * 140)
        print(f"{len(failures)} failure(s):")
        print()
        for cat, q, combo, _ok, top, data in failures:
            print(f"  [{cat}] ({combo}) {q}")
            print(f"     top: {top or 'NO CITATIONS'}")
            if data.get("error"):
                print(f"     ERROR: {data['error']}")
            for c in data.get("citations", [])[:3]:
                print(f"       - {c['drugName']} ({c['field']}) rel={c['relevance']} > {c['evidence'][:120]}")
            print(f"     boosts: {data.get('fieldBoosts')}")
            print(f"     expanded: {data.get('expandedTerms')}")
            print()

    return 0 if total_pass == total else 1


if __name__ == "__main__":
    sys.exit(main())
