"""Classical NLP helpers used by the RAG pipeline.

Currently provides a pure-stdlib implementation of the Porter (1980)
stemming algorithm. Used by `rag_tokenize` to fold morphological variants
together so a BM25 query for "metabolized" can match a chunk containing
"metabolism" via the shared stem "metabol".

This is deliberately a small, well-known classical algorithm rather than an
embedding model — keeps the project's "no external API, no model downloads"
promise intact.

Reference: M. F. Porter, "An algorithm for suffix stripping" (1980).
"""

from __future__ import annotations

from functools import lru_cache


_VOWELS = frozenset("aeiou")


def _is_consonant(word: str, index: int) -> bool:
    ch = word[index]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return index == 0 or not _is_consonant(word, index - 1)
    return True


def _measure(stem: str) -> int:
    """Porter's m: the count of VC sequences in the stem."""
    if not stem:
        return 0
    n = len(stem)
    i = 0
    while i < n and _is_consonant(stem, i):
        i += 1
    if i == n:
        return 0
    m = 0
    while i < n:
        while i < n and not _is_consonant(stem, i):
            i += 1
        if i == n:
            break
        m += 1
        while i < n and _is_consonant(stem, i):
            i += 1
    return m


def _contains_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(stem: str) -> bool:
    if len(stem) < 2:
        return False
    return stem[-1] == stem[-2] and _is_consonant(stem, len(stem) - 1)


def _ends_cvc(stem: str) -> bool:
    """Consonant-vowel-consonant suffix, last consonant not in W/X/Y."""
    if len(stem) < 3:
        return False
    if not _is_consonant(stem, len(stem) - 1):
        return False
    if _is_consonant(stem, len(stem) - 2):
        return False
    if not _is_consonant(stem, len(stem) - 3):
        return False
    return stem[-1] not in "wxy"


_STEP2 = (
    ("ational", "ate"),
    ("tional", "tion"),
    ("enci", "ence"),
    ("anci", "ance"),
    ("izer", "ize"),
    ("abli", "able"),
    ("alli", "al"),
    ("entli", "ent"),
    ("eli", "e"),
    ("ousli", "ous"),
    ("ization", "ize"),
    ("ation", "ate"),
    ("ator", "ate"),
    ("alism", "al"),
    ("iveness", "ive"),
    ("fulness", "ful"),
    ("ousness", "ous"),
    ("aliti", "al"),
    ("iviti", "ive"),
    ("biliti", "ble"),
)

_STEP3 = (
    ("icate", "ic"),
    ("ative", ""),
    ("alize", "al"),
    ("iciti", "ic"),
    ("ical", "ic"),
    # Extension to vanilla Porter: -istic → -ic so "mechanistic" reduces to
    # the same stem as "mechanism" (both end at "mechan" after step 4).
    ("istic", "ic"),
    ("ful", ""),
    ("ness", ""),
)

_STEP4 = (
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant",
    "ement", "ment", "ent", "ou", "ism", "ate", "iti", "ous",
    "ive", "ize",
)


@lru_cache(maxsize=10000)
def porter_stem(word: str) -> str:
    """Porter stem of `word`. Lowercases first.

    Returns the input unchanged for very short words (length ≤ 2) and for
    tokens that contain digits or hyphens (drug IDs, isoform names like
    `cyp3a4`, `half-life` etc. — these are best left intact).
    """
    if not word:
        return word
    if any(ch.isdigit() or ch == "-" for ch in word):
        return word.lower()
    word = word.lower()
    if len(word) <= 2:
        return word

    # ---------- Step 1a ----------
    if word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("ies"):
        word = word[:-2]
    elif word.endswith("ss"):
        pass
    elif word.endswith("s"):
        word = word[:-1]

    # ---------- Step 1b ----------
    step1b_changed = False
    if word.endswith("eed"):
        if _measure(word[:-3]) > 0:
            word = word[:-1]
    elif word.endswith("ed"):
        stem = word[:-2]
        if _contains_vowel(stem):
            word = stem
            step1b_changed = True
    elif word.endswith("ing"):
        stem = word[:-3]
        if _contains_vowel(stem):
            word = stem
            step1b_changed = True

    if step1b_changed:
        if word.endswith(("at", "bl", "iz")):
            word += "e"
        elif _ends_double_consonant(word) and word[-1] not in "lsz":
            word = word[:-1]
        elif _measure(word) == 1 and _ends_cvc(word):
            word += "e"

    # ---------- Step 1c ----------
    if word.endswith("y") and len(word) > 1 and _contains_vowel(word[:-1]):
        word = word[:-1] + "i"

    # ---------- Step 2 ----------
    for suffix, replacement in _STEP2:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _measure(stem) > 0:
                word = stem + replacement
            break

    # ---------- Step 3 ----------
    for suffix, replacement in _STEP3:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _measure(stem) > 0:
                word = stem + replacement
            break

    # ---------- Step 4 ----------
    for suffix in _STEP4:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _measure(stem) > 1:
                word = stem
            break
    # Special case for -ion (only if preceding char is s or t)
    if word.endswith("ion"):
        stem = word[:-3]
        if _measure(stem) > 1 and stem and stem[-1] in "st":
            word = stem

    # ---------- Step 5a ----------
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _ends_cvc(stem)):
            word = stem

    # ---------- Step 5b ----------
    if word.endswith("ll") and _measure(word[:-1]) > 1:
        word = word[:-1]

    return word
