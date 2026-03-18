"""
Bulk Sheets API Router

Endpoints for uploading, managing, and querying Amazon PPC bulk sheets.
"""
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from bulk_sheet_models import (
    BulkSheetListItem,
    BulkSheetListResponse,
    BulkSheetTarget,
    BulkSheetTargetsResponse,
    BulkSheetUploadResponse,
    KeywordTargetingInfo,
    TargetingCheckRequest,
    TargetingCheckResponse,
)
from bulk_sheet_parser import normalize_keyword, parse_bulk_sheet
from supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bulk-sheets", tags=["bulk-sheets"])

# Maximum file size: 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024


@router.post("/upload", response_model=BulkSheetUploadResponse)
async def upload_bulk_sheet(
    file: UploadFile = File(...),
    account_name: str = Form(...),
    marketplace: str = Form(default="com"),
    user_id: str = Form(...),  # In production, extract from auth token
):
    """
    Upload and parse an Amazon PPC bulk sheet.

    - Parses CSV or XLSX files
    - Extracts keyword targeting data
    - Overwrites previous data for the same account
    - Returns bulk sheet ID and row count
    """
    # Validate file type
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided"
        )

    filename_lower = file.filename.lower()
    if not (filename_lower.endswith(".csv") or filename_lower.endswith((".xlsx", ".xls"))):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Use CSV or XLSX."
        )

    # Read file content
    try:
        content = await file.read()
    except Exception as e:
        logger.error(f"Failed to read uploaded file: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {str(e)}"
        )

    # Check file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB."
        )

    # Parse the bulk sheet
    try:
        parse_result = parse_bulk_sheet(content, file.filename)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error parsing bulk sheet: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse bulk sheet: {str(e)}"
        )

    if parse_result.row_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid keyword rows found in the bulk sheet."
        )

    # Get Supabase client
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        logger.error(f"Supabase not configured: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    # Normalize inputs
    account_name = account_name.strip()
    marketplace = marketplace.lower().strip()

    try:
        # Delete existing bulk sheet for this user+account (upsert behavior)
        # Due to UNIQUE constraint, we delete first then insert
        delete_result = supabase.schema("keyword_analysis").table("bulk_sheets").delete().match({
            "user_id": user_id,
            "account_name": account_name
        }).execute()

        logger.info(f"Deleted existing bulk sheet for user={user_id}, account={account_name}")

        # Insert new bulk sheet
        bulk_sheet_data = {
            "user_id": user_id,
            "account_name": account_name,
            "marketplace": marketplace,
            "file_name": file.filename,
            "row_count": parse_result.row_count,
        }

        insert_result = supabase.schema("keyword_analysis").table("bulk_sheets").insert(
            bulk_sheet_data
        ).execute()

        if not insert_result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create bulk sheet record"
            )

        bulk_sheet_id = insert_result.data[0]["id"]
        logger.info(f"Created bulk sheet {bulk_sheet_id} with {parse_result.row_count} targets")

        # Insert targets
        if parse_result.targets:
            targets_data = [
                {
                    "bulk_sheet_id": bulk_sheet_id,
                    "campaign_name": t.campaign_name,
                    "ad_group_name": t.ad_group_name,
                    "keyword": t.keyword,
                    "keyword_normalized": t.keyword_normalized,
                    "match_type": t.match_type,
                    "targeting_type": t.targeting_type,
                    "state": t.state,
                    "bid": float(t.bid) if t.bid else None,
                }
                for t in parse_result.targets
            ]

            # Insert in batches of 1000
            batch_size = 1000
            for i in range(0, len(targets_data), batch_size):
                batch = targets_data[i:i + batch_size]
                supabase.schema("keyword_analysis").table("bulk_sheet_targets").insert(batch).execute()

            logger.info(f"Inserted {len(targets_data)} targets for bulk sheet {bulk_sheet_id}")

        return BulkSheetUploadResponse(
            bulk_sheet_id=bulk_sheet_id,
            account_name=account_name,
            marketplace=marketplace,
            file_name=file.filename,
            row_count=parse_result.row_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database error during bulk sheet upload: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.get("", response_model=BulkSheetListResponse)
async def list_bulk_sheets(user_id: str):
    """
    List all bulk sheets for a user.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        result = supabase.schema("keyword_analysis").table("bulk_sheets").select(
            "id, account_name, marketplace, file_name, uploaded_at, row_count"
        ).eq("user_id", user_id).order("uploaded_at", desc=True).execute()

        bulk_sheets = [
            BulkSheetListItem(
                id=row["id"],
                account_name=row["account_name"],
                marketplace=row["marketplace"],
                file_name=row["file_name"],
                uploaded_at=row["uploaded_at"],
                row_count=row["row_count"],
            )
            for row in result.data
        ]

        return BulkSheetListResponse(
            bulk_sheets=bulk_sheets,
            total=len(bulk_sheets)
        )

    except Exception as e:
        logger.error(f"Error listing bulk sheets: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list bulk sheets: {str(e)}"
        )


@router.get("/{bulk_sheet_id}/targets", response_model=BulkSheetTargetsResponse)
async def get_bulk_sheet_targets(
    bulk_sheet_id: UUID,
    keywords: Optional[str] = None,
    user_id: str = "",
):
    """
    Get targets from a bulk sheet.

    Optionally filter by normalized keywords (comma-separated).
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify user owns this bulk sheet
        ownership = supabase.schema("keyword_analysis").table("bulk_sheets").select(
            "id"
        ).eq("id", str(bulk_sheet_id)).eq("user_id", user_id).execute()

        if not ownership.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bulk sheet not found"
            )

        # Build query
        query = supabase.schema("keyword_analysis").table("bulk_sheet_targets").select(
            "campaign_name, ad_group_name, keyword, keyword_normalized, match_type, targeting_type, state, bid"
        ).eq("bulk_sheet_id", str(bulk_sheet_id))

        # Filter by keywords if provided
        if keywords:
            keyword_list = [normalize_keyword(kw) for kw in keywords.split(",") if kw.strip()]
            if keyword_list:
                query = query.in_("keyword_normalized", keyword_list)

        result = query.execute()

        targets = [
            BulkSheetTarget(
                campaign_name=row.get("campaign_name"),
                ad_group_name=row.get("ad_group_name"),
                keyword=row["keyword"],
                keyword_normalized=row["keyword_normalized"],
                match_type=row["match_type"],
                targeting_type=row.get("targeting_type", "keyword"),
                state=row.get("state", "enabled"),
                bid=row.get("bid"),
            )
            for row in result.data
        ]

        return BulkSheetTargetsResponse(
            targets=targets,
            total=len(targets)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting bulk sheet targets: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get targets: {str(e)}"
        )


@router.delete("/{bulk_sheet_id}")
async def delete_bulk_sheet(bulk_sheet_id: UUID, user_id: str):
    """
    Delete a bulk sheet and all its targets.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Delete bulk sheet (CASCADE will delete targets)
        result = supabase.schema("keyword_analysis").table("bulk_sheets").delete().match({
            "id": str(bulk_sheet_id),
            "user_id": user_id
        }).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bulk sheet not found"
            )

        return {"success": True, "message": "Bulk sheet deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting bulk sheet: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete bulk sheet: {str(e)}"
        )


@router.post("/check-targeting", response_model=TargetingCheckResponse)
async def check_targeting(request: TargetingCheckRequest, user_id: str = ""):
    """
    Check which keywords are already targeted in a bulk sheet.

    Returns targeting status for each keyword including match types and campaigns.
    """
    try:
        supabase = get_supabase_client()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )

    try:
        # Verify user owns this bulk sheet
        ownership = supabase.schema("keyword_analysis").table("bulk_sheets").select(
            "id"
        ).eq("id", str(request.bulk_sheet_id)).eq("user_id", user_id).execute()

        if not ownership.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bulk sheet not found"
            )

        # Normalize input keywords
        normalized_keywords = [normalize_keyword(kw) for kw in request.keywords]

        # Query targets matching these keywords
        result = supabase.schema("keyword_analysis").table("bulk_sheet_targets").select(
            "keyword_normalized, match_type, campaign_name"
        ).eq("bulk_sheet_id", str(request.bulk_sheet_id)).in_(
            "keyword_normalized", normalized_keywords
        ).execute()

        # Build targeting map
        targeting_map: dict = {}
        for row in result.data:
            norm_kw = row["keyword_normalized"]
            if norm_kw not in targeting_map:
                targeting_map[norm_kw] = {
                    "match_types": set(),
                    "campaigns": set()
                }
            targeting_map[norm_kw]["match_types"].add(row["match_type"])
            if row["campaign_name"]:
                targeting_map[norm_kw]["campaigns"].add(row["campaign_name"])

        # Build response for each requested keyword
        targeting = {}
        for kw in request.keywords:
            norm_kw = normalize_keyword(kw)
            if norm_kw in targeting_map:
                data = targeting_map[norm_kw]
                targeting[kw] = KeywordTargetingInfo(
                    is_targeted=True,
                    match_types=sorted(list(data["match_types"])),
                    campaigns=sorted(list(data["campaigns"]))
                )
            else:
                targeting[kw] = KeywordTargetingInfo(
                    is_targeted=False,
                    match_types=[],
                    campaigns=[]
                )

        return TargetingCheckResponse(targeting=targeting)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking targeting: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check targeting: {str(e)}"
        )
