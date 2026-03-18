"""
Pydantic models for the keyword analysis API
"""
from typing import List, Dict, Any, Optional, Union
from typing import Literal
from pydantic import BaseModel, Field, validator


class KeywordAnalysisWithASIN(BaseModel):
    """Request model when user provides ASIN"""
    asin: str = Field(..., min_length=10, max_length=10, description="Amazon Standard Identification Number")
    country: str = Field(default="US", description="Country code for Amazon marketplace")
    keywords: List[str] = Field(..., min_items=1, description="List of keywords to analyze")
    
    @validator('asin')
    def validate_asin(cls, v):
        if not v.isalnum():
            raise ValueError("ASIN must be alphanumeric")
        return v.upper()
    
    @validator('country')
    def validate_country(cls, v):
        valid_countries = ["US", "GB", "UK", "DE", "FR", "JP", "CA", "IT", "ES", "IN", "MX", "BR", "AU", "NL"]
        if v.upper() not in valid_countries:
            raise ValueError(f"Country must be one of: {', '.join(valid_countries)}")
        return v.upper()


class KeywordAnalysisWithDescription(BaseModel):
    """Request model when user provides product description"""
    product_description: str = Field(..., min_length=10, description="Text description of the product")
    keywords: List[str] = Field(..., min_items=1, description="List of keywords to analyze")


class KeywordAnalysisRequest(BaseModel):
    """Union request model that accepts either ASIN or product description"""
    asin: Optional[str] = Field(None, min_length=10, max_length=10)
    country: Optional[str] = Field(default="US")
    product_description: Optional[str] = Field(None, min_length=10)
    keywords: List[str] = Field(..., min_items=1, description="List of keywords to analyze")
    
    @validator('keywords')
    def validate_keywords(cls, v):
        # Remove duplicates while preserving order
        seen = set()
        unique_keywords = []
        for keyword in v:
            keyword_lower = keyword.lower().strip()
            if keyword_lower and keyword_lower not in seen:
                seen.add(keyword_lower)
                unique_keywords.append(keyword.strip())
        return unique_keywords
    
    @validator('asin', pre=True)
    def validate_asin(cls, v):
        if v and not v.isalnum():
            raise ValueError("ASIN must be alphanumeric")
        return v.upper() if v else v
    
    @validator('country')
    def validate_country(cls, v):
        valid_countries = ["US", "GB", "UK", "DE", "FR", "JP", "CA", "IT", "ES", "IN", "MX", "BR", "AU", "NL"]
        if v and v.upper() not in valid_countries:
            raise ValueError(f"Country must be one of: {', '.join(valid_countries)}")
        return v.upper() if v else v
    
    def validate_input_type(self):
        """Validate that either ASIN or product_description is provided, but not both"""
        if self.asin and self.product_description:
            raise ValueError("Provide either ASIN or product_description, not both")
        if not self.asin and not self.product_description:
            raise ValueError("Either ASIN or product_description must be provided")
        return True


class NegativePhraseRequest(BaseModel):
    """Request payload for generating negative keyword phrases via ASIN."""
    asin: str = Field(..., min_length=10, max_length=10)
    country: str = Field(default="US")

    @validator('asin')
    def validate_asin_format(cls, value: str) -> str:
        if not value.isalnum():
            raise ValueError("ASIN must be alphanumeric")
        return value.upper()

    @validator('country')
    def validate_country_code(cls, value: str) -> str:
        valid_countries = [
            "US", "GB", "UK", "DE", "FR", "JP", "CA", "IT", "ES",
            "IN", "MX", "BR", "AU", "NL"
        ]
        if value.upper() not in valid_countries:
            raise ValueError(f"Country must be one of: {', '.join(valid_countries)}")
        return value.upper()


class ProductDetails(BaseModel):
    """Product details model (from Keepa or user description)"""
    asin: Optional[str] = None
    brand: Optional[str] = None
    product_title: Optional[str] = None
    product_features: Optional[str] = None
    description: Optional[str] = None
    main_image_url: Optional[str] = None
    gallery_image_urls: Optional[List[str]] = None
    category_tree: Optional[List[Dict[str, Any]]] = None
    cat_id: Optional[int] = None
    category_name: Optional[str] = None
    parent_asin: Optional[str] = None
    review_count: Optional[int] = None
    rating: Optional[float] = None
    sales_rank: Optional[int] = None
    price: Optional[float] = None
    category_attributes: Optional[Dict[str, Any]] = None
    # For text description input
    raw_description: Optional[str] = None


class KeywordResult(BaseModel):
    """Individual keyword analysis result"""
    keyword: str
    type: str = Field(..., description="Classification: generic, our_brand, or competitor_brand")
    score: int = Field(..., ge=1, le=10, description="Relevance score from 1-10")
    reasoning: str = Field(..., description="Brief explanation for the classification and score")


class AnalysisSummary(BaseModel):
    """Summary statistics for the analysis"""
    total_keywords: int
    analyzed: int
    failed: int
    by_type: Dict[str, int] = Field(default_factory=dict)
    average_score: Optional[float] = None
    processing_time: Optional[float] = None


class KeywordAnalysisResponse(BaseModel):
    """Complete response model"""
    input_type: str = Field(..., description="Either 'asin' or 'description'")
    product_info: ProductDetails
    analysis_results: List[KeywordResult]
    summary: AnalysisSummary
    errors: Optional[List[str]] = None


class KeywordVolumeRow(BaseModel):
    """Single keyword row used for root aggregation"""
    keyword: str = Field(..., min_length=1)
    search_volume: int = Field(..., ge=0)


class RootAnalysisRequest(BaseModel):
    """Request payload for bulk root keyword aggregation"""
    keywords: List[KeywordVolumeRow] = Field(..., min_items=1)
    mode: Literal["full", "simple"] = Field(default="full")


class RootAnalysisMember(BaseModel):
    """Original keyword row contributing to a normalized root"""
    keyword: str
    search_volume: int


class RootAnalysisItem(BaseModel):
    """Normalized root output item"""
    normalized_term: str
    frequency: int
    search_volume: int
    relative_volume: Optional[float] = None
    members: List[RootAnalysisMember]


class AutoConfigUpdates(BaseModel):
    """Auto-learned stopwords/irregulars added during processing"""
    new_stopwords: List[str] = Field(default_factory=list)
    new_irregular_singulars: Dict[str, str] = Field(default_factory=dict)


class RootAnalysisResponse(BaseModel):
    """Response payload returned by the root analysis endpoint"""
    mode: Literal["full", "simple"]
    total_keywords: int
    results: List[RootAnalysisItem]
    auto_config_updates: AutoConfigUpdates


# ============================================================================
# Root Validation Models (for comparing with Data Dive)
# ============================================================================


class RootComparisonRequest(BaseModel):
    """Request to compare local root analysis with Data Dive."""
    niche_id: str = Field(..., min_length=1, description="Data Dive niche ID")


class RootComparisonSummary(BaseModel):
    """Summary of root comparison results."""
    match_rate: float = Field(..., description="Percentage of matching roots (0-100)")
    total_datadive_roots: int
    total_local_roots: int
    exact_matches: int
    mismatches: int
    only_in_datadive: int
    only_in_local: int
    passed: bool = Field(..., description="True if match_rate >= 95%")


class RootMismatch(BaseModel):
    """Details of a mismatched root."""
    root: str
    datadive: Dict[str, Any]
    local: Dict[str, Any]
    differences: Dict[str, bool]


class RootOnlyItem(BaseModel):
    """Root that exists only in one source."""
    root: str
    frequency: int
    search_volume: Optional[int] = Field(None, alias="broadSearchVolume")


class RootComparisonResponse(BaseModel):
    """Response from root comparison endpoint."""
    summary: RootComparisonSummary
    matches: List[str]
    mismatches: List[RootMismatch]
    only_datadive: List[Dict[str, Any]]
    only_local: List[Dict[str, Any]]
