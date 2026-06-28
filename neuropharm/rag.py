from __future__ import annotations

import math
import re
from collections import Counter

from .nlp import porter_stem

RAG_STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have how i in is it of on or so that the
    their them then there these this to was were what when where which who why will
    with would you your about against between into through during before after above
    below up down out off can could should may might shall do does did doing done
    not no nor only own same than too very just also any all both each few more most
    other some such only own per via vs versus
    """.split()
)

RAG_FIELDS = (
    ("description", "Description"),
    ("indication", "Indication"),
    ("pharmacodynamics", "Pharmacodynamics"),
    ("mechanism_of_action", "Mechanism"),
    ("toxicity", "Toxicity"),
    ("metabolism", "Metabolism"),
    ("absorption", "Absorption"),
    ("half_life", "Half-life"),
    ("route_of_elimination", "Elimination"),
)


# Lexicon that maps natural-language query tokens onto canonical pharmacology
# vocabulary that actually appears in DrugBank text. Pure BM25 over a literal
# query like "what happens if I take these together?" returns near-zero scores
# because none of those tokens occur in the corpus; expansion fixes that.
RAG_QUERY_EXPANSIONS = {
    # Interaction / co-administration intent
    "together": ("interaction", "concurrent", "combined", "coadministration"),
    "combine": ("interaction", "concurrent", "combined"),
    "combined": ("interaction", "concurrent"),
    "combining": ("interaction", "concurrent", "combined"),
    "mix": ("interaction", "concurrent", "combined"),
    "mixing": ("interaction", "concurrent", "combined"),
    "interact": ("interaction", "concurrent"),
    "interaction": ("interaction", "concurrent"),
    "interactions": ("interaction", "concurrent"),
    "concurrent": ("interaction", "concurrent", "combined"),
    "concurrently": ("interaction", "concurrent", "combined"),
    "coadminister": ("interaction", "concurrent", "combined"),
    "coadministration": ("interaction", "concurrent", "combined"),
    "combination": ("interaction", "concurrent", "combined", "coadministration"),
    "combinations": ("interaction", "concurrent", "combined", "coadministration"),
    # Outcome / risk wording
    "happen": ("effect", "risk", "outcome", "adverse"),
    "happens": ("effect", "risk", "outcome", "adverse"),
    "danger": ("risk", "severe", "toxicity", "adverse"),
    "dangerous": ("risk", "severe", "toxicity", "adverse"),
    "side": ("adverse", "toxicity"),
    "effect": ("effect", "adverse"),
    "effects": ("effect", "adverse"),
    "reaction": ("adverse", "toxicity", "effect"),
    "reactions": ("adverse", "toxicity", "effect"),
    "safe": ("risk", "adverse", "contraindicated"),
    "safety": ("risk", "adverse", "contraindicated"),
    "avoid": ("contraindicated", "avoid", "interaction"),
    "toxic": ("toxicity", "adverse", "overdose"),
    "toxicities": ("toxicity", "adverse"),
    "overdose": ("overdose", "lethal", "fatal", "toxic"),
    # Body systems / clinical context
    "blood": ("bleeding", "hemorrhage"),
    "thinner": ("anticoagulant",),
    "thinners": ("anticoagulant",),
    "renal": ("renal", "kidney", "nephro", "esrd", "dialysis", "urine", "urinary"),
    "kidney": ("renal", "kidney", "nephro", "esrd", "dialysis", "urine", "urinary"),
    "kidneys": ("renal", "kidney", "nephro", "esrd", "dialysis", "urine", "urinary"),
    "liver": ("hepatic", "liver", "transaminase", "cyp"),
    "hepatic": ("hepatic", "liver", "transaminase"),
    "hepatotoxic": ("hepatic", "liver", "transaminase", "hepatotoxic"),
    "hepatotoxicity": ("hepatic", "liver", "transaminase"),
    "stomach": ("gastric", "gastrointestinal"),
    "pregnant": ("pregnancy", "fetal", "teratogen", "teratogenic"),
    "pregnancy": ("pregnancy", "fetal", "teratogen", "teratogenic"),
    "teratogenic": ("teratogen", "teratogenic", "fetal", "pregnancy"),
    "teratogenicity": ("teratogen", "teratogenic", "fetal", "pregnancy"),
    "baby": ("fetal", "pregnancy", "infant"),
    "infant": ("infant", "neonatal", "pediatric"),
    "sugar": ("glucose", "glycemic"),
    "diabetic": ("diabetes", "glycemic", "insulin"),
    "pressure": ("hypertension", "hypotension", "pressure"),
    "heart": ("cardiac", "cardiovascular"),
    # Mechanism / pharmacology
    "enzyme": ("enzyme", "metabolism", "cyp"),
    "enzymes": ("enzyme", "metabolism", "cyp"),
    "metabolized": ("metabolism", "metabolic", "cyp"),
    "metabolism": ("metabolism", "metabolic", "cyp"),
    "work": ("mechanism", "action", "pharmacodynamics", "effect"),
    "works": ("mechanism", "action", "pharmacodynamics", "effect"),
    "function": ("mechanism", "action", "pharmacodynamics"),
    "mechanism": ("mechanism", "action"),
    # Diet
    "drinking": ("alcohol", "ethanol"),
    "drink": ("alcohol", "ethanol"),
    "eat": ("food",),
    "eating": ("food",),
    "meal": ("food",),
    # Duration / clearance
    "long": ("half-life", "elimination", "duration", "hours"),
    "duration": ("half-life", "elimination", "hours"),
    "stay": ("elimination", "half-life", "excretion"),
    "remain": ("elimination", "half-life", "excretion"),
    "body": ("elimination", "absorption", "excretion"),
    "clear": ("elimination", "half-life", "clearance", "excretion"),
    "clears": ("elimination", "half-life", "clearance"),
    "clearance": ("elimination", "half-life", "clearance", "excretion"),
    "quickly": ("rapid", "absorption", "hours"),
    "rapidly": ("rapid", "absorption", "hours"),
    # Indication / use
    "treat": ("indication", "treatment", "therapy", "indicated"),
    "treats": ("indication", "treatment", "therapy", "indicated"),
    "treating": ("indication", "treatment", "therapy"),
    "treated": ("indication", "treatment", "therapy"),
    "treatment": ("indication", "treatment", "therapy"),
    "prescribed": ("indication", "treatment", "therapy", "indicated"),
    "prescribe": ("indication", "treatment", "therapy", "indicated"),
    "prescription": ("indication", "treatment"),
    "used": ("indication", "treatment", "therapy"),
    "uses": ("indication", "treatment", "therapy"),
    "indicated": ("indication", "treatment", "indicated"),
    # Generic fallback so "tell me everything"-style queries still land somewhere
    "everything": ("description", "indication", "mechanism", "toxicity"),
    "tell": ("description", "indication"),
    "summary": ("description", "indication"),
    "about": ("description", "indication"),
    "overview": ("description", "indication"),
    # Cardiac / QT
    "prolongation": ("qt", "prolong", "interval", "cardiac", "arrhythm"),
    "prolong": ("qt", "prolong", "interval", "cardiac"),
    "rhythm": ("cardiac", "arrhythm", "rhythm", "qt"),
    "arrhythmia": ("cardiac", "arrhythm", "rhythm", "qt"),
    # Bleeding-equivalent vocab so "GI bleed" / "internal bleeding" queries
    # can also match anticoagulant/factor-Xa text in Descriptions.
    "bleed": ("bleed", "bleeding", "hemorrhage", "haemorrhage", "anticoagulant", "platelet"),
    "bleeding": ("bleeding", "hemorrhage", "haemorrhage", "anticoagulant", "platelet"),
    "gi": ("gastric", "gastrointestinal"),
    # Contraindication intent — deliberately NOT expanded to "avoid", because
    # that token pulls in every "Avoid alcohol/grapefruit" food chunk and
    # crowds out the actual contraindication evidence.
    "contraindicated": ("contraindicated", "contraindication", "warning"),
    "contraindication": ("contraindicated", "contraindication", "warning"),
    # Respiratory
    "respiratory": ("respiratory", "breath", "respiration", "depression"),
    "breathing": ("respiratory", "breath", "respiration"),
    # Serotonin
    "serotonin": ("serotonin", "5-ht", "sero"),
    # Misc clinical
    "myopathy": ("myopath", "rhabdomyol", "muscle", "myalgia"),
    "rhabdomyolysis": ("rhabdomyol", "myopath", "muscle"),
    "prodrug": ("prodrug", "metabolized", "active", "metabolic"),
    # Porter can't reduce irregular past tenses (bled, took, came, bound).
    # Map the common clinical ones explicitly.
    "bled": ("bleed", "bleeding", "hemorrhage"),
    "took": ("take", "administer"),
    "given": ("give", "administer", "dose"),

    # ===================================================================
    # Lay / patient-language vocabulary. Worried patients don't type
    # "anticoagulant" — they type "blood thinner". Each entry maps a
    # colloquial term to the clinical vocabulary that actually appears in
    # DrugBank text so BM25 can match.
    # ===================================================================

    # --- Food / drinks ---
    "wine": ("alcohol", "ethanol"),
    "beer": ("alcohol", "ethanol"),
    "liquor": ("alcohol", "ethanol"),
    "booze": ("alcohol", "ethanol"),
    "coffee": ("caffeine", "food"),
    "caffeine": ("caffeine", "food", "stimulant"),
    "tea": ("caffeine", "food"),
    "soda": ("caffeine", "food"),
    "dairy": ("food", "dairy", "calcium", "milk"),
    "milk": ("food", "dairy", "calcium"),
    "tummy": ("gastric", "gastrointestinal", "abdominal"),
    "belly": ("gastric", "gastrointestinal", "abdominal"),

    # --- Sensations / common adverse events ---
    "dizzy": ("dizziness", "cns", "drowsiness", "hypotension"),
    "dizziness": ("dizziness", "cns", "drowsiness"),
    "lightheaded": ("dizziness", "cns", "hypotension"),
    "sleepy": ("sedation", "drowsiness", "somnolence", "cns"),
    "drowsy": ("drowsiness", "sedation", "somnolence", "cns"),
    "drowsiness": ("drowsiness", "sedation", "somnolence"),
    "tired": ("fatigue", "sedation", "drowsiness", "lethargy"),
    "fatigue": ("fatigue", "sedation", "lethargy"),
    "sick": ("nausea", "vomit", "adverse"),
    "nausea": ("nausea", "vomit", "gastrointestinal", "adverse"),
    "nauseous": ("nausea", "vomit", "gastrointestinal", "adverse"),
    "nauseated": ("nausea", "vomit", "gastrointestinal", "adverse"),
    "vomit": ("vomit", "nausea", "gastrointestinal"),
    "vomiting": ("vomit", "nausea", "gastrointestinal"),
    "constipated": ("constipation", "gastrointestinal"),
    "constipation": ("constipation", "gastrointestinal"),
    "diarrhea": ("diarrhea", "gastrointestinal"),
    # Note: deliberately NOT expanding "weight" to "metabolic" — that pulls
    # mechanism-field content (metabolic pathways) into a side-effect query.
    "weight": ("weight", "appetite", "increase", "decrease"),
    "gain": ("gain", "increase"),
    "bruise": ("bleeding", "hemorrhage", "ecchymosis", "platelet"),
    "bruising": ("bleeding", "hemorrhage", "ecchymosis", "platelet"),
    "pee": ("urine", "urinary", "diuretic"),
    "urinate": ("urine", "urinary", "diuretic"),
    "urination": ("urine", "urinary", "diuretic"),
    "headache": ("headache", "cephalalgia", "cns"),
    "rash": ("rash", "dermatologic", "skin", "hypersensitivity"),
    "itchy": ("pruritus", "rash", "dermatologic"),
    "itch": ("pruritus", "rash", "dermatologic"),

    # --- Patient populations ---
    "old": ("elderly", "geriatric", "older", "aged"),
    "older": ("elderly", "geriatric", "older", "aged"),
    "elderly": ("elderly", "geriatric", "older", "aged"),
    "senior": ("elderly", "geriatric", "older"),
    "seniors": ("elderly", "geriatric", "older"),
    "kid": ("pediatric", "child", "children", "infant"),
    "kids": ("pediatric", "child", "children", "infant"),
    "child": ("pediatric", "child", "children"),
    "children": ("pediatric", "child", "pediatric"),
    "teen": ("adolescent", "pediatric"),
    "teenager": ("adolescent", "pediatric"),

    # --- Drug classes (lay → clinical) ---
    "antibiotic": ("antibiotic", "antibacterial", "antimicrobial", "infection"),
    "antibiotics": ("antibiotic", "antibacterial", "antimicrobial", "infection"),
    "antibacterial": ("antibacterial", "antibiotic", "antimicrobial"),
    "painkiller": ("analgesic", "pain", "narcotic", "opioid"),
    "painkillers": ("analgesic", "pain", "narcotic", "opioid"),
    "narcotic": ("opioid", "narcotic", "analgesic"),
    "antidepressant": ("antidepressant", "ssri", "depression", "serotonin"),
    "antidepressants": ("antidepressant", "ssri", "depression"),
    "ssri": ("ssri", "serotonin", "antidepressant"),
    "statin": ("statin", "hmg", "lipid", "cholesterol", "hmg-coa"),
    "statins": ("statin", "hmg", "lipid", "cholesterol"),

    # --- Driving / function ---
    "drive": ("driving", "cns", "drowsiness", "sedation"),
    "driving": ("driving", "cns", "drowsiness", "sedation"),

    # --- Addiction / dependence ---
    "addictive": ("addiction", "dependence", "abuse", "withdrawal"),
    "addiction": ("addiction", "dependence", "abuse", "withdrawal"),
    "addicted": ("addiction", "dependence", "abuse", "withdrawal"),
    "habit": ("addiction", "dependence", "abuse"),
    "withdrawal": ("withdrawal", "dependence", "discontinuation"),

    # --- Potency words ---
    "strong": ("potent", "potency", "strong"),
    "powerful": ("potent", "potency", "strong"),
    "weak": ("weak", "low", "mild"),
    "potent": ("potent", "potency"),

    # --- Worry / vague safety ---
    "worry": ("risk", "adverse", "safety"),
    "worried": ("risk", "adverse", "safety"),
    "scared": ("risk", "adverse", "safety"),
    "afraid": ("risk", "adverse", "safety"),
    "concerned": ("risk", "adverse", "safety"),

    # --- "Too much" / dosing ---
    "much": ("overdose", "dose", "toxic"),
}


# Stem-indexed expansion lookup (built immediately so the function defined
# below can use it). The token-field-boost stem index is built later in the
# file, after RAG_TOKEN_FIELD_BOOSTS itself is defined.
RAG_EXPANSION_BY_STEM: dict[str, tuple[str, ...]] = {}
for _key, _vals in RAG_QUERY_EXPANSIONS.items():
    _stem = porter_stem(_key)
    RAG_EXPANSION_BY_STEM.setdefault(_stem, _vals)


# Original-query tokens that flag co-administration questions. When any of
# these appear and >=2 drugs are selected, pair-interaction chunks are boosted.
RAG_INTERACTION_INTENT = frozenset(
    (
        "together",
        "combine",
        "combined",
        "combining",
        "interaction",
        "interactions",
        "interact",
        "mix",
        "mixing",
        "coadminister",
        "coadministration",
        "concurrent",
        "concurrently",
        "combination",
        "combinations",
    )
)


# Phrase substrings that also signal "I'm asking about co-administration" but
# don't contain any token from RAG_INTERACTION_INTENT (e.g. "at once").
RAG_PAIR_INTENT_PHRASES = frozenset(
    (
        "at once",
        "all three",
        "all four",
        "all five",
        "all of them",
        "all these",
        "all of these",
        "what happens",
        # Colloquial DDI phrases real people use
        "take both",
        "use both",
        "doing both",
        "on top of",
        "on top",
        "cancel each other",
        "cancel out",
        "stop one",
        "drop one",
        "one of them",
    )
)


# Phrase substrings (lowercased query) that trigger field boosts.
RAG_INTENT_PHRASES = {
    "what happens": {"Pair interaction": 1.8, "Toxicity": 1.2},
    "side effect": {"Toxicity": 1.6, "Pharmacodynamics": 1.2},
    "side effects": {"Toxicity": 1.6, "Pharmacodynamics": 1.2},
    "adverse reaction": {"Toxicity": 1.7},
    "adverse reactions": {"Toxicity": 1.7},
    "adverse effect": {"Toxicity": 1.7},
    "adverse effects": {"Toxicity": 1.7},
    "safe to take": {"Pair interaction": 1.6, "Toxicity": 1.3},
    "safe to use": {"Pair interaction": 1.4, "Toxicity": 1.3},
    "okay to take": {"Pair interaction": 1.6, "Toxicity": 1.3},
    "at once": {"Pair interaction": 2.0},
    "all three": {"Pair interaction": 2.0},
    "all four": {"Pair interaction": 2.0},
    "all of them": {"Pair interaction": 2.0},
    "all these": {"Pair interaction": 2.0},
    "all of these": {"Pair interaction": 2.0},
    "blood pressure": {"Pharmacodynamics": 1.5, "Toxicity": 1.3},
    "mechanism of action": {"Mechanism": 1.8},
    # "Too much" implies overdose / toxicity context.
    "too much":  {"Toxicity": 1.7},
    "too many":  {"Toxicity": 1.7},
    "overdose":  {"Toxicity": 1.7},
    # Lay phrases that signal adverse-event interest.
    "make me":   {"Toxicity": 1.3, "Pharmacodynamics": 1.3},
    "feel sick": {"Toxicity": 1.5},
    "feel weird":{"Toxicity": 1.4},
}


# Original-query tokens that route attention toward specific fields.
RAG_TOKEN_FIELD_BOOSTS = {
    # Food / diet
    "alcohol":     {"Food interaction": 1.5},
    "food":        {"Food interaction": 1.7},
    "eat":         {"Food interaction": 1.4},
    "drink":       {"Food interaction": 1.3},
    "dietary":     {"Food interaction": 1.5},
    "grapefruit":  {"Food interaction": 1.6},
    # Organ systems
    "kidney":      {"Elimination": 1.4, "Toxicity": 1.3},
    "kidneys":     {"Elimination": 1.4, "Toxicity": 1.3},
    "renal":       {"Elimination": 1.4, "Toxicity": 1.3},
    "liver":       {"Metabolism": 1.4, "Toxicity": 1.3},
    "hepatic":     {"Metabolism": 1.4, "Toxicity": 1.3},
    "hepatotoxic": {"Toxicity": 1.7, "Metabolism": 1.2},
    # Pharmacology
    "cyp":         {"Metabolism": 2.2},   # dominates the pair-interaction 2.0 when user explicitly asks CYP
    "metabolized": {"Metabolism": 1.7},
    "metabolism":  {"Metabolism": 1.5},
    "cytochrome":  {"Metabolism": 1.8},
    # Pregnancy
    "pregnancy":   {"Toxicity": 1.5},
    "pregnant":    {"Toxicity": 1.5},
    "teratogenic": {"Toxicity": 1.6},
    "fetal":       {"Toxicity": 1.5},
    "maternal":    {"Toxicity": 1.4},
    "breastfeeding": {"Toxicity": 1.4},
    "nursing":     {"Toxicity": 1.4},
    # Toxicity
    "adverse":     {"Toxicity": 1.6},
    "reactions":   {"Toxicity": 1.5},
    "side":        {"Toxicity": 1.4},
    "toxicity":    {"Toxicity": 1.6},
    "toxicities":  {"Toxicity": 1.6},
    "overdose":    {"Toxicity": 1.6},
    # Duration / clearance
    "clear":       {"Elimination": 1.4, "Half-life": 1.3},
    "clearance":   {"Elimination": 1.5, "Half-life": 1.3},
    "quickly":     {"Absorption": 1.3, "Half-life": 1.3},
    # Mechanism
    "mechanism":   {"Mechanism": 1.7},
    "action":      {"Mechanism": 1.3, "Pharmacodynamics": 1.3},
    "work":        {"Mechanism": 1.5, "Pharmacodynamics": 1.3},
    "works":       {"Mechanism": 1.5, "Pharmacodynamics": 1.3},
    "receptor":    {"Mechanism": 1.5, "Pharmacodynamics": 1.3},
    "receptors":   {"Mechanism": 1.5, "Pharmacodynamics": 1.3},
    "target":      {"Mechanism": 1.4},
    # Indication
    "treat":       {"Indication": 1.6},
    "treats":      {"Indication": 1.6},
    "treatment":   {"Indication": 1.4},
    "treating":    {"Indication": 1.4},
    "prescribed":  {"Indication": 1.5},
    "indicated":   {"Indication": 1.5},
    "used":        {"Indication": 1.3},
    # Cardiac / QT
    "qt":          {"Toxicity": 1.5, "Pharmacodynamics": 1.4},
    "prolongation":{"Toxicity": 1.5, "Pharmacodynamics": 1.4},
    "rhythm":      {"Pharmacodynamics": 1.4, "Toxicity": 1.3},
    "arrhythm":    {"Toxicity": 1.5, "Pharmacodynamics": 1.4},
    # Respiratory
    "respiratory": {"Toxicity": 1.5, "Pharmacodynamics": 1.3},
    "breathing":   {"Toxicity": 1.5},
    # Serotonin
    "serotonin":   {"Pharmacodynamics": 1.5, "Mechanism": 1.4, "Toxicity": 1.3},
    # Contraindication / safety
    "contraindicated":{"Toxicity": 1.5, "Pair interaction": 1.3},
    # Misc
    "myopathy":    {"Toxicity": 1.6},
    "rhabdomyolysis":{"Toxicity": 1.6},
    "prodrug":     {"Metabolism": 1.5, "Pharmacodynamics": 1.3},

    # ---- Lay symptom words → Toxicity / Pharmacodynamics --------------
    "dizzy":       {"Toxicity": 1.5, "Pharmacodynamics": 1.3},
    "dizziness":   {"Toxicity": 1.5, "Pharmacodynamics": 1.3},
    "sleepy":      {"Toxicity": 1.5, "Pharmacodynamics": 1.3},
    "drowsy":      {"Toxicity": 1.5, "Pharmacodynamics": 1.3},
    "drowsiness":  {"Toxicity": 1.5, "Pharmacodynamics": 1.3},
    "tired":       {"Toxicity": 1.4, "Pharmacodynamics": 1.3},
    "fatigue":     {"Toxicity": 1.4, "Pharmacodynamics": 1.3},
    "sick":        {"Toxicity": 1.5},
    "nausea":      {"Toxicity": 1.5},
    "nauseous":    {"Toxicity": 1.5},
    "vomit":       {"Toxicity": 1.5},
    "vomiting":    {"Toxicity": 1.5},
    "constipated": {"Toxicity": 1.5, "Pharmacodynamics": 1.3},
    "diarrhea":    {"Toxicity": 1.5},
    "weight":      {"Pharmacodynamics": 1.4, "Toxicity": 1.3},
    "bruise":      {"Toxicity": 1.5, "Pair interaction": 1.2},
    "bruising":    {"Toxicity": 1.5, "Pair interaction": 1.2},
    "pee":         {"Elimination": 1.3, "Pharmacodynamics": 1.3},
    "urinate":     {"Elimination": 1.3, "Pharmacodynamics": 1.3},
    "headache":    {"Toxicity": 1.5, "Pharmacodynamics": 1.3},
    "rash":        {"Toxicity": 1.6},
    "itchy":       {"Toxicity": 1.5},

    # ---- Driving / function ------------------------------------------
    "drive":       {"Toxicity": 1.5, "Pharmacodynamics": 1.3},
    "driving":     {"Toxicity": 1.5, "Pharmacodynamics": 1.3},

    # ---- Patient populations -----------------------------------------
    "elderly":     {"Toxicity": 1.4, "Indication": 1.2},
    "geriatric":   {"Toxicity": 1.4},
    "pediatric":   {"Toxicity": 1.4, "Indication": 1.3},
    "kids":        {"Toxicity": 1.3, "Indication": 1.3},
    "child":       {"Toxicity": 1.3, "Indication": 1.3},
    "children":    {"Toxicity": 1.3, "Indication": 1.3},

    # ---- Drug classes (lay) ------------------------------------------
    "antibiotic":  {"Description": 1.4, "Indication": 1.4, "Mechanism": 1.3},
    "antibiotics": {"Description": 1.4, "Indication": 1.4, "Mechanism": 1.3},
    "painkiller":  {"Description": 1.4, "Indication": 1.4, "Mechanism": 1.3},
    "antidepressant":{"Description": 1.4, "Indication": 1.4, "Mechanism": 1.3},
    "statin":      {"Description": 1.4, "Indication": 1.3, "Mechanism": 1.3},

    # ---- Addiction / dependence --------------------------------------
    "addictive":   {"Toxicity": 1.6, "Pharmacodynamics": 1.3, "Description": 1.3},
    "addiction":   {"Toxicity": 1.6, "Pharmacodynamics": 1.3, "Description": 1.3},
    "addicted":    {"Toxicity": 1.6, "Pharmacodynamics": 1.3, "Description": 1.3},
    "withdrawal":  {"Toxicity": 1.5, "Pharmacodynamics": 1.3},

    # ---- Worry (vague safety) ----------------------------------------
    "worry":       {"Toxicity": 1.3, "Description": 1.2},
    "worried":     {"Toxicity": 1.3, "Description": 1.2},

    # ---- Lay food / drink tokens ----
    "wine":        {"Food interaction": 1.7},
    "beer":        {"Food interaction": 1.6},
    "liquor":      {"Food interaction": 1.6},
    "booze":       {"Food interaction": 1.6},
    "coffee":      {"Food interaction": 1.5},
    "caffeine":    {"Food interaction": 1.5},
    "tea":         {"Food interaction": 1.3},
    "soda":        {"Food interaction": 1.3},

    # ---- Stomach / pain colloquial ----
    "stomach":     {"Toxicity": 1.5, "Pharmacodynamics": 1.2},
    "tummy":       {"Toxicity": 1.4},
    "belly":       {"Toxicity": 1.4},
    "hurts":       {"Toxicity": 1.4, "Pharmacodynamics": 1.2},
    "ache":        {"Toxicity": 1.3, "Pharmacodynamics": 1.2},
}


def rag_expand_query(tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    seen = set(tokens)

    def add(synonyms: tuple[str, ...]) -> None:
        for synonym in synonyms:
            if synonym not in seen:
                expanded.append(synonym)
                seen.add(synonym)

    for token in tokens:
        # Direct surface-form lookup first.
        add(RAG_QUERY_EXPANSIONS.get(token, ()))
        # NLP fallback: also resolve via Porter stem so "metabolize" /
        # "metabolizes" / "metabolic" all pick up the "metabolism" expansion.
        stem = porter_stem(token)
        if stem != token:
            add(RAG_EXPANSION_BY_STEM.get(stem, ()))
    return expanded


# Stem-indexed view of RAG_TOKEN_FIELD_BOOSTS so a query token like
# "metabolize" (stem "metabol") picks up the same field boost that "metabolism"
# (also stem "metabol") would. Built after RAG_TOKEN_FIELD_BOOSTS is defined.
RAG_TOKEN_FIELD_BOOSTS_BY_STEM: dict[str, dict[str, float]] = {}
for _key, _vals in RAG_TOKEN_FIELD_BOOSTS.items():
    _stem = porter_stem(_key)
    RAG_TOKEN_FIELD_BOOSTS_BY_STEM.setdefault(_stem, _vals)


def _is_cyp_isoform(token: str) -> bool:
    """Match CYP1A2, CYP2C9, CYP2C19, CYP3A4, etc."""
    return len(token) > 3 and token.startswith("cyp") and any(ch.isdigit() for ch in token[3:])


def rag_field_boosts(
    original_tokens: list[str],
    query_lower: str,
    selected_drug_count: int,
) -> dict[str, float]:
    boosts: dict[str, float] = {}

    def bump(field: str, multiplier: float) -> None:
        if multiplier > boosts.get(field, 1.0):
            boosts[field] = multiplier

    original_set = set(original_tokens)
    pair_intent_via_tokens = bool(original_set & RAG_INTERACTION_INTENT)
    pair_intent_via_phrases = any(p in query_lower for p in RAG_PAIR_INTENT_PHRASES)
    if selected_drug_count >= 2 and (pair_intent_via_tokens or pair_intent_via_phrases):
        bump("Pair interaction", 2.0)

    for phrase, field_boosts in RAG_INTENT_PHRASES.items():
        if phrase in query_lower:
            for field, multiplier in field_boosts.items():
                if field == "Pair interaction" and selected_drug_count < 2:
                    continue
                bump(field, multiplier)

    for token in original_set:
        for field, multiplier in RAG_TOKEN_FIELD_BOOSTS.get(token, {}).items():
            bump(field, multiplier)
        # NLP fallback: lookup by Porter stem too so token-level boosts
        # apply to all morphological variants.
        stem = porter_stem(token)
        if stem != token:
            for field, multiplier in RAG_TOKEN_FIELD_BOOSTS_BY_STEM.get(stem, {}).items():
                bump(field, multiplier)
        # CYP isoform tokens (cyp2c9, cyp3a4, ...) route to Metabolism with
        # enough weight to outrank the pair-interaction baseline boost.
        if _is_cyp_isoform(token):
            bump("Metabolism", 2.4)

    return boosts


_INTERACTION_INTENT_STEMS = frozenset(porter_stem(w) for w in RAG_INTERACTION_INTENT)


# Tokens that signal "tell me about safety / side effects". When detected,
# inject Toxicity-field vocabulary into the BM25 query so chunks whose body
# uses clinical terms ("overdose", "respiratory depression", "death") still
# match queries that use lay vocabulary ("adverse", "events", "side").
RAG_ADVERSE_INTENT = frozenset(
    (
        "adverse",
        "adversely",
        "side",
        "toxic",
        "toxicity",
        "toxicities",
        "overdose",
        "harm",
        "harms",
        "harmful",
        "reactions",
    )
)
_ADVERSE_INTENT_STEMS = frozenset(porter_stem(w) for w in RAG_ADVERSE_INTENT)


def rag_intent_extras(
    original_tokens: list[str],
    query_lower: str,
    selected_drug_count: int,
) -> list[str]:
    """Extra query tokens to inject into BM25 retrieval based on intent.

    A boost can only amplify a non-zero BM25 score, so a phrase like "all
    three at once" must also inject interaction vocabulary into the query;
    otherwise the pair-interaction chunks score zero and the boost has
    nothing to multiply.
    """
    extras: list[str] = []
    original_set = set(original_tokens)
    # NLP: stem-aware intent detection so "interacting"/"interactivity"/
    # "combines" all trigger the pair-interaction path.
    original_stems = {porter_stem(t) for t in original_set}
    pair_intent = (
        bool(original_set & RAG_INTERACTION_INTENT)
        or bool(original_stems & _INTERACTION_INTENT_STEMS)
        or any(phrase in query_lower for phrase in RAG_PAIR_INTENT_PHRASES)
    )
    if pair_intent and selected_drug_count >= 2:
        for term in ("interaction", "concurrent", "combined", "coadministration"):
            if term not in extras:
                extras.append(term)
    # Adverse-events intent: inject clinical safety vocabulary so a lay query
    # like "adversely affecting events?" can still match a Toxicity chunk
    # whose body talks about "overdose" / "respiratory depression" / "death".
    adverse_intent = (
        bool(original_set & RAG_ADVERSE_INTENT)
        or bool(original_stems & _ADVERSE_INTENT_STEMS)
    )
    if adverse_intent:
        for term in ("toxicity", "adverse", "overdose", "effect", "symptom"):
            if term not in extras:
                extras.append(term)
    for token in original_set:
        if _is_cyp_isoform(token):
            for term in ("cyp", "cytochrome", "metabolism"):
                if term not in extras:
                    extras.append(term)
    return extras


def rag_tokenize(text: str) -> list[str]:
    """Tokenize text for BM25 indexing.

    For each surface token we also append its Porter stem so morphological
    variants (metabolize/metabolized/metabolism/metabolic → metabol;
    combine/combined/combining/combination/combinations → combin) all match
    each other via a shared stem. Both query and chunk tokens are stemmed,
    so retrieval works across word forms without manual lexicon entries.
    """
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def push(tok: str) -> None:
        if tok and tok not in seen and tok not in RAG_STOPWORDS:
            out.append(tok)
            seen.add(tok)

    # Pick up tokens including bare 2-char ones (QT, IV, PO, CK, GI ...).
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9\-]*", text.lower()):
        if len(tok) >= 2:
            push(tok)
        # Index sub-parts of hyphenated terms ("half-life" → "half","life").
        if "-" in tok:
            for part in tok.split("-"):
                if len(part) >= 2:
                    push(part)
        # NLP: also yield the Porter stem of any non-trivial token so that
        # "metabolized" and "metabolism" co-index under the stem "metabol".
        if len(tok) >= 4:
            stem = porter_stem(tok)
            if stem != tok and len(stem) >= 2:
                push(stem)
    return out


def rag_split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])|\n+", text)
    return [part.strip() for part in parts if part and part.strip()]


def rag_chunk(text: str, window: int = 3) -> list[str]:
    sentences = rag_split_sentences(text)
    if not sentences:
        return []
    if len(sentences) <= window:
        return [" ".join(sentences)]
    chunks = []
    step = max(1, window - 1)
    for start in range(0, len(sentences), step):
        chunk = " ".join(sentences[start : start + window]).strip()
        if chunk:
            chunks.append(chunk)
        if start + window >= len(sentences):
            break
    return chunks


def rag_bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    doc_freqs: Counter,
    avg_doc_len: float,
    total_docs: int,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    doc_len = len(doc_tokens)
    tf = Counter(doc_tokens)
    score = 0.0
    for term in set(query_tokens):
        df = doc_freqs.get(term, 0)
        if df == 0:
            continue
        idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
        term_tf = tf.get(term, 0)
        if term_tf == 0:
            continue
        numerator = term_tf * (k1 + 1)
        denominator = term_tf + k1 * (1 - b + b * doc_len / max(avg_doc_len, 1.0))
        score += idf * (numerator / denominator)
    return score
