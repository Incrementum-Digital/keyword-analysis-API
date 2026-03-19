"""
Campaign Builder API Router

Endpoints for creating and managing Amazon PPC campaign sessions,
keyword normalization, campaign generation, and bulk sheet export.
"""
import logging
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
    ExportBulkSheetRequest,
    ExportSummary,
    GenerateCampaignsRequest,
    NormalizeResponse,
    SaveNormalizationRequest,
    UpdateCampaignRequest,
    UpdateCampaignSessionRequest,
)
from supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaign-sessions", tags=["campaign-sessions"])


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
            "id"
        ).eq("keyword_session_id", request.keyword_session_id).execute()

        if existing.data:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Campaign session already exists for this keyword session"
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
            "keyword, search_volume"
        ).eq("session_id", keyword_session_id).execute()

        if not keywords_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No keywords found in keyword session"
            )

        # TODO: Implement normalization algorithm
        # For now, return empty groups - this will be implemented in Phase 2
        return NormalizeResponse(
            groups=[],
            total_keywords=len(keywords_result.data),
            total_groups=0,
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

        # TODO: Implement campaign generation algorithm
        # For now, return empty list - this will be implemented in Phase 3
        return CampaignListResponse(
            session_id=str(session_id),
            campaigns=[],
            total=0,
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
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

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
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

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
        # Verify session ownership
        session = supabase.schema("keyword_analysis").table("campaign_sessions").select(
            "id"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        # TODO: Implement bulk sheet export in Phase 4
        # For now, return summary with zeros
        return ExportSummary(
            total_campaigns=0,
            total_keywords=0,
            total_negatives=0,
            total_rows=0,
            match_type_breakdown={},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting bulk sheet: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export bulk sheet: {str(e)}"
        )


@router.get("/{session_id}/export/download")
async def download_bulk_sheet(
    session_id: UUID,
    user_id: str,
    format: str = "new",
):
    """
    Download the bulk sheet as an XLSX file.

    Format options:
    - 'new': Current Amazon bulk sheet format
    - 'legacy': Legacy bulk sheet format
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
            "id, name"
        ).eq("id", str(session_id)).eq("user_id", user_id).execute()

        if not session.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign session not found"
            )

        # TODO: Implement actual XLSX generation in Phase 4
        # For now, return a placeholder response
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Bulk sheet download not yet implemented"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading bulk sheet: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download bulk sheet: {str(e)}"
        )
