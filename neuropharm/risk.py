from __future__ import annotations

import sqlite3

from .text import compact

PATIENT_CONTEXT_RULES = {
    "older_adult": {
        "label": "Older adult",
        "terms": ("geriatric", "elderly", "aged", "75 years", "advanced age", "older"),
        "points": 9,
        "monitor": "Review dose sensitivity, fall risk, bleeding, renal function, and CNS adverse effects.",
    },
    "pregnancy": {
        "label": "Pregnancy",
        "terms": ("pregnancy", "pregnant", "fetal", "foetal", "teratogen", "teratogenic", "labor", "labour", "breastfeeding", "nursing"),
        "points": 14,
        "monitor": "Check pregnancy safety language, fetal risk, labor effects, and lactation warnings.",
    },
    "kidney": {
        "label": "Kidney disease",
        "terms": ("renal", "kidney", "nephro", "urine", "urinary", "esrd", "dialysis", "creatinine", "glomerular"),
        "points": 11,
        "monitor": "Review renal elimination, dose adjustment language, accumulation risk, and renal adverse effects.",
    },
    "liver": {
        "label": "Liver disease",
        "terms": ("hepatic", "liver", "cirrhosis", "cyp", "cytochrome", "metabolism", "transaminase", "bilirubin"),
        "points": 10,
        "monitor": "Review hepatic metabolism, CYP overlap, liver impairment language, and exposure changes.",
    },
    "bleeding": {
        "label": "Bleeding risk",
        "terms": ("bleeding", "hemorrhage", "haemorrhage", "anticoagulant", "antiplatelet", "platelet", "inr", "thrombin", "coagulation"),
        "points": 14,
        "monitor": "Review anticoagulant or antiplatelet overlap, bleeding symptoms, INR language, and GI bleeding risk.",
    },
    "diabetes": {
        "label": "Diabetes",
        "terms": ("diabetes", "diabetic", "glucose", "glycemic", "glycaemic", "hypoglycemia", "hyperglycemia", "insulin"),
        "points": 8,
        "monitor": "Review glucose-related warnings, metabolic effects, and diabetes-specific indications.",
    },
    "hypertension": {
        "label": "Hypertension",
        "terms": ("hypertension", "blood pressure", "hypotension", "sodium retention", "diuretic", "cardiac", "heart failure"),
        "points": 8,
        "monitor": "Review blood pressure effects, sodium retention, heart failure language, and cardiovascular warnings.",
    },
    "alcohol": {
        "label": "Alcohol use",
        "terms": ("avoid alcohol", "alcohol use", "ethanol", "cns depression", "sedation", "drowsiness", "somnolence"),
        "points": 8,
        "monitor": "Review alcohol-specific counseling, CNS depression, sedation, and toxicity language.",
    },
}

RISK_ESCALATORS = {
    "contraindicated": 8,
    "contraindication": 8,
    "fatal": 8,
    "life-threatening": 8,
    "toxicity": 5,
    "severe": 5,
    "increase": 3,
    "increased": 3,
    "risk": 2,
}


def severity_for(description: str | None) -> tuple[str, str]:
    text = (description or "").lower()
    high_terms = ("contraindicated", "life-threatening", "fatal", "hemorrhage", "bleeding", "toxicity")
    moderate_terms = ("risk", "severity", "increase", "decrease", "adverse", "serum concentration")

    if any(term in text for term in high_terms):
        return "high", "High attention"
    if any(term in text for term in moderate_terms):
        return "moderate", "Monitor"
    return "informational", "Informational"


def row_to_drug(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["drugbank_id"],
        "name": row["name"] or row["drugbank_id"],
        "description": compact(row["description"], 2200),
        "indication": compact(row["indication"], 2600),
        "mechanism": compact(row["mechanism_of_action"], 2600),
        "toxicity": compact(row["toxicity"], 1800),
        "metabolism": compact(row["metabolism"], 1800),
        "half_life": compact(row["half_life"], 900),
    }
