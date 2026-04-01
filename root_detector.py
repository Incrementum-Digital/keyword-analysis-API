"""
Root Keyword Detector

Ported from CampaignForge rootDetector.ts
Detects common root keywords/phrases in a keyword list and assigns keywords to roots.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional
from collections import defaultdict


@dataclass
class Keyword:
    """Keyword with normalized text and search volume."""
    id: str
    normalized_text: str
    search_volume: int
    original_text: str = ""


@dataclass
class RootGroup:
    """A detected root keyword group."""
    name: str
    is_selected: bool = False
    keyword_ids: List[str] = field(default_factory=list)
    total_sv: int = 0
    frequency: int = 0


@dataclass
class NgramEntry:
    """Internal structure for n-gram frequency tracking."""
    ngram: str
    count: int = 0
    total_sv: int = 0
    keyword_ids: List[str] = field(default_factory=list)


def detect_roots(keywords: List[Keyword]) -> List[RootGroup]:
    """
    Detect potential root keywords from a list of keywords.

    Analyzes 1-gram, 2-gram, and 3-gram phrases to find common roots.
    Returns all candidates sorted by frequency and search volume.

    Args:
        keywords: List of keywords with normalized text

    Returns:
        List of RootGroup objects, sorted by frequency (desc) then total SV (desc)
    """
    freq_map: Dict[str, NgramEntry] = {}

    for kw in keywords:
        # Split into words, filtering short words
        words = [w for w in kw.normalized_text.lower().split() if len(w) >= 2]

        # Generate 1-gram, 2-gram, and 3-gram phrases
        for n in range(1, 4):
            for i in range(len(words) - n + 1):
                ngram = ' '.join(words[i:i + n])

                if ngram not in freq_map:
                    freq_map[ngram] = NgramEntry(ngram=ngram)

                entry = freq_map[ngram]
                if kw.id not in entry.keyword_ids:
                    entry.count += 1
                    entry.total_sv += kw.search_volume
                    entry.keyword_ids.append(kw.id)

    # Filter: must appear in at least 2 keywords
    candidates = [e for e in freq_map.values() if e.count >= 2]

    # Sort by frequency desc, then by total SV desc
    candidates.sort(key=lambda c: (-c.count, -c.total_sv))

    # Convert to RootGroup format
    roots = [
        RootGroup(
            name=c.ngram,
            is_selected=False,  # User selects which roots to use
            keyword_ids=c.keyword_ids,
            total_sv=c.total_sv,
            frequency=c.count,
        )
        for c in candidates
    ]

    return roots


def assign_keywords_to_roots(
    keywords: List[Keyword],
    root_groups: List[RootGroup],
    selected_root_names: Optional[Set[str]] = None
) -> Dict[str, str]:
    """
    Assign each keyword to a root group.

    Each keyword is assigned to the most specific (longest) matching root.
    Keywords not matching any root are assigned to 'Mixed Roots'.

    Args:
        keywords: List of keywords to assign
        root_groups: Available root groups
        selected_root_names: Optional set of selected root names (if None, all are considered)

    Returns:
        Dict mapping keyword_id -> root_name
    """
    assignments: Dict[str, str] = {}

    # Sort roots by specificity: longer name = more specific
    # Only consider selected roots if filter is provided
    sorted_roots = [
        r for r in root_groups
        if selected_root_names is None or r.name in selected_root_names
    ]

    # Sort by word count (desc), then by keyword count (asc, smaller set wins), then name (asc)
    sorted_roots.sort(key=lambda r: (-len(r.name.split()), len(r.keyword_ids), r.name))

    for kw in keywords:
        normalized_lower = kw.normalized_text.lower()
        assigned = False

        for root in sorted_roots:
            if root.name.lower() in normalized_lower:
                assignments[kw.id] = root.name
                assigned = True
                break

        if not assigned:
            assignments[kw.id] = 'Mixed Roots'

    return assignments


def get_keywords_by_root(
    keywords: List[Keyword],
    assignments: Dict[str, str]
) -> Dict[str, List[Keyword]]:
    """
    Group keywords by their assigned root.

    Args:
        keywords: List of keywords
        assignments: Mapping of keyword_id -> root_name

    Returns:
        Dict mapping root_name -> list of keywords
    """
    by_root: Dict[str, List[Keyword]] = defaultdict(list)

    for kw in keywords:
        root = assignments.get(kw.id, 'Mixed Roots')
        by_root[root].append(kw)

    return dict(by_root)
