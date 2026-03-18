#!/usr/bin/env python3
"""Derive normalized root statistics from a keyword CSV.

The script now keeps a companion configuration file that stores additional
stopwords and irregular singular mappings discovered while processing new
keyword lists.  Each time it runs it can extend that file automatically based
on simple heuristics so future runs benefit from the expanded vocabulary.
"""
import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

# --------- Defaults & configuration handling ---------------------------------

DEFAULT_STOPWORDS: Set[str] = {
    "and",
    "for",
    "of",
    "on",
    "with",
    "the",
    "a",
    "an",
    "mega",
}

DEFAULT_IRREGULAR_SINGULARS: Dict[str, str] = {
    "men": "man",
    "mens": "man",
    "women": "woman",
    "womens": "woman",
    "teeth": "tooth",
    "feet": "foot",
    "people": "person",
    "humans": "human",
    "kids": "kid",
    "omegas": "omegas",
    "lbs": "lb",
    "iris": "iris",
    "homeplus": "homeplus",
    # Compound irregular plurals
    "snowmen": "snowman",
    "snowmens": "snowman",
    "gentlemen": "gentleman",
    "businessmen": "businessman",
    "salesmen": "salesman",
    "firemen": "fireman",
    "policemen": "policeman",
    "fishermen": "fisherman",
    "sportsmen": "sportsman",
    "workmen": "workman",
    "craftsmen": "craftsman",
    "spokesmen": "spokesman",
    "chairmen": "chairman",
    "congressmen": "congressman",
    "servicemen": "serviceman",
    "newsmen": "newsman",
    "stuntmen": "stuntman",
    "doormen": "doorman",
    "watchmen": "watchman",
    "horsemen": "horseman",
    "countrymen": "countryman",
    # Words ending in 's' that are NOT plurals (should not be singularized)
    "christmas": "christmas",
    "xmas": "xmas",
    "series": "series",
    "species": "species",
    "news": "news",
    "means": "means",
    "plus": "plus",
    "bus": "bus",
    "lens": "lens",
    "canvas": "canvas",
    "status": "status",
    "virus": "virus",
    "bonus": "bonus",
    "focus": "focus",
    "campus": "campus",
    "citrus": "citrus",
    "radius": "radius",
    "genius": "genius",
    "census": "census",
    "cactus": "cactus",
    "fungus": "fungus",
    "mucus": "mucus",
    "nexus": "nexus",
    "sinus": "sinus",
    "lotus": "lotus",
    "hiatus": "hiatus",
    "fetus": "fetus",
    "apparatus": "apparatus",
    "stimulus": "stimulus",
    "consensus": "consensus",
    "corpus": "corpus",
    "compass": "compass",
    "surplus": "surplus",
    "tennis": "tennis",
    "axis": "axis",
    "basis": "basis",
    "oasis": "oasis",
    "crisis": "crisis",
    "thesis": "thesis",
    "pelvis": "pelvis",
    "cannabis": "cannabis",
    "analysis": "analysis",
    "diagnosis": "diagnosis",
    "emphasis": "emphasis",
    "hypothesis": "hypothesis",
    "synthesis": "synthesis",
    "paralysis": "paralysis",
    "metamorphosis": "metamorphosis",
    "gas": "gas",
    "atlas": "atlas",
    "chaos": "chaos",
    "ethos": "ethos",
    "pathos": "pathos",
    "cosmos": "cosmos",
    "rhinoceros": "rhinoceros",
    "lass": "lass",
    "lass": "lass",
    "class": "class",
    "glass": "glass",
    "grass": "grass",
    "brass": "brass",
    "mass": "mass",
    "pass": "pass",
    "boss": "boss",
    "loss": "loss",
    "moss": "moss",
    "toss": "toss",
    "cross": "cross",
    "gross": "gross",
    "dress": "dress",
    "press": "press",
    "stress": "stress",
    "bless": "bless",
    "chess": "chess",
    "mess": "mess",
    "less": "less",
    "guess": "guess",
    "success": "success",
    "access": "access",
    "process": "process",
    "progress": "progress",
    "address": "address",
    "express": "express",
    "compress": "compress",
    "impress": "impress",
    "possess": "possess",
    "business": "business",
    "fitness": "fitness",
    "illness": "illness",
    "wellness": "wellness",
    "darkness": "darkness",
    "weakness": "weakness",
    "kindness": "kindness",
    "happiness": "happiness",
    "sadness": "sadness",
    "madness": "madness",
    "awareness": "awareness",
    "wireless": "wireless",
    "stainless": "stainless",
    "seamless": "seamless",
    "cordless": "cordless",
    "endless": "endless",
    "harmless": "harmless",
    "homeless": "homeless",
    "helpless": "helpless",
    "hopeless": "hopeless",
    "useless": "useless",
    "careless": "careless",
    "priceless": "priceless",
    "timeless": "timeless",
    "flawless": "flawless",
    "effortless": "effortless",
    "weightless": "weightless",
    "breathless": "breathless",
    "relentless": "relentless",
    "restless": "restless",
    "fearless": "fearless",
    "odorless": "odorless",
    "colorless": "colorless",
    "sugarless": "sugarless",
    "waterless": "waterless",
    "powerless": "powerless",
}

# Irregulars that we can recognise automatically even if they are not yet in
# the configuration file. These map the observed token to the singular form.
AUTO_IRREGULAR_LOOKUP: Dict[str, str] = {
    "children": "child",
    "geese": "goose",
    "mice": "mouse",
    "lice": "louse",
    "oxen": "ox",
    "indices": "index",
    "appendices": "appendix",
    "matrices": "matrix",
    "vertices": "vertex",
    "analyses": "analysis",
    "crises": "crisis",
    "diagnoses": "diagnosis",
    "theses": "thesis",
    "phenomena": "phenomenon",
    "criteria": "criterion",
    "algae": "alga",
    "fungi": "fungus",
    "cacti": "cactus",
    "nuclei": "nucleus",
    "syllabi": "syllabus",
}

AUTO_STOPWORD_THRESHOLD_DEFAULT = 0.9
CONFIG_PATH = Path(__file__).with_name("root_analysis_config.json")
NON_WORD_RE = re.compile(r"[^\w]+", flags=re.UNICODE)
DECIMAL_PATTERN = re.compile(r"\d+\.\d+")


def load_config() -> Dict[str, object]:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    else:
        config = {}

    config.setdefault("stopwords", [])
    config.setdefault("irregular_singulars", {})
    auto_section = config.setdefault("auto", {})
    auto_section.setdefault("stopword_threshold", AUTO_STOPWORD_THRESHOLD_DEFAULT)
    return config


def save_config(config: Dict[str, object]) -> None:
    # Normalise ordering for readability.
    stopwords = sorted(set(config.get("stopwords", [])))
    irregulars = dict(sorted(config.get("irregular_singulars", {}).items()))
    config = {
        "stopwords": stopwords,
        "irregular_singulars": irregulars,
        "auto": config.get("auto", {"stopword_threshold": AUTO_STOPWORD_THRESHOLD_DEFAULT}),
    }
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, sort_keys=True)
        handle.write("\n")


# --------- Token normalisation helpers ---------------------------------------

def singularize(token: str, irregular_map: Dict[str, str]) -> str:
    """Convert a plural word to its singular form using rule-based approach.

    Matches DataDive's singularization behavior:
    - Uses irregular_map for exceptions (christmas, xmas, series, etc.)
    - Applies standard English plural rules for everything else
    """
    if token in irregular_map:
        return irregular_map[token]

    candidate = token
    if candidate.endswith("ies") and len(candidate) > 3:
        candidate = candidate[:-3] + "y"
    elif candidate.endswith("ses") and len(candidate) > 3:
        candidate = candidate[:-2]
    elif candidate.endswith("xes") and len(candidate) > 3:
        candidate = candidate[:-2]
    elif candidate.endswith("zes") and len(candidate) > 3:
        candidate = candidate[:-2]
    elif candidate.endswith("ches") and len(candidate) > 3:
        candidate = candidate[:-2]
    elif candidate.endswith("shes") and len(candidate) > 3:
        candidate = candidate[:-2]
    elif candidate.endswith("oes") and len(candidate) > 3:
        candidate = candidate[:-2]
    elif candidate.endswith("s") and len(candidate) > 3 and not candidate.endswith("ss"):
        candidate = candidate[:-1]

    return irregular_map.get(candidate, candidate)


def tokenize(term: str, irregular_map: Dict[str, str]) -> Tuple[List[str], List[str]]:
    lowered = term.lower()
    placeholder_map: Dict[str, str] = {}

    def replace_decimal(match: re.Match[str]) -> str:
        decimal = match.group(0)
        placeholder = f"decimalplaceholder{len(placeholder_map)}"
        placeholder_map[placeholder] = decimal
        return placeholder

    prepped = DECIMAL_PATTERN.sub(replace_decimal, lowered)
    cleaned = NON_WORD_RE.sub(" ", prepped).strip()
    if not cleaned:
        return [], []

    raw_tokens = cleaned.split()
    restored_raw = [placeholder_map.get(token, token) for token in raw_tokens]

    normalized: List[str] = []
    for raw in restored_raw:
        normalized_token = singularize(raw, irregular_map) if raw not in placeholder_map.values() else raw
        if normalized_token:
            normalized.append(normalized_token)

    return normalized, restored_raw


# --------- CSV ingestion -----------------------------------------------------

def iter_rows(path: str) -> Iterable[Tuple[str, int]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return
        for row in reader:
            if not row or len(row) < 3:
                continue
            term = row[1].strip()
            if not term:
                continue
            try:
                volume = int(row[2])
            except ValueError:
                continue
            yield term, volume


# --------- Auto learning logic ----------------------------------------------

def preprocess_tokens(
    rows: Sequence[Tuple[str, int]],
    irregular_map: Dict[str, str],
) -> Tuple[List[Tuple[List[str], int]], collections.Counter, Set[str], Set[str]]:
    tokens_per_row: List[Tuple[List[str], int]] = []
    doc_freq: collections.Counter = collections.Counter()
    normalized_token_set: Set[str] = set()
    raw_token_set: Set[str] = set()

    for term, volume in rows:
        tokens, raw_tokens = tokenize(term, irregular_map)
        raw_token_set.update(raw_tokens)

        tokens_per_row.append((tokens, volume))
        if tokens:
            unique_tokens = set(tokens)
            doc_freq.update(unique_tokens)
            normalized_token_set.update(unique_tokens)

    return tokens_per_row, doc_freq, normalized_token_set, raw_token_set


def detect_new_irregulars(
    raw_token_set: Set[str],
    normalized_token_set: Set[str],
    irregular_map: Dict[str, str],
) -> Dict[str, str]:
    new_entries: Dict[str, str] = {}
    for raw_token in raw_token_set:
        token = raw_token.lower()
        if token in irregular_map or token in new_entries:
            continue
        if token in AUTO_IRREGULAR_LOOKUP:
            new_entries[token] = AUTO_IRREGULAR_LOOKUP[token]
            continue

        if token.endswith("ves") and len(token) > 3:
            stem = token[:-3]
            for candidate in (stem + "f", stem + "fe"):
                if candidate in raw_token_set or candidate in normalized_token_set:
                    new_entries[token] = candidate
                    break
    return new_entries


def detect_new_stopwords(
    doc_freq: collections.Counter,
    total_keywords: int,
    stopwords: Set[str],
    threshold: float,
    root_freq: collections.Counter,
) -> Set[str]:
    if total_keywords == 0:
        return set()

    new_stopwords: Set[str] = set()
    for token, count in doc_freq.items():
        if token in stopwords:
            continue
        if token in root_freq:
            continue
        ratio = count / total_keywords
        if ratio >= threshold and token.isalpha() and len(token) <= 4:
            new_stopwords.add(token)
    return new_stopwords


# --------- Aggregation logic -------------------------------------------------

def build_stats(
    tokens_per_row: Sequence[Tuple[List[str], int]],
    stopwords: Set[str],
) -> Tuple[collections.Counter, collections.Counter, Dict[str, int]]:
    freq = collections.Counter()
    sv_sum = collections.Counter()
    first_seen: Dict[str, int] = {}
    order = 0

    for tokens, volume in tokens_per_row:
        filtered = [token for token in tokens if token not in stopwords]
        if not filtered:
            continue
        seen_in_term: Set[str] = set()
        for start in range(len(filtered)):
            for end in range(start + 1, len(filtered) + 1):
                key = " ".join(filtered[start:end])
                if key in seen_in_term:
                    continue
                seen_in_term.add(key)
                freq[key] += 1
                sv_sum[key] += volume
                if key not in first_seen:
                    first_seen[key] = order
                    order += 1

    return freq, sv_sum, first_seen


def filter_terms(
    freq: collections.Counter,
    sv_sum: collections.Counter,
    first_seen: Dict[str, int],
) -> List[str]:
    candidates = [term for term in freq if not (len(term.split()) > 1 and freq[term] == 1)]

    terms_by_length: Dict[int, List[str]] = collections.defaultdict(list)
    for term in candidates:
        terms_by_length[len(term.split())].append(term)
    max_length = max(terms_by_length, default=0)

    keep = set(candidates)
    for length in range(1, max_length):
        for term in terms_by_length.get(length, []):
            if term not in keep:
                continue
            tokens = term.split()
            target_freq = freq[term]
            target_sv = sv_sum[term]
            removed = False
            for longer_length in range(length + 1, max_length + 1):
                for candidate in terms_by_length.get(longer_length, []):
                    if candidate not in keep:
                        continue
                    c_tokens = candidate.split()
                    for start in range(len(c_tokens) - length + 1):
                        if c_tokens[start : start + length] == tokens and freq[candidate] == target_freq and sv_sum[candidate] == target_sv:
                            keep.discard(term)
                            removed = True
                            break
                    if removed:
                        break
                if removed:
                    break

    terms = list(keep)
    terms.sort(key=lambda term: first_seen.get(term, 0))
    terms.sort(key=lambda term: sv_sum[term], reverse=True)
    terms.sort(key=lambda term: freq[term], reverse=True)
    return terms


def build_simple_stats(
    tokens_per_row: Sequence[Tuple[List[str], int]],
    stopwords: Set[str],
) -> Tuple[List[str], collections.Counter, collections.Counter]:
    sv_sum = collections.Counter()
    freq = collections.Counter()
    first_seen: Dict[str, int] = {}

    for tokens, volume in tokens_per_row:
        filtered = [token for token in tokens if token not in stopwords]
        if not filtered:
            continue
        key = " ".join(filtered)
        sv_sum[key] += volume
        freq[key] += 1
        first_seen.setdefault(key, len(first_seen))

    ordered_terms = sorted(sv_sum.keys(), key=lambda term: (-sv_sum[term], first_seen[term]))
    return ordered_terms, sv_sum, freq


def write_full_output(
    path: str,
    ordered_terms: List[str],
    freq: collections.Counter,
    sv_sum: collections.Counter,
) -> None:
    if not ordered_terms:
        raise ValueError("No terms generated from input")

    max_sv = max(sv_sum[term] for term in ordered_terms)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(["", "Normalized Root", "Frequency", "Broad Search Volume", ""])
        for term in ordered_terms:
            volume = sv_sum[term]
            ratio = volume / max_sv if max_sv else 0.0
            ratio_str = str(ratio)
            if ratio_str.endswith(".0"):
                ratio_str = ratio_str[:-2]
            writer.writerow(["", term, str(freq[term]), str(volume), ratio_str])


def write_simple_output(
    path: str,
    ordered_terms: List[str],
    sv_sum: collections.Counter,
) -> None:
    if not ordered_terms:
        raise ValueError("No terms generated from input")

    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(["Unique Normalized Keywords", "Consolidated Search Volume"])
        for term in ordered_terms:
            writer.writerow([term, str(sv_sum[term])])


# --------- Entry point -------------------------------------------------------

def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate normalized root analysis from a keyword CSV",
    )
    parser.add_argument("keywords_csv", help="Path to the keyword export CSV")
    parser.add_argument("output_csv", help="Path to write the generated root analysis CSV")
    parser.add_argument(
        "--mode",
        choices=["full", "simple"],
        default="full",
        help="Output mode: 'full' matches the detailed root analysis (default), 'simple' matches the consolidated volume format",
    )
    return parser.parse_args(argv[1:])


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    input_path, output_path = args.keywords_csv, args.output_csv
    rows = list(iter_rows(input_path))
    if not rows:
        print("No keyword rows found in input", file=sys.stderr)
        return 1

    config = load_config()
    stopwords: Set[str] = set(DEFAULT_STOPWORDS)
    stopwords.update(config.get("stopwords", []))
    irregular_map: Dict[str, str] = dict(DEFAULT_IRREGULAR_SINGULARS)
    irregular_map.update(config.get("irregular_singulars", {}))
    threshold = float(config.get("auto", {}).get("stopword_threshold", AUTO_STOPWORD_THRESHOLD_DEFAULT))

    (
        tokens_per_row,
        doc_freq,
        normalized_token_set,
        raw_token_set,
    ) = preprocess_tokens(rows, irregular_map)

    if args.mode == "full":
        freq, sv_sum, first_seen = build_stats(tokens_per_row, stopwords)
        ordered_terms = filter_terms(freq, sv_sum, first_seen)
        write_full_output(output_path, ordered_terms, freq, sv_sum)
        root_freq = freq
    else:
        ordered_terms, sv_sum, simple_freq = build_simple_stats(tokens_per_row, stopwords)
        write_simple_output(output_path, ordered_terms, sv_sum)
        root_freq = simple_freq

    new_irregulars = detect_new_irregulars(raw_token_set, normalized_token_set, irregular_map)
    new_stopwords = detect_new_stopwords(doc_freq, len(rows), stopwords, threshold, root_freq)

    if new_irregulars or new_stopwords:
        if new_irregulars:
            config.setdefault("irregular_singulars", {}).update(new_irregulars)
        if new_stopwords:
            existing = set(config.get("stopwords", []))
            existing.update(new_stopwords)
            config["stopwords"] = sorted(existing)
        save_config(config)
        if new_stopwords:
            msg = ", ".join(sorted(new_stopwords))
            print(f"[auto-config] added stopwords: {msg}", file=sys.stderr)
        if new_irregulars:
            msg = ", ".join(f"{k}->{v}" for k, v in sorted(new_irregulars.items()))
            print(f"[auto-config] added irregulars: {msg}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
