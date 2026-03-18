"""
Pydantic models for bulk sheet parsing and API endpoints
"""
from typing import List, Dict, Optional, Literal
from decimal import Decimal
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, validator


MatchType = Literal["exact", "phrase", "broad"]


class BulkSheetTarget(BaseModel):
    """Single keyword target parsed from a bulk sheet."""
    campaign_name: Optional[str] = None
    ad_group_name: Optional[str] = None
    keyword: str = Field(..., min_length=1)
    keyword_normalized: str = Field(..., min_length=1)
    match_type: MatchType
    targeting_type: str = Field(default="keyword")
    state: str = Field(default="enabled")
    bid: Optional[Decimal] = None


class BulkSheetTargetDB(BulkSheetTarget):
    """Bulk sheet target with database fields."""
    id: UUID
    bulk_sheet_id: UUID


class BulkSheetUploadRequest(BaseModel):
    """Request metadata for bulk sheet upload (file sent as multipart)."""
    account_name: str = Field(..., min_length=1, max_length=255)
    marketplace: str = Field(default="com", max_length=10)

    @validator("account_name")
    def strip_account_name(cls, v: str) -> str:
        return v.strip()

    @validator("marketplace")
    def normalize_marketplace(cls, v: str) -> str:
        return v.lower().strip()


class BulkSheetUploadResponse(BaseModel):
    """Response after successful bulk sheet upload."""
    bulk_sheet_id: UUID
    account_name: str
    marketplace: str
    file_name: str
    row_count: int
    message: str = "Bulk sheet uploaded successfully"


class BulkSheetListItem(BaseModel):
    """Bulk sheet metadata for listing."""
    id: UUID
    account_name: str
    marketplace: str
    file_name: str
    uploaded_at: datetime
    row_count: Optional[int] = None


class BulkSheetListResponse(BaseModel):
    """Response with list of user's bulk sheets."""
    bulk_sheets: List[BulkSheetListItem]
    total: int


class TargetingCheckRequest(BaseModel):
    """Request to check targeting status for keywords."""
    bulk_sheet_id: UUID
    keywords: List[str] = Field(..., min_items=1)

    @validator("keywords")
    def normalize_keywords(cls, v: List[str]) -> List[str]:
        return [kw.strip() for kw in v if kw.strip()]


class KeywordTargetingInfo(BaseModel):
    """Targeting information for a single keyword."""
    is_targeted: bool
    match_types: List[MatchType] = Field(default_factory=list)
    campaigns: List[str] = Field(default_factory=list)


class TargetingCheckResponse(BaseModel):
    """Response with targeting status for requested keywords."""
    targeting: Dict[str, KeywordTargetingInfo]


class BulkSheetTargetsRequest(BaseModel):
    """Request to get targets from a bulk sheet."""
    keywords: Optional[List[str]] = Field(
        default=None,
        description="Optional list of keywords to filter by (normalized)"
    )


class BulkSheetTargetsResponse(BaseModel):
    """Response with targets from a bulk sheet."""
    targets: List[BulkSheetTarget]
    total: int


class ParseErrorDetail(BaseModel):
    """Details about a parse error."""
    row: int
    error: str


class ParseResult(BaseModel):
    """Result of parsing a bulk sheet."""
    targets: List[BulkSheetTarget]
    row_count: int
    skipped_rows: int
    errors: List[ParseErrorDetail] = Field(default_factory=list)
