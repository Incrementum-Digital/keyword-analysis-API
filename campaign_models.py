"""
Pydantic models for the campaign builder API
"""
from typing import List, Dict, Any, Optional
from decimal import Decimal
from pydantic import BaseModel, Field


# ============================================================================
# Configuration Models
# ============================================================================


class SVTier(BaseModel):
    """Search volume tier configuration"""
    id: str
    label: str = Field(..., description="Display label for tier (e.g., 'High', 'Medium', 'Low')")
    min_sv: int = Field(..., ge=0, description="Minimum search volume for this tier")
    max_sv: int = Field(..., ge=0, description="Maximum search volume for this tier")
    max_keywords: int = Field(default=10, ge=1, description="Max keywords per campaign in this tier")


class PlacementMultipliers(BaseModel):
    """Placement bid multiplier percentages (0-900%)"""
    top_of_search: int = Field(default=0, ge=0, le=900, description="Top of Search placement multiplier %")
    rest_of_search: int = Field(default=0, ge=0, le=900, description="Rest of Search placement multiplier %")
    product_page: int = Field(default=0, ge=0, le=900, description="Product Page placement multiplier %")


class MatchTypeConfig(BaseModel):
    """Configuration for a specific match type"""
    enabled: bool = Field(default=True, description="Whether this match type is enabled")
    sv_tiers: List[SVTier] = Field(default_factory=list, description="Search volume tier configurations")
    daily_budget: Decimal = Field(default=Decimal("20.00"), description="Daily budget for campaigns")
    default_bid: Decimal = Field(default=Decimal("0.67"), description="Default bid for ad groups")
    keyword_bid: Decimal = Field(default=Decimal("0.67"), description="Default bid for keywords")
    bidding_strategy: str = Field(
        default="Fixed",
        description="Bidding strategy: Fixed, Dynamic Down, or Dynamic Up & Down"
    )
    placement_multipliers_enabled: bool = Field(
        default=False,
        description="Whether placement multipliers are enabled"
    )
    placement_multipliers: PlacementMultipliers = Field(
        default_factory=PlacementMultipliers,
        description="Placement bid multiplier percentages"
    )
    start_date: str = Field(default="", description="Campaign start date (YYYY-MM-DD)")
    status: str = Field(default="Enabled", description="Campaign status: Enabled or Paused")
    sv_ratio_threshold: float = Field(
        default=10.0,
        description="Search volume ratio threshold for grouping"
    )


class NamingTemplate(BaseModel):
    """Campaign naming template configuration"""
    tokens: List[str] = Field(
        default=["SKU", "SP", "MATCH", "GROUP"],
        description="Ordered list of tokens to include in campaign name"
    )
    separator: str = Field(default="_", description="Separator between tokens")
    custom_tokens: Dict[str, str] = Field(
        default_factory=dict,
        description="Custom token values (token name -> value)"
    )


class CampaignSessionConfig(BaseModel):
    """Full campaign session configuration"""
    sku: str = Field(default="", description="Product SKU")
    naming_template: NamingTemplate = Field(default_factory=NamingTemplate)
    match_type_configs: Dict[str, MatchTypeConfig] = Field(
        default_factory=dict,
        description="Configuration per match type (exact, phrase, broad, product, auto)"
    )


# ============================================================================
# Request Models
# ============================================================================


class CreateCampaignSessionRequest(BaseModel):
    """Request to create a new campaign session"""
    keyword_session_id: str = Field(..., description="ID of the parent keyword analysis session")
    user_id: str = Field(..., description="User ID")
    name: Optional[str] = Field(None, description="Optional name for the campaign session")


class UpdateCampaignSessionRequest(BaseModel):
    """Request to update campaign session configuration"""
    config: Optional[CampaignSessionConfig] = Field(None, description="Updated configuration")
    current_step: Optional[int] = Field(None, ge=1, le=4, description="Current wizard step")
    status: Optional[str] = Field(None, description="Session status: draft or complete")


class NormalizationDecision(BaseModel):
    """Single normalization decision"""
    original_keyword: str = Field(..., description="Original keyword text")
    normalized_keyword: str = Field(..., description="Normalized keyword text")
    accepted: bool = Field(default=True, description="Whether the normalization is accepted")
    reason: Optional[str] = Field(None, description="Reason for normalization (e.g., 'Plural → Singular')")


class SaveNormalizationRequest(BaseModel):
    """Request to save normalization decisions"""
    decisions: List[NormalizationDecision] = Field(
        ...,
        description="List of normalization decisions"
    )


class ManualCampaignGroupRequest(BaseModel):
    """Manual campaign group for custom/product/auto targeting"""
    id: int = Field(..., description="Unique ID for this manual campaign group")
    name: str = Field(..., description="Custom campaign name")
    keyword_ids: List[str] = Field(
        default_factory=list,
        description="Keyword IDs to include in this campaign"
    )


class GenerateCampaignsRequest(BaseModel):
    """Request to generate campaigns"""
    config: CampaignSessionConfig = Field(..., description="Campaign configuration")
    selected_roots: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Selected root keywords per match type"
    )
    solo_keyword_ids: List[str] = Field(
        default_factory=list,
        description="Keyword IDs to create solo campaigns for"
    )
    include_ungrouped: bool = Field(
        default=True,
        description="Whether to include keywords not in any root group"
    )
    manual_campaign_groups: Dict[str, List[ManualCampaignGroupRequest]] = Field(
        default_factory=dict,
        description="Manual campaign groups per match type (exact, phrase, broad, product, auto)"
    )


class UpdateCampaignRequest(BaseModel):
    """Request to update a single campaign"""
    name: Optional[str] = None
    daily_budget: Optional[Decimal] = None
    default_bid: Optional[Decimal] = None
    keyword_bid: Optional[Decimal] = None
    bidding_strategy: Optional[str] = None
    placement_multipliers_enabled: Optional[bool] = None
    placement_multipliers: Optional[PlacementMultipliers] = None
    start_date: Optional[str] = None
    status: Optional[str] = None


class ExportBulkSheetRequest(BaseModel):
    """Request to export bulk sheet"""
    campaign_ids: Optional[List[str]] = Field(
        None,
        description="Specific campaign IDs to export (None = all campaigns)"
    )
    include_negatives: bool = Field(
        default=True,
        description="Whether to include negative keywords"
    )
    skus: List[str] = Field(
        default_factory=list,
        description="Product SKUs to include in product ads"
    )
    format: str = Field(
        default="new",
        description="Bulk sheet format: 'new' or 'legacy'"
    )


class CampaignNegativeRequest(BaseModel):
    """Request to add campaign negative keywords"""
    keyword_text: str = Field(..., min_length=1, description="Negative keyword text")
    match_type: str = Field(
        ...,
        description="Match type: 'negative_exact' or 'negative_phrase'"
    )


class CampaignNegativesForExport(BaseModel):
    """Negative keywords for a campaign in export format"""
    exact: List[str] = Field(default_factory=list)
    phrase: List[str] = Field(default_factory=list)


class CampaignKeywordForExport(BaseModel):
    """Keyword within a campaign for export"""
    id: str = Field(..., description="Keyword ID")
    text: str = Field(..., description="Keyword text")
    sv: int = Field(default=0, description="Search volume")


class CampaignForExport(BaseModel):
    """Campaign data sent from frontend for export"""
    id: str = Field(..., description="Campaign ID")
    name: str = Field(..., description="Campaign name")
    match_type: str = Field(..., description="Match type: exact, phrase, broad, product, auto")
    root_group: Optional[str] = Field(None, description="Root group name")
    daily_budget: float = Field(..., description="Daily budget")
    default_bid: float = Field(..., description="Default bid for ad group")
    keyword_bid: Optional[float] = Field(None, description="Keyword bid")
    bidding_strategy: str = Field(default="Fixed", description="Bidding strategy")
    placement_multipliers_enabled: bool = Field(default=False, description="Whether placement multipliers are enabled")
    placement_multipliers: Optional[PlacementMultipliers] = Field(None, description="Placement multiplier percentages")
    start_date: Optional[str] = Field(None, description="Start date YYYY-MM-DD")
    status: str = Field(default="Enabled", description="Campaign status")
    is_auto: bool = Field(default=False, description="Is auto targeting campaign")
    keywords: Optional[List[CampaignKeywordForExport]] = Field(
        None, description="Keywords in this campaign"
    )


class DownloadBulkSheetRequest(BaseModel):
    """Request to download bulk sheet with campaigns and negatives"""
    campaigns: Optional[List[CampaignForExport]] = Field(
        None,
        description="Campaigns to export (from frontend). If not provided, fetches from DB."
    )
    campaign_negatives: Dict[str, CampaignNegativesForExport] = Field(
        default_factory=dict,
        description="Negative keywords per campaign name"
    )


# ============================================================================
# Response Models
# ============================================================================


class NormVariant(BaseModel):
    """Variant within a normalization group"""
    keyword: str
    keyword_id: str = Field(..., description="ID of the keyword in keyword_analysis.results")
    search_volume: int
    reason: str = Field(..., description="Normalization reason (e.g., 'Plural → Singular')")
    is_merged: bool = Field(default=True)


class NormGroup(BaseModel):
    """Group of keywords that normalize to the same text"""
    id: str
    normalized_text: str
    combined_search_volume: int
    variants: List[NormVariant]
    is_included: bool = Field(default=True)


class NormalizeResponse(BaseModel):
    """Response from normalization endpoint"""
    groups: List[NormGroup]
    total_keywords: int
    total_groups: int


class CampaignKeywordResponse(BaseModel):
    """Keyword within a campaign"""
    id: str
    keyword_id: str
    keyword_text: str
    search_volume: Optional[int] = None
    bid: Optional[Decimal] = None
    status: str = "enabled"


class CampaignResponse(BaseModel):
    """Generated campaign response"""
    id: str
    name: str
    match_type: str
    root_group: Optional[str] = None
    keyword_count: int
    keywords: Optional[List[CampaignKeywordResponse]] = None
    daily_budget: float  # Changed from Decimal to ensure JSON serializes as number
    default_bid: float   # Changed from Decimal to ensure JSON serializes as number
    keyword_bid: Optional[float] = None  # Changed from Decimal
    bidding_strategy: str
    start_date: str
    status: str
    is_solo: bool = False
    is_auto: bool = False
    sv_tier: Optional[str] = None


class CampaignSessionResponse(BaseModel):
    """Full campaign session response"""
    id: str
    keyword_session_id: str
    user_id: str
    name: Optional[str] = None
    status: str
    current_step: int
    config: CampaignSessionConfig
    existing_targeting: Optional[Dict[str, Any]] = None
    campaigns: Optional[List[CampaignResponse]] = None
    normalization_decisions: Optional[List[NormalizationDecision]] = None
    created_at: str
    updated_at: str


class CampaignNegativeResponse(BaseModel):
    """Campaign negative keyword response"""
    id: str
    keyword_text: str
    match_type: str


class ExportSummary(BaseModel):
    """Summary of exported bulk sheet"""
    total_campaigns: int
    total_keywords: int
    total_negatives: int
    total_rows: int
    match_type_breakdown: Dict[str, int]


class CampaignListResponse(BaseModel):
    """List of campaigns for a session"""
    session_id: str
    campaigns: List[CampaignResponse]
    total: int
