"""
Keyword Normalizer

Ported from CampaignForge normalizer.ts
Handles plural/singular normalization and filler word removal.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple


# Common filler words to remove
FILLER_WORDS: Set[str] = {'for', 'with', 'the', 'a', 'an', 'of', 'to', 'in', 'on'}


def singularize(word: str) -> str:
    """
    Convert a word to its singular form using basic English rules.

    Handles common plural patterns:
    - -ies → -y (batteries → battery)
    - -ses, -xes, -zes, -ches, -shes → remove -es
    - -s → remove s (but not -ss, -us)
    """
    lower = word.lower()

    # Words ending in -ies (batteries → battery)
    if lower.endswith('ies') and len(lower) > 4:
        return word[:-3] + 'y'

    # Words ending in -ses, -xes, -zes, -ches, -shes
    if (lower.endswith('ses') or lower.endswith('xes') or
        lower.endswith('zes') or lower.endswith('ches') or
        lower.endswith('shes')):
        return word[:-2]

    # General -s ending (but not -ss or -us)
    if lower.endswith('s') and not lower.endswith('ss') and not lower.endswith('us') and len(lower) > 3:
        return word[:-1]

    return word


def normalize_text(text: str) -> Tuple[str, List[str]]:
    """
    Normalize keyword text by removing filler words and singularizing.

    Returns:
        Tuple of (normalized_text, list_of_reasons)
    """
    reasons: List[str] = []
    words = text.lower().strip().split()

    # Remove filler words
    filtered = [w for w in words if w not in FILLER_WORDS]
    removed_fillers = [w for w in words if w in FILLER_WORDS]

    if removed_fillers and filtered:
        words = filtered
        reasons.append(f"Filler: {', '.join(removed_fillers)}")

    # Singularize each word
    singularized = [singularize(w) for w in words]
    changed_words = [w for w, s in zip(words, singularized) if w != s]

    if changed_words:
        reasons.append('Plural → Singular')

    return ' '.join(singularized), reasons


@dataclass
class RawKeyword:
    """Input keyword with ID and search volume."""
    id: str
    text: str
    search_volume: int


@dataclass
class NormVariant:
    """A keyword variant within a normalization group."""
    keyword: RawKeyword
    reason: str
    is_merged: bool = True


@dataclass
class NormGroup:
    """Group of keywords that normalize to the same text."""
    id: str
    normalized_text: str
    combined_search_volume: int
    variants: List[NormVariant] = field(default_factory=list)
    is_included: bool = True


_group_id_counter = 0


def normalize_keywords(raw_keywords: List[RawKeyword]) -> List[NormGroup]:
    """
    Normalize a list of keywords into groups.

    Keywords that normalize to the same text are grouped together.
    The keyword with highest search volume becomes the primary variant.

    Args:
        raw_keywords: List of keywords with id, text, and search_volume

    Returns:
        List of NormGroup objects sorted by combined search volume
    """
    global _group_id_counter
    _group_id_counter = 0

    # Map: normalized_text -> (keywords, reasons per keyword)
    group_map: Dict[str, Dict] = {}

    for kw in raw_keywords:
        normalized, reasons = normalize_text(kw.text)

        if normalized not in group_map:
            group_map[normalized] = {
                'keywords': [],
                'reasons': {}
            }

        group = group_map[normalized]
        group['keywords'].append(kw)
        group['reasons'][kw.id] = reasons

    groups: List[NormGroup] = []

    for normalized_text, data in group_map.items():
        keywords = data['keywords']
        reasons_map = data['reasons']

        # Sort by search volume descending - first keyword is the "parent"
        keywords.sort(key=lambda k: k.search_volume, reverse=True)

        variants: List[NormVariant] = []
        for i, kw in enumerate(keywords):
            kw_reasons = reasons_map.get(kw.id, [])
            is_original_kept = i == 0 and len(kw_reasons) == 0

            if is_original_kept:
                reason = 'Original · Kept'
            elif kw_reasons:
                reason = ', '.join(kw_reasons)
            elif i == 0:
                reason = 'Original · Kept'
            else:
                reason = 'Duplicate'

            variants.append(NormVariant(
                keyword=kw,
                reason=reason,
                is_merged=i > 0  # All except the first (highest SV) are merged
            ))

        _group_id_counter += 1
        groups.append(NormGroup(
            id=f'norm_{_group_id_counter}',
            normalized_text=normalized_text,
            combined_search_volume=sum(kw.search_volume for kw in keywords),
            variants=variants,
            is_included=True
        ))

    # Sort groups by combined search volume descending
    groups.sort(key=lambda g: g.combined_search_volume, reverse=True)

    return groups


def groups_to_dict(groups: List[NormGroup]) -> List[Dict]:
    """Convert NormGroup list to JSON-serializable dict format."""
    return [
        {
            'id': g.id,
            'normalized_text': g.normalized_text,
            'combined_search_volume': g.combined_search_volume,
            'variants': [
                {
                    'keyword': v.keyword.text,
                    'keyword_id': v.keyword.id,
                    'search_volume': v.keyword.search_volume,
                    'reason': v.reason,
                    'is_merged': v.is_merged
                }
                for v in g.variants
            ],
            'is_included': g.is_included
        }
        for g in groups
    ]
