"""
Bulk Sheet Exporter

Ported from CampaignForge bulkSheetExporter.ts
Generates Amazon SP bulk sheet XLSX files for campaign upload.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from decimal import Decimal
from io import BytesIO
import openpyxl
from openpyxl import Workbook


# All auto targeting types
ALL_AUTO_TARGETS = ['close_match', 'loose_match', 'substitutes', 'complements']

AUTO_TARGET_EXPRESSIONS: Dict[str, str] = {
    'close_match': 'close-match',
    'loose_match': 'loose-match',
    'substitutes': 'substitutes',
    'complements': 'complements',
}

# Amazon SP Bulk Sheet column order
COLUMNS = [
    'Product',
    'Entity',
    'Operation',
    'Campaign Id',
    'Ad Group Id',
    'Portfolio Id',
    'Ad Id (Read only)',
    'Keyword Id (Read only)',
    'Product Targeting Id (Read only)',
    'Campaign Name',
    'Ad Group Name',
    'Start Date',
    'End Date',
    'Targeting Type',
    'State',
    'Daily Budget',
    'SKU',
    'ASIN',
    'Ad Group Default Bid',
    'Bid',
    'Keyword Text',
    'Match Type',
    'Bidding Strategy',
    'Placement',
    'Percentage',
    'Product Targeting Expression',
]


@dataclass
class Keyword:
    """Keyword data for export."""
    id: str
    normalized_text: str
    original_text: str = ""
    search_volume: int = 0


@dataclass
class Campaign:
    """Campaign data for export."""
    id: str
    name: str
    match_type: str
    keyword_ids: List[str]
    daily_budget: Decimal
    default_bid: Decimal
    keyword_bid: Decimal
    bidding_strategy: str
    start_date: str
    status: str
    is_solo: bool = False
    is_auto: bool = False
    root_group: Optional[str] = None


@dataclass
class CampaignOverride:
    """Per-campaign overrides."""
    daily_budget: Optional[Decimal] = None
    paused_keyword_ids: Set[str] = field(default_factory=set)
    keyword_bids: Dict[str, Decimal] = field(default_factory=dict)


@dataclass
class CampaignNegatives:
    """Negative keywords for a campaign."""
    exact: List[str] = field(default_factory=list)
    phrase: List[str] = field(default_factory=list)


@dataclass
class ExportOptions:
    """Options for bulk sheet export."""
    include_campaign_rows: bool = True
    include_ad_group_rows: bool = True
    include_keyword_rows: bool = True
    include_product_ad_rows: bool = True
    sku: str = ""
    format: str = "new"  # "new" or "legacy"


def format_bidding_strategy(strategy: str) -> str:
    """Format bidding strategy for Amazon bulk sheet."""
    strategies = {
        'Fixed': 'Fixed bids',
        'Dynamic Down': 'Dynamic bids - down only',
        'Dynamic Up & Down': 'Dynamic bids - up and down',
    }
    return strategies.get(strategy, strategy)


def format_date(date_str: str) -> str:
    """Convert date from YYYY-MM-DD to YYYYMMDD format."""
    return date_str.replace('-', '') if date_str else ''


def empty_row() -> Dict[str, str]:
    """Create an empty row with all columns."""
    return {col: '' for col in COLUMNS}


def generate_bulk_sheet(
    campaigns: List[Campaign],
    keywords: List[Keyword],
    overrides: Dict[str, CampaignOverride],
    options: ExportOptions,
    auto_targeting_groups: Optional[Dict[str, List[str]]] = None,
    campaign_negatives: Optional[Dict[str, CampaignNegatives]] = None,
) -> Workbook:
    """
    Generate an Amazon SP bulk sheet workbook.

    Args:
        campaigns: List of campaigns to export
        keywords: List of all keywords (for lookup)
        overrides: Per-campaign overrides
        options: Export options
        auto_targeting_groups: Auto targeting type selections by campaign root
        campaign_negatives: Negative keywords per campaign

    Returns:
        openpyxl Workbook ready for saving
    """
    rows: List[Dict[str, str]] = []
    keyword_map = {kw.id: kw for kw in keywords}
    skus = [s.strip() for s in options.sku.split(',') if s.strip()]

    for campaign in campaigns:
        override = overrides.get(campaign.id, CampaignOverride())
        daily_budget = override.daily_budget if override.daily_budget else campaign.daily_budget

        # 1. Campaign row
        if options.include_campaign_rows:
            row = empty_row()
            row['Product'] = 'Sponsored Products'
            row['Entity'] = 'Campaign'
            row['Operation'] = 'Create'
            row['Campaign Name'] = campaign.name
            row['Start Date'] = format_date(campaign.start_date)
            row['Targeting Type'] = 'auto' if campaign.is_auto else 'manual'
            row['State'] = campaign.status.lower()
            row['Daily Budget'] = str(daily_budget)
            row['Bidding Strategy'] = format_bidding_strategy(campaign.bidding_strategy)
            rows.append(row)

        # 2. Ad Group row
        if options.include_ad_group_rows:
            row = empty_row()
            row['Product'] = 'Sponsored Products'
            row['Entity'] = 'Ad group'
            row['Operation'] = 'Create'
            row['Campaign Name'] = campaign.name
            row['Ad Group Name'] = campaign.name
            row['State'] = 'enabled'
            row['Ad Group Default Bid'] = str(campaign.default_bid)
            rows.append(row)

        # 3. Product Ad rows (one per SKU)
        if options.include_product_ad_rows and skus:
            for sku in skus:
                row = empty_row()
                row['Product'] = 'Sponsored Products'
                row['Entity'] = 'Product ad'
                row['Operation'] = 'Create'
                row['Campaign Name'] = campaign.name
                row['Ad Group Name'] = campaign.name
                row['State'] = 'enabled'
                row['SKU'] = sku
                rows.append(row)

        # 4. Keyword rows (manual keyword campaigns: Exact, Phrase, Broad)
        if options.include_keyword_rows and not campaign.is_auto and campaign.match_type.lower() != 'product':
            paused_kw_ids = override.paused_keyword_ids
            for kw_id in campaign.keyword_ids:
                kw = keyword_map.get(kw_id)
                if not kw:
                    continue

                bid = override.keyword_bids.get(kw_id, campaign.keyword_bid)
                is_paused = kw_id in paused_kw_ids

                row = empty_row()
                row['Product'] = 'Sponsored Products'
                row['Entity'] = 'Keyword'
                row['Operation'] = 'Create'
                row['Campaign Name'] = campaign.name
                row['Ad Group Name'] = campaign.name
                row['State'] = 'paused' if is_paused else 'enabled'
                row['Bid'] = str(bid)
                row['Keyword Text'] = kw.normalized_text
                row['Match Type'] = campaign.match_type.lower()
                rows.append(row)

        # 5. Product Targeting rows (Product campaigns - ASIN targeting)
        if options.include_keyword_rows and campaign.match_type.lower() == 'product':
            for kw_id in campaign.keyword_ids:
                kw = keyword_map.get(kw_id)
                if not kw:
                    continue

                asin_text = (kw.original_text or kw.normalized_text).upper()

                row = empty_row()
                row['Product'] = 'Sponsored Products'
                row['Entity'] = 'Product Targeting'
                row['Operation'] = 'Create'
                row['Campaign Name'] = campaign.name
                row['Ad Group Name'] = campaign.name
                row['State'] = 'enabled'
                row['Bid'] = str(campaign.keyword_bid)
                row['Product Targeting Expression'] = f'asin="{asin_text}"'
                rows.append(row)

        # 6. Auto campaign targeting type rows
        if campaign.is_auto:
            root_group = campaign.root_group or ''
            selected_types = set(
                (auto_targeting_groups or {}).get(root_group, ALL_AUTO_TARGETS)
            )
            for type_id in ALL_AUTO_TARGETS:
                row = empty_row()
                row['Product'] = 'Sponsored Products'
                row['Entity'] = 'Product Targeting'
                row['Operation'] = 'Create'
                row['Campaign Name'] = campaign.name
                row['Ad Group Name'] = campaign.name
                row['State'] = 'enabled' if type_id in selected_types else 'paused'
                row['Bid'] = str(campaign.default_bid)
                row['Product Targeting Expression'] = AUTO_TARGET_EXPRESSIONS.get(type_id, type_id)
                rows.append(row)

        # 7. Campaign negative keyword rows
        # Look up negatives by campaign ID first, then by campaign name (for frontend-computed campaigns)
        negs = (campaign_negatives or {}).get(campaign.id) or (campaign_negatives or {}).get(campaign.name)
        if negs:
            for kw_text in negs.exact:
                row = empty_row()
                row['Product'] = 'Sponsored Products'
                row['Entity'] = 'Campaign negative keyword'
                row['Operation'] = 'Create'
                row['Campaign Name'] = campaign.name
                row['State'] = 'enabled'
                row['Keyword Text'] = kw_text
                row['Match Type'] = 'negativeExact'
                rows.append(row)

            for kw_text in negs.phrase:
                row = empty_row()
                row['Product'] = 'Sponsored Products'
                row['Entity'] = 'Campaign negative keyword'
                row['Operation'] = 'Create'
                row['Campaign Name'] = campaign.name
                row['State'] = 'enabled'
                row['Keyword Text'] = kw_text
                row['Match Type'] = 'negativePhrase'
                rows.append(row)

    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Sponsored Products Campaigns'

    # Write header
    ws.append(COLUMNS)

    # Write data rows
    for row_data in rows:
        ws.append([row_data.get(col, '') for col in COLUMNS])

    return wb


def workbook_to_bytes(wb: Workbook) -> bytes:
    """Convert workbook to bytes for HTTP response."""
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def get_export_summary(
    campaigns: List[Campaign],
    keywords: List[Keyword],
    campaign_negatives: Optional[Dict[str, CampaignNegatives]] = None,
) -> Dict:
    """
    Get summary statistics for export.

    Args:
        campaigns: List of campaigns
        keywords: List of keywords
        campaign_negatives: Negative keywords per campaign

    Returns:
        Dict with summary statistics
    """
    total_keywords = sum(len(c.keyword_ids) for c in campaigns if not c.is_auto)
    total_negatives = sum(
        len(n.exact) + len(n.phrase)
        for n in (campaign_negatives or {}).values()
    )

    # Match type breakdown
    match_type_breakdown: Dict[str, int] = {}
    for campaign in campaigns:
        mt = campaign.match_type.lower()
        match_type_breakdown[mt] = match_type_breakdown.get(mt, 0) + 1

    # Estimate total rows
    total_rows = (
        len(campaigns)  # Campaign rows
        + len(campaigns)  # Ad group rows
        + total_keywords  # Keyword rows
        + total_negatives  # Negative rows
        + sum(4 for c in campaigns if c.is_auto)  # Auto targeting rows
    )

    return {
        'total_campaigns': len(campaigns),
        'total_keywords': total_keywords,
        'total_negatives': total_negatives,
        'total_rows': total_rows,
        'match_type_breakdown': match_type_breakdown,
    }
