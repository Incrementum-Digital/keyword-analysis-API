"""
Campaign Generator

Ported from CampaignForge campaignGenerator.ts
Generates Amazon PPC campaigns from keywords based on configuration.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from decimal import Decimal
from datetime import datetime
import uuid

from root_detector import Keyword, RootGroup, assign_keywords_to_roots, detect_roots
from naming_engine import NamingTemplate, NamingContext, generate_campaign_name


@dataclass
class SVTier:
    """Search volume tier configuration."""
    id: str
    label: str
    min_sv: int
    max_sv: int
    max_keywords: int = 10


@dataclass
class MatchTypeConfig:
    """Configuration for a specific match type."""
    enabled: bool = True
    sv_tiers: List[SVTier] = field(default_factory=list)
    daily_budget: Decimal = Decimal("20.00")
    default_bid: Decimal = Decimal("0.67")
    keyword_bid: Decimal = Decimal("0.67")
    bidding_strategy: str = "Fixed"
    start_date: str = ""
    status: str = "Enabled"
    max_kw_per_campaign: int = 10


@dataclass
class Campaign:
    """Generated campaign."""
    id: str
    name: str
    match_type: str
    root_group: Optional[str]
    keyword_ids: List[str]
    daily_budget: Decimal
    default_bid: Decimal
    keyword_bid: Decimal
    bidding_strategy: str
    start_date: str
    status: str
    is_solo: bool = False
    is_auto: bool = False
    sv_tier: Optional[str] = None


@dataclass
class ManualCampaignGroup:
    """Manual campaign group (for custom/product/auto targeting)."""
    id: int
    name: str
    keyword_ids: List[str]


@dataclass
class GenerateInput:
    """Input for campaign generation."""
    keywords: List[Keyword]
    targeting_selections: Dict[str, List[str]]  # keyword_id -> list of match types
    match_type_configs: Dict[str, MatchTypeConfig]
    root_groups: List[RootGroup]
    selected_roots_by_match_type: Dict[str, List[str]]  # match_type -> list of root names
    solo_keyword_ids: List[str]
    include_ungrouped: bool = True
    manual_campaign_groups: Dict[str, List[ManualCampaignGroup]] = field(default_factory=dict)
    sku: str = ""
    naming_template: NamingTemplate = None

    def __post_init__(self):
        if self.naming_template is None:
            self.naming_template = NamingTemplate(
                tokens=["SKU", "SP", "MATCH", "ROOT"],
                separator="_"
            )


def _gen_id() -> str:
    """Generate unique campaign ID."""
    return f"camp_{uuid.uuid4().hex[:8]}_{int(datetime.now().timestamp())}"


def generate_campaigns(input_data: GenerateInput) -> List[Campaign]:
    """
    Generate campaigns from keywords based on configuration.

    This implements the core campaign generation algorithm:
    1. For each enabled match type (Exact, Phrase, Broad):
       - Assign keywords to roots based on selected roots for that match type
       - Create solo campaigns for keywords marked as solo
       - Group remaining keywords by root
       - Split large groups by SV tier limits
    2. For manual campaign groups (Product, Auto, custom):
       - Create campaigns as specified

    Args:
        input_data: Generation configuration and data

    Returns:
        List of generated Campaign objects
    """
    campaigns: List[Campaign] = []
    sku = input_data.sku
    naming_template = input_data.naming_template

    # Standard keyword match types
    standard_match_types = ['exact', 'phrase', 'broad']

    for match_type in standard_match_types:
        config = input_data.match_type_configs.get(match_type)
        if not config or not config.enabled:
            continue

        selected_root_names = set(
            input_data.selected_roots_by_match_type.get(match_type, [])
        )

        # Assign keywords to roots using only the roots selected for this match type
        assignments = assign_keywords_to_roots(
            input_data.keywords,
            input_data.root_groups,
            selected_root_names if selected_root_names else None
        )

        # Get keywords that have this match type selected
        match_keywords = [
            kw for kw in input_data.keywords
            if match_type in [mt.lower() for mt in input_data.targeting_selections.get(kw.id, [])]
        ]

        # Separate solo vs grouped keywords
        solo_kws = [
            kw for kw in match_keywords
            if kw.id in input_data.solo_keyword_ids
        ]

        # Grouped keywords
        if selected_root_names:
            # If roots are selected, include keywords in those roots + ungrouped if flag is set
            grouped_kws = [
                kw for kw in match_keywords
                if kw.id not in input_data.solo_keyword_ids
                and (
                    assignments.get(kw.id) in selected_root_names
                    or (input_data.include_ungrouped and assignments.get(kw.id) == 'Mixed Roots')
                )
            ]
        elif input_data.include_ungrouped:
            # No roots selected but include_ungrouped is True: treat ALL non-solo keywords as ungrouped
            grouped_kws = [
                kw for kw in match_keywords
                if kw.id not in input_data.solo_keyword_ids
            ]
        else:
            grouped_kws = []

        # Create solo campaigns - one per keyword
        for kw in solo_kws:
            campaigns.append(Campaign(
                id=_gen_id(),
                name=generate_campaign_name(
                    naming_template,
                    NamingContext(
                        sku=sku,
                        match_type=match_type,
                        root_group=kw.normalized_text,
                        date=config.start_date,
                    )
                ),
                match_type=match_type,
                root_group=assignments.get(kw.id, 'Solo'),
                keyword_ids=[kw.id],
                daily_budget=config.daily_budget,
                default_bid=config.default_bid,
                keyword_bid=config.keyword_bid,
                bidding_strategy=config.bidding_strategy,
                start_date=config.start_date,
                status=config.status,
                is_solo=True,
                is_auto=False,
            ))

        # Group keywords by root
        by_root: Dict[str, List[Keyword]] = {}
        for kw in grouped_kws:
            root = assignments.get(kw.id, 'Mixed Roots')
            if root not in by_root:
                by_root[root] = []
            by_root[root].append(kw)

        # Create campaigns per root, splitting by SV tier limits
        for root_name, root_kws in by_root.items():
            # Sort by SV descending within root
            root_kws.sort(key=lambda k: k.search_volume, reverse=True)

            # Determine tiers
            tiers = config.sv_tiers if config.sv_tiers else [
                SVTier(
                    id='default',
                    label='All',
                    min_sv=0,
                    max_sv=float('inf'),
                    max_keywords=config.max_kw_per_campaign
                )
            ]

            # Bucket keywords into tiers, then chunk each tier by maxKeywords
            all_chunks: List[tuple] = []  # (tier_label, keywords)
            assigned: Set[str] = set()

            for tier in tiers:
                tier_kws = [
                    kw for kw in root_kws
                    if kw.id not in assigned
                    and kw.search_volume >= tier.min_sv
                    and kw.search_volume <= tier.max_sv
                ]
                for kw in tier_kws:
                    assigned.add(kw.id)

                # Chunk by max_keywords
                for i in range(0, len(tier_kws), tier.max_keywords):
                    chunk = tier_kws[i:i + tier.max_keywords]
                    all_chunks.append((tier.label, chunk))

            # Catch any keywords that didn't fall into a tier
            uncaught = [kw for kw in root_kws if kw.id not in assigned]
            if uncaught:
                fallback_max = tiers[-1].max_keywords if tiers else config.max_kw_per_campaign
                for i in range(0, len(uncaught), fallback_max):
                    all_chunks.append(('All', uncaught[i:i + fallback_max]))

            # Create campaigns from chunks
            for idx, (tier_label, chunk_kws) in enumerate(all_chunks):
                campaigns.append(Campaign(
                    id=_gen_id(),
                    name=generate_campaign_name(
                        naming_template,
                        NamingContext(
                            sku=sku,
                            match_type=match_type,
                            root_group=root_name,
                            tier=tier_label if len(tiers) > 1 else None,
                            date=config.start_date,
                            index=idx if len(all_chunks) > 1 else None,
                        )
                    ),
                    match_type=match_type,
                    root_group=root_name,
                    keyword_ids=[kw.id for kw in chunk_kws],
                    daily_budget=config.daily_budget,
                    default_bid=config.default_bid,
                    keyword_bid=config.keyword_bid,
                    bidding_strategy=config.bidding_strategy,
                    start_date=config.start_date,
                    status=config.status,
                    is_solo=False,
                    is_auto=False,
                    sv_tier=tier_label,
                ))

    # Manual campaign groups (Product, Auto, custom configurations)
    all_manual_types = ['exact', 'phrase', 'broad', 'product', 'auto']
    for match_type in all_manual_types:
        config = input_data.match_type_configs.get(match_type)
        if not config or not config.enabled:
            continue

        groups = input_data.manual_campaign_groups.get(match_type, [])
        for i, group in enumerate(groups):
            if not group.keyword_ids:
                continue

            group_name = group.name or f'Custom_{i + 1}'

            campaigns.append(Campaign(
                id=_gen_id(),
                name=generate_campaign_name(
                    naming_template,
                    NamingContext(
                        sku=sku,
                        match_type=match_type,
                        root_group=group_name,
                        date=config.start_date,
                    )
                ),
                match_type=match_type,
                root_group=group_name,
                keyword_ids=[] if match_type == 'auto' else group.keyword_ids,
                daily_budget=config.daily_budget,
                default_bid=config.default_bid,
                keyword_bid=config.keyword_bid,
                bidding_strategy=config.bidding_strategy,
                start_date=config.start_date,
                status=config.status,
                is_solo=False,
                is_auto=match_type == 'auto',
            ))

    return campaigns


def detect_roots_from_keywords(keywords: List[Keyword]) -> List[RootGroup]:
    """
    Convenience function to detect roots from a keyword list.

    Args:
        keywords: List of keywords

    Returns:
        List of detected RootGroup objects
    """
    return detect_roots(keywords)
