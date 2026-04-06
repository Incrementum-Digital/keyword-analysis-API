"""
Campaign Builder API Router

Endpoints for creating and managing Amazon PPC campaign sessions,
keyword normalization, campaign generation, and bulk sheet export.
"""
import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from campaign_models import (
    CampaignListResponse,
    CampaignNegativeRequest,
    CampaignNegativeResponse,
    CampaignResponse,
    CampaignSessionResponse,
    CreateCampaignSessionRequest,
    DownloadBulkSheetRequest,
    ExportBulkSheetRequest,
    ExportSummary,
    GenerateCampaignsRequest,
    NormGroup,
    NormalizeResponse,
    NormVariant,
    SaveNormalizationRequest,
    UpdateCampaignRequest,
    UpdateCampaignSessionRequest,
)
from normalizer import RawKeyword, normalize_keywords, groups_to_dict
from campaign_generator import (
    Campaign as GenCampaign,
    GenerateInput,
    Keyword as GenKeyword,
    MatchTypeConfig as GenMatchTypeConfig,
    SVTier as GenSVTier,
    ManualCampaignGroup as GenManualCampaignGroup,
    generate_campaigns as run_campaign_generator,
    detect_roots_from_keywords,
)
from root_detector import RootGroup
from naming_engine import NamingTemplate as GenNamingTemplate
from bulk_sheet_exporter import (
    Campaign as ExportCampaign,
    Keyword as ExportKeyword,
    CampaignOverride,
    CampaignNegatives,
    ExportOptions,
    generate_bulk_sheet,
    workbook_to_bytes,
    get_export_summary,
    calculate_base_bid,
)
from supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaign-sessions", tags=["campaign-sessions"])


def _compute_calculated_bid(campaign: dict, config: dict) -> float:
    """Compute calculated base bid from campaign data and session config.

    Uses the same calculate_base_bid() function as bulk sheet export to ensure
    the preview bid matches the exported bid.
    """
    keyword_bid = campaign.get("keyword_bid")
    default_bid = campaign.get("default_bid", 0)
    bid = keyword_bid if keyword_bid is not None else default_bid
    if not bid:
        return bid or 0.0

    match_type = campaign.get("match_type", "")
    bidding_strategy = campaign.get("bidding_strategy", "Fixed")

    # Look up placement multiplier settings from session config
    mtc = config.get("match_type_configs", {}).get(match_type, {})
    placement_enabled = mtc.get("placement_multipliers_enabled", False)
    pm = mtc.get("placement_multipliers") or {}
    top_pct = pm.get("top_of_search", 0)
    rest_pct = pm.get("rest_of_search", 0)
    product_pct = pm.get("product_page", 0)

    result = calculate_base_bid(
        max_bid=Decimal(str(bid)),
        bidding_strategy=bidding_strategy,
        placement_enabled=placement_enabled,
        top_pct=top_pct,
        rest_pct=rest_pct,
        product_pct=product_pct,
    )
    return float(result)


# ============================================================================
# Campaign Session Endpoints
# ============================================================================


@router.post("", response_model=CampaignSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign_session(request: CreateCampaignSessionRequest):
    """
    Create a new campaign session from an existing keyword analysis session.

    - Validates that the keyword session exists and belongs to the user
    - Creates a new campaign session in 'draft' status
    - Returns the created session with default configuration
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        logger.error(f"Supabase not configured: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify keyword session exists and belongs to user
        keyword_session = supabase.schema("keyword_analysis").table("sessions").select(
            "id"
        ).eq("id", request.keyword_session_id).eq("user_id", request.user_id).execute()

        if not keyword_session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Keyword session not found"
            )

        # Check if campaign session already exists for this keyword session
        existing = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "*"
        ).eq("keyword_session_id", request.keyword_session_id).execute()

        if existing.data:
            # Return existing session instead of error (idempotent create)
            row = existing.data[0]
            return CampaignSessionResponse(
                id=row["id"],
                keyword_session_id=row["keyword_session_id"],
                user_id=row["user_id"],
                name=row.get("name"),
                status=row["status"],
                current_step=row["current_step"],
                config=row.get("config", {}),
                existing_targeting=row.get("existing_targeting"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

        # Create campaign session
        session_data = {
            "keyword_session_id": request.keyword_session_id,
            "user_id": request.user_id,
            "name": request.name,
            "status": "draft",
            "current_step": 1,
            "config": {},
        }

        result = supabase.schema("keyword_analysis").table("campaign_sessions").insert(
            session_data
        ).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create campaign session"
            )

        row = result.data[0]
        return CampaignSessionResponse(
            id=row["id"],
            keyword_session_id=row["keyword_session_id"],
            user_id=row["user_id"],
            name=row.get("name"),
            status=row["status"],
            current_step=row["current_step"],
            config=row.get("config", {}),
            existing_targeting=row.get("existing_targeting"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating campaign session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create campaign session: {str(e)}"
        )


@router.get("/{session_id}", response_model=CampaignSessionResponse)
async def get_campaign_session(session_id: UUID, user_id: str):
    """
    Get a campaign session with all related data.

    Returns the session configuration, campaigns, and normalization decisions.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Get campaign session
        result = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "*"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        row = result.data[0]

        # Get campaigns for this session
        campaigns_result = supabase.schema("keyword_analysis").table("campaigns").select(
            "*, campaign_keywords(id, keyword_id, bid, status)"
        ).eq("campaign_session_id", str(session_id)).execute()

        campaigns = []
        session_config = row.get("config", {})
        for c in campaigns_result.data or []:
            campaigns.append(CampaignResponse(
                id=c["id"],
                name=c["name"],
                match_type=c["match_type"],
                root_group=c.get("root_group"),
                keyword_count=len(c.get("campaign_keywords", [])),
                daily_budget=c["daily_budget"],
                default_bid=c["default_bid"],
                keyword_bid=c.get("keyword_bid"),
                bidding_strategy=c["bidding_strategy"],
                start_date=str(c["start_date"]) if c.get("start_date") else "",
                status=c["status"],
                is_solo=c.get("is_solo", False),
                is_auto=c.get("is_auto", False),
                sv_tier=c.get("sv_tier"),
                calculated_base_bid=_compute_calculated_bid(c, session_config),
            ))

        # Get normalization decisions
        norm_result = supabase.schema("keyword_analysis").table("normalization_decisions").select(
            "*"
        ).eq("campaign_session_id", str(session_id)).execute()

        normalization_decisions = [
            {
                "original_keyword": n["original_keyword"],
                "normalized_keyword": n["normalized_keyword"],
                "accepted": n["accepted"],
                "reason": n.get("reason"),
            }
            for n in norm_result.data or []
        ]

        return CampaignSessionResponse(
            id=row["id"],
            keyword_session_id=row["keyword_session_id"],
            user_id=row["user_id"],
            name=row.get("name"),
            status=row["status"],
            current_step=row["current_step"],
            config=row.get("config", {}),
            existing_targeting=row.get("existing_targeting"),
            campaigns=campaigns if campaigns else None,
            normalization_decisions=normalization_decisions if normalization_decisions else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting campaign session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get campaign session: {str(e)}"
        )


@router.put("/{session_id}", response_model=CampaignSessionResponse)
async def update_campaign_session(
    session_id: UUID,
    request: UpdateCampaignSessionRequest,
    user_id: str,
):
    """
    Update campaign session configuration.

    - Updates config, current_step, or status
    - Config includes: sku, namingTemplate, matchTypeConfigs
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Build update data
        update_data = {}
        if request.config:
            update_data["config"] = request.config.model_dump(mode="json")
        if request.current_step is not None:
            update_data["current_step"] = request.current_step
        if request.status is not None:
            update_data["status"] = request.status

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        # Update session
        result = supabase.schema("keyword_analysis").table("campaign_sessions").update(
            update_data
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        row = result.data[0]
        return CampaignSessionResponse(
            id=row["id"],
            keyword_session_id=row["keyword_session_id"],
            user_id=row["user_id"],
            name=row.get("name"),
            status=row["status"],
            current_step=row["current_step"],
            config=row.get("config", {}),
            existing_targeting=row.get("existing_targeting"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating campaign session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update campaign session: {str(e)}"
        )


# ============================================================================
# Normalization Endpoints
# ============================================================================


@router.post("/{session_id}/normalize", response_model=NormalizeResponse)
async def generate_normalization(session_id: UUID, user_id: str):
    """
    Generate normalization suggestions for keywords in the session.

    - Detects plural/singular variants
    - Identifies filler words (for, with, etc.)
    - Groups keywords that normalize to the same text
    - Returns groups with combined search volumes
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "keyword_session_id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        keyword_session_id = session.data[0]["keyword_session_id"]

        # Get keywords from the keyword analysis results
        keywords_result = supabase.schema("keyword_analysis").table("results").select(
            "id, keyword, search_volume"
        ).eq("session_id", keyword_session_id).execute()

        if not keywords_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No keywords found in keyword session"
            )

        # Convert to RawKeyword format for normalizer
        raw_keywords = [
            RawKeyword(
                id=kw["id"],
                text=kw["keyword"],
                search_volume=kw.get("search_volume", 0) or 0
            )
            for kw in keywords_result.data
        ]

        # Run normalization algorithm
        norm_groups = normalize_keywords(raw_keywords)

        # Convert to response format
        groups = [
            NormGroup(
                id=g.id,
                normalized_text=g.normalized_text,
                combined_search_volume=g.combined_search_volume,
                variants=[
                    NormVariant(
                        keyword=v.keyword.text,
                        keyword_id=v.keyword.id,
                        search_volume=v.keyword.search_volume,
                        reason=v.reason,
                        is_merged=v.is_merged
                    )
                    for v in g.variants
                ],
                is_included=g.is_included
            )
            for g in norm_groups
        ]

        return NormalizeResponse(
            groups=groups,
            total_keywords=len(keywords_result.data),
            total_groups=len(groups),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating normalization: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate normalization: {str(e)}"
        )


@router.put("/{session_id}/normalize")
async def save_normalization(
    session_id: UUID,
    request: SaveNormalizationRequest,
    user_id: str,
):
    """
    Save normalization decisions.

    - Persists user's accept/reject decisions for each normalization
    - Used to merge or keep separate keyword variants
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        # Delete existing decisions for this session
        supabase.schema("keyword_analysis").table("normalization_decisions").delete().eq(
            "campaign_session_id", str(session_id)
        ).execute()

        # Insert new decisions
        if request.decisions:
            decisions_data = [
                {
                    "campaign_session_id": str(session_id),
                    "original_keyword": d.original_keyword,
                    "normalized_keyword": d.normalized_keyword,
                    "accepted": d.accepted,
                    "reason": d.reason,
                }
                for d in request.decisions
            ]

            supabase.schema("keyword_analysis").table("normalization_decisions").insert(
                decisions_data
            ).execute()

        return {"success": True, "saved": len(request.decisions)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving normalization: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save normalization: {str(e)}"
        )


@router.get("/{session_id}/roots")
async def get_root_groups(session_id: UUID, user_id: str):
    """
    Detect and return root keyword groups for a session.

    Root groups are common n-grams that appear across multiple keywords.
    Used for organizing keywords into campaigns.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "keyword_session_id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        keyword_session_id = session.data[0]["keyword_session_id"]

        # Get keywords from keyword analysis results
        keywords_result = supabase.schema("keyword_analysis").table("results").select(
            "id, keyword, search_volume"
        ).eq("session_id", keyword_session_id).execute()

        if not keywords_result.data:
            return {"roots": [], "total": 0}

        # Convert to generator Keyword format
        gen_keywords = [
            GenKeyword(
                id=kw["id"],
                normalized_text=kw["keyword"],
                search_volume=kw.get("search_volume", 0) or 0,
                original_text=kw["keyword"]
            )
            for kw in keywords_result.data
        ]

        # Detect roots
        root_groups = detect_roots_from_keywords(gen_keywords)

        # Convert to response format (include keyword_ids for frontend display)
        roots = [
            {
                "name": r.name,
                "frequency": r.frequency,
                "total_sv": r.total_sv,
                "keyword_count": len(r.keyword_ids),
                "keyword_ids": r.keyword_ids,
            }
            for r in root_groups
        ]

        return {"roots": roots, "total": len(roots)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting roots: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to detect roots: {str(e)}"
        )


# ============================================================================
# Campaign Generation Endpoints
# ============================================================================


@router.post("/{session_id}/campaigns", response_model=CampaignListResponse)
async def generate_campaigns(
    session_id: UUID,
    request: GenerateCampaignsRequest,
    user_id: str,
):
    """
    Generate campaigns from keywords based on configuration.

    - Creates campaigns grouped by root keywords and SV tiers
    - Applies match type configurations
    - Respects max keywords per campaign limits
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id, keyword_session_id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        keyword_session_id = session.data[0]["keyword_session_id"]

        # Get keywords from keyword analysis results
        keywords_result = supabase.schema("keyword_analysis").table("results").select(
            "id, keyword, search_volume"
        ).eq("session_id", keyword_session_id).execute()

        if not keywords_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No keywords found in keyword session"
            )

        # Convert to generator Keyword format
        gen_keywords = [
            GenKeyword(
                id=kw["id"],
                normalized_text=kw["keyword"],
                search_volume=kw.get("search_volume", 0) or 0,
                original_text=kw["keyword"]
            )
            for kw in keywords_result.data
        ]

        # Detect roots from keywords
        root_groups = detect_roots_from_keywords(gen_keywords)

        # Convert config to generator format
        match_type_configs = {}
        for mt, mtc in (request.config.match_type_configs or {}).items():
            sv_tiers = [
                GenSVTier(
                    id=tier.id,
                    label=tier.label,
                    min_sv=tier.min_sv,
                    max_sv=tier.max_sv,
                    max_keywords=tier.max_keywords
                )
                for tier in (mtc.sv_tiers or [])
            ]
            match_type_configs[mt.lower()] = GenMatchTypeConfig(
                enabled=mtc.enabled,
                sv_tiers=sv_tiers,
                daily_budget=mtc.daily_budget,
                default_bid=mtc.default_bid,
                keyword_bid=mtc.keyword_bid,
                bidding_strategy=mtc.bidding_strategy,
                start_date=mtc.start_date,
                status=mtc.status,
            )

        # Build targeting selections (all keywords selected for all enabled match types)
        targeting_selections = {}
        for kw in gen_keywords:
            targeting_selections[kw.id] = [
                mt for mt, cfg in match_type_configs.items()
                if cfg.enabled and mt in ['exact', 'phrase', 'broad']
            ]

        # Build naming template
        naming_template = GenNamingTemplate(
            tokens=request.config.naming_template.tokens or ["SKU", "SP", "MATCH", "GROUP"],
            separator=request.config.naming_template.separator or "_",
            custom_tokens=request.config.naming_template.custom_tokens or {}
        )

        # Convert manual campaign groups from request to generator format
        manual_campaign_groups = {}
        for match_type, groups in (request.manual_campaign_groups or {}).items():
            manual_campaign_groups[match_type] = [
                GenManualCampaignGroup(
                    id=g.id,
                    name=g.name,
                    keyword_ids=g.keyword_ids
                )
                for g in groups
            ]

        # Generate campaigns
        gen_input = GenerateInput(
            keywords=gen_keywords,
            targeting_selections=targeting_selections,
            match_type_configs=match_type_configs,
            root_groups=root_groups,
            selected_roots_by_match_type=request.selected_roots or {},
            solo_keyword_ids=request.solo_keyword_ids or [],
            include_ungrouped=request.include_ungrouped,
            sku=request.config.sku or "",
            naming_template=naming_template,
            manual_campaign_groups=manual_campaign_groups,
        )

        generated_campaigns = run_campaign_generator(gen_input)

        # Delete existing campaigns for this session
        supabase.schema("keyword_analysis").table("campaigns").delete().eq(
            "campaign_session_id", str(session_id)
        ).execute()

        # Batch insert all campaigns at once for performance
        campaigns_data = [
            {
                "campaign_session_id": str(session_id),
                "name": camp.name,
                "match_type": camp.match_type,
                "root_group": camp.root_group,
                "daily_budget": float(camp.daily_budget),
                "default_bid": float(camp.default_bid),
                "keyword_bid": float(camp.keyword_bid),
                "bidding_strategy": camp.bidding_strategy,
                "start_date": camp.start_date if camp.start_date else None,
                "status": camp.status,
                "is_solo": camp.is_solo,
                "is_auto": camp.is_auto,
                "sv_tier": camp.sv_tier,
            }
            for camp in generated_campaigns
        ]

        # Batch insert campaigns
        result = supabase.schema("keyword_analysis").table("campaigns").insert(
            campaigns_data
        ).execute()

        # Build response and collect keyword data for batch insert
        campaigns_response = []
        all_kw_data = []

        for i, db_campaign in enumerate(result.data or []):
            campaign_id = db_campaign["id"]
            camp = generated_campaigns[i]

            # Collect keywords for batch insert
            if camp.keyword_ids:
                for kw_id in camp.keyword_ids:
                    all_kw_data.append({
                        "campaign_id": campaign_id,
                        "keyword_id": kw_id,
                        "status": "enabled"
                    })

            campaigns_response.append(CampaignResponse(
                id=campaign_id,
                name=db_campaign["name"],
                match_type=db_campaign["match_type"],
                root_group=db_campaign.get("root_group"),
                keyword_count=len(camp.keyword_ids),
                daily_budget=db_campaign["daily_budget"],
                default_bid=db_campaign["default_bid"],
                keyword_bid=db_campaign.get("keyword_bid"),
                bidding_strategy=db_campaign["bidding_strategy"],
                start_date=str(db_campaign["start_date"]) if db_campaign.get("start_date") else "",
                status=db_campaign["status"],
                is_solo=db_campaign.get("is_solo", False),
                is_auto=db_campaign.get("is_auto", False),
                sv_tier=db_campaign.get("sv_tier"),
                calculated_base_bid=_compute_calculated_bid(
                    db_campaign, request.config.model_dump(mode="json")
                ),
            ))

        # Batch insert all campaign keywords at once
        if all_kw_data:
            supabase.schema("keyword_analysis").table("campaign_keywords").insert(
                all_kw_data
            ).execute()

        return CampaignListResponse(
            session_id=str(session_id),
            campaigns=campaigns_response,
            total=len(campaigns_response),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating campaigns: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate campaigns: {str(e)}"
        )


@router.get("/{session_id}/campaigns", response_model=CampaignListResponse)
async def list_campaigns(session_id: UUID, user_id: str):
    """
    List all campaigns for a session.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership and get config
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id, config"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        session_config = session.data[0].get("config", {})

        # Get campaigns
        result = supabase.schema("keyword_analysis").table("campaigns").select(
            "*, campaign_keywords(id, keyword_id, bid, status)"
        ).eq("campaign_session_id", str(session_id)).execute()

        campaigns = []
        for c in result.data or []:
            campaigns.append(CampaignResponse(
                id=c["id"],
                name=c["name"],
                match_type=c["match_type"],
                root_group=c.get("root_group"),
                keyword_count=len(c.get("campaign_keywords", [])),
                daily_budget=c["daily_budget"],
                default_bid=c["default_bid"],
                keyword_bid=c.get("keyword_bid"),
                bidding_strategy=c["bidding_strategy"],
                start_date=str(c["start_date"]) if c.get("start_date") else "",
                status=c["status"],
                is_solo=c.get("is_solo", False),
                is_auto=c.get("is_auto", False),
                sv_tier=c.get("sv_tier"),
                calculated_base_bid=_compute_calculated_bid(c, session_config),
            ))

        return CampaignListResponse(
            session_id=str(session_id),
            campaigns=campaigns,
            total=len(campaigns),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing campaigns: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list campaigns: {str(e)}"
        )


@router.put("/{session_id}/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    session_id: UUID,
    campaign_id: UUID,
    request: UpdateCampaignRequest,
    user_id: str,
):
    """
    Update a single campaign's configuration.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership and get config
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id, config"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        session_config = session.data[0].get("config", {})

        # Build update data
        update_data = {}
        if request.name is not None:
            update_data["name"] = request.name
        if request.daily_budget is not None:
            update_data["daily_budget"] = float(request.daily_budget)
        if request.default_bid is not None:
            update_data["default_bid"] = float(request.default_bid)
        if request.keyword_bid is not None:
            update_data["keyword_bid"] = float(request.keyword_bid)
        if request.bidding_strategy is not None:
            update_data["bidding_strategy"] = request.bidding_strategy
        if request.start_date is not None:
            update_data["start_date"] = request.start_date
        if request.status is not None:
            update_data["status"] = request.status

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        # Update campaign
        result = supabase.schema("keyword_analysis").table("campaigns").update(
            update_data
        ).eq("id", str(campaign_id)).eq("campaign_session_id", str(session_id)).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found"
            )

        c = result.data[0]
        return CampaignResponse(
            id=c["id"],
            name=c["name"],
            match_type=c["match_type"],
            root_group=c.get("root_group"),
            keyword_count=0,  # Would need separate query
            daily_budget=c["daily_budget"],
            default_bid=c["default_bid"],
            keyword_bid=c.get("keyword_bid"),
            bidding_strategy=c["bidding_strategy"],
            start_date=str(c["start_date"]) if c.get("start_date") else "",
            status=c["status"],
            is_solo=c.get("is_solo", False),
            is_auto=c.get("is_auto", False),
            sv_tier=c.get("sv_tier"),
            calculated_base_bid=_compute_calculated_bid(c, session_config),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating campaign: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update campaign: {str(e)}"
        )


@router.delete("/{session_id}/campaigns/{campaign_id}")
async def delete_campaign(session_id: UUID, campaign_id: UUID, user_id: str):
    """
    Delete a campaign.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        # Delete campaign (CASCADE will delete keywords)
        result = supabase.schema("keyword_analysis").table("campaigns").delete().eq(
            "id", str(campaign_id)
        ).eq("campaign_session_id", str(session_id)).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found"
            )

        return {"success": True, "message": "Campaign deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting campaign: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete campaign: {str(e)}"
        )


# ============================================================================
# Campaign Negatives Endpoints
# ============================================================================


@router.get("/{session_id}/negatives", response_model=list[CampaignNegativeResponse])
async def list_negatives(session_id: UUID, user_id: str):
    """
    List all negative keywords for a campaign session.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        # Get negatives
        result = supabase.schema("keyword_analysis").table("campaign_negatives").select(
            "*"
        ).eq("campaign_session_id", str(session_id)).execute()

        return [
            CampaignNegativeResponse(
                id=n["id"],
                keyword_text=n["keyword_text"],
                match_type=n["match_type"],
            )
            for n in result.data or []
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing negatives: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list negatives: {str(e)}"
        )


@router.post("/{session_id}/negatives", response_model=CampaignNegativeResponse, status_code=status.HTTP_201_CREATED)
async def add_negative(
    session_id: UUID,
    request: CampaignNegativeRequest,
    user_id: str,
):
    """
    Add a negative keyword to the campaign session.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        # Validate match type
        if request.match_type not in ("negative_exact", "negative_phrase"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid match type. Use 'negative_exact' or 'negative_phrase'"
            )

        # Insert negative
        result = supabase.schema("keyword_analysis").table("campaign_negatives").insert({
            "campaign_session_id": str(session_id),
            "keyword_text": request.keyword_text.strip(),
            "match_type": request.match_type,
        }).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to add negative keyword"
            )

        n = result.data[0]
        return CampaignNegativeResponse(
            id=n["id"],
            keyword_text=n["keyword_text"],
            match_type=n["match_type"],
        )

    except HTTPException:
        raise
    except Exception as e:
        # Check for unique constraint violation
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Negative keyword already exists with this match type"
            )
        logger.error(f"Error adding negative: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add negative: {str(e)}"
        )


@router.delete("/{session_id}/negatives/{negative_id}")
async def delete_negative(session_id: UUID, negative_id: UUID, user_id: str):
    """
    Delete a negative keyword.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        # Delete negative
        result = supabase.schema("keyword_analysis").table("campaign_negatives").delete().eq(
            "id", str(negative_id)
        ).eq("campaign_session_id", str(session_id)).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Negative keyword not found"
            )

        return {"success": True, "message": "Negative keyword deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting negative: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete negative: {str(e)}"
        )


# ============================================================================
# Export Endpoints
# ============================================================================


@router.post("/{session_id}/export", response_model=ExportSummary)
async def export_bulk_sheet(
    session_id: UUID,
    request: ExportBulkSheetRequest,
    user_id: str,
):
    """
    Export campaigns as an Amazon SP bulk sheet.

    Returns summary of export; actual file download is a separate endpoint.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership and get config
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id, keyword_session_id, config"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        keyword_session_id = session.data[0]["keyword_session_id"]
        config = session.data[0].get("config", {})

        # Get campaigns for this session
        campaigns_result = supabase.schema("keyword_analysis").table("campaigns").select(
            "*, campaign_keywords(keyword_id)"
        ).eq("campaign_session_id", str(session_id)).execute()

        campaigns = campaigns_result.data or []

        # Filter by campaign_ids if provided
        if request.campaign_ids:
            campaign_id_set = set(request.campaign_ids)
            campaigns = [c for c in campaigns if c["id"] in campaign_id_set]

        # Get keywords
        keywords_result = supabase.schema("keyword_analysis").table("results").select(
            "id, keyword, search_volume"
        ).eq("session_id", keyword_session_id).execute()

        keywords = [
            ExportKeyword(
                id=kw["id"],
                normalized_text=kw["keyword"],
                original_text=kw["keyword"],
                search_volume=kw.get("search_volume", 0) or 0
            )
            for kw in (keywords_result.data or [])
        ]

        # Get negatives if requested
        campaign_negatives = {}
        if request.include_negatives:
            negatives_result = supabase.schema("keyword_analysis").table("campaign_negatives").select(
                "*"
            ).eq("campaign_session_id", str(session_id)).execute()

            # Group negatives by campaign (for now, all negatives apply globally)
            for c in campaigns:
                exact_negs = [
                    n["keyword_text"] for n in (negatives_result.data or [])
                    if n["match_type"] == "negative_exact"
                ]
                phrase_negs = [
                    n["keyword_text"] for n in (negatives_result.data or [])
                    if n["match_type"] == "negative_phrase"
                ]
                campaign_negatives[c["id"]] = CampaignNegatives(
                    exact=exact_negs,
                    phrase=phrase_negs
                )

        # Convert to export format
        export_campaigns = [
            ExportCampaign(
                id=c["id"],
                name=c["name"],
                match_type=c["match_type"],
                keyword_ids=[ck["keyword_id"] for ck in c.get("campaign_keywords", [])],
                daily_budget=c["daily_budget"],
                default_bid=c["default_bid"],
                keyword_bid=c.get("keyword_bid") or c["default_bid"],
                bidding_strategy=c["bidding_strategy"],
                start_date=str(c["start_date"]) if c.get("start_date") else "",
                status=c["status"],
                is_solo=c.get("is_solo", False),
                is_auto=c.get("is_auto", False),
                root_group=c.get("root_group"),
            )
            for c in campaigns
        ]

        # Get export summary
        summary = get_export_summary(export_campaigns, keywords, campaign_negatives)

        return ExportSummary(
            total_campaigns=summary["total_campaigns"],
            total_keywords=summary["total_keywords"],
            total_negatives=summary["total_negatives"],
            total_rows=summary["total_rows"],
            match_type_breakdown=summary["match_type_breakdown"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting bulk sheet: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export bulk sheet: {str(e)}"
        )


@router.post("/{session_id}/export/download")
async def download_bulk_sheet(
    session_id: UUID,
    request: DownloadBulkSheetRequest,
    user_id: str,
    format: str = "new",
):
    """
    Download the bulk sheet as an XLSX file.

    Format options:
    - 'new': Current Amazon bulk sheet format
    - 'legacy': Legacy bulk sheet format

    The request body can include campaign_negatives to override
    database-stored negatives (for client-side edits not yet saved).
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify session ownership and get config
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id, name, keyword_session_id, config"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        session_data = session.data[0]
        keyword_session_id = session_data["keyword_session_id"]
        config = session_data.get("config", {})
        session_name = session_data.get("name", "campaigns")

        # Use campaigns from request if provided (frontend-generated for consistency)
        # Otherwise fall back to database campaigns
        if request.campaigns:
            # Use frontend-provided campaigns - ensures report matches export
            export_campaigns = []
            keywords = []
            keyword_ids_seen = set()

            for c in request.campaigns:
                # Build keyword_ids from campaign keywords
                campaign_keyword_ids = []
                if c.keywords:
                    for kw in c.keywords:
                        campaign_keyword_ids.append(kw.id)
                        # Collect unique keywords for export
                        if kw.id not in keyword_ids_seen:
                            keyword_ids_seen.add(kw.id)
                            keywords.append(ExportKeyword(
                                id=kw.id,
                                normalized_text=kw.text,
                                original_text=kw.text,
                                search_volume=kw.sv
                            ))

                # Extract placement multiplier values
                pm_enabled = c.placement_multipliers_enabled
                pm = c.placement_multipliers

                export_campaigns.append(ExportCampaign(
                    id=c.id,
                    name=c.name,
                    match_type=c.match_type,
                    keyword_ids=campaign_keyword_ids,
                    daily_budget=Decimal(str(c.daily_budget)),
                    default_bid=Decimal(str(c.default_bid)),
                    keyword_bid=Decimal(str(c.keyword_bid)) if c.keyword_bid else Decimal(str(c.default_bid)),
                    bidding_strategy=c.bidding_strategy,
                    start_date=c.start_date or "",
                    status=c.status,
                    is_solo=False,
                    is_auto=c.is_auto,
                    root_group=c.root_group,
                    placement_multipliers_enabled=pm_enabled,
                    placement_top_of_search=pm.top_of_search if pm else 0,
                    placement_rest_of_search=pm.rest_of_search if pm else 0,
                    placement_product_page=pm.product_page if pm else 0,
                ))

            if not export_campaigns:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No campaigns to export"
                )
        else:
            # Fall back to database campaigns
            campaigns_result = supabase.schema("keyword_analysis").table("campaigns").select(
                "*, campaign_keywords(keyword_id)"
            ).eq("campaign_session_id", str(session_id)).execute()

            campaigns = campaigns_result.data or []

            if not campaigns:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No campaigns to export"
                )

            # Get keywords from database
            keywords_result = supabase.schema("keyword_analysis").table("results").select(
                "id, keyword, search_volume"
            ).eq("session_id", keyword_session_id).execute()

            keywords = [
                ExportKeyword(
                    id=kw["id"],
                    normalized_text=kw["keyword"],
                    original_text=kw["keyword"],
                    search_volume=kw.get("search_volume", 0) or 0
                )
                for kw in (keywords_result.data or [])
            ]

            export_campaigns = [
                ExportCampaign(
                    id=c["id"],
                    name=c["name"],
                    match_type=c["match_type"],
                    keyword_ids=[ck["keyword_id"] for ck in c.get("campaign_keywords", [])],
                    daily_budget=c["daily_budget"],
                    default_bid=c["default_bid"],
                    keyword_bid=c.get("keyword_bid") or c["default_bid"],
                    bidding_strategy=c["bidding_strategy"],
                    start_date=str(c["start_date"]) if c.get("start_date") else "",
                    status=c["status"],
                    is_solo=c.get("is_solo", False),
                    is_auto=c.get("is_auto", False),
                    root_group=c.get("root_group"),
                )
                for c in campaigns
            ]

        # Get negatives from request (keyed by campaign name)
        campaign_negatives = {}
        if request.campaign_negatives:
            for campaign_name, negs in request.campaign_negatives.items():
                campaign_negatives[campaign_name] = CampaignNegatives(
                    exact=negs.exact,
                    phrase=negs.phrase
                )

        # Get SKU/ASIN and account type from config
        sku = config.get("sku", "")
        account_type = config.get("account_type", "seller")

        # Build auto_targeting_groups from auto campaigns' keyword_ids
        # For auto campaigns, keyword_ids contains the selected targeting type IDs
        # (e.g., ["close_match", "loose_match"]). The exporter uses this to set
        # selected types as enabled and unselected types as paused.
        auto_targeting_groups = {}
        for c in export_campaigns:
            if c.is_auto and c.root_group is not None:
                auto_targeting_groups[c.root_group] = c.keyword_ids

        # Generate bulk sheet
        options = ExportOptions(
            include_campaign_rows=True,
            include_ad_group_rows=True,
            include_keyword_rows=True,
            include_product_ad_rows=True,
            sku=sku,
            account_type=account_type,
            format=format,
        )

        workbook = generate_bulk_sheet(
            campaigns=export_campaigns,
            keywords=keywords,
            overrides={},
            options=options,
            auto_targeting_groups=auto_targeting_groups if auto_targeting_groups else None,
            campaign_negatives=campaign_negatives,
        )

        # Convert to bytes
        xlsx_bytes = workbook_to_bytes(workbook)

        # Generate filename
        filename = f"{session_name or 'campaigns'}_bulk_sheet.xlsx"

        return StreamingResponse(
            iter([xlsx_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading bulk sheet: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download bulk sheet: {str(e)}"
        )
