"""
Amazon PPC Bulk Sheet Parser

Parses CSV and XLSX bulk sheets exported from Amazon Advertising Console.
Extracts keyword targeting data for matching against keyword analysis results.
"""
import logging
from io import BytesIO
from typing import List, Tuple

import pandas as pd

from bulk_sheet_models import BulkSheetTarget, ParseResult, ParseErrorDetail

logger = logging.getLogger(__name__)

# Amazon bulk sheet column mappings
COLUMN_MAP = {
    "Record Type": "record_type",
    "Campaign Name": "campaign_name",
    "Ad Group Name": "ad_group_name",
    "Keyword": "keyword",
    "Match Type": "match_type",
    "State": "state",
    "Bid": "bid",
    # Alternative column names (some exports use different names)
    "record_type": "record_type",
    "campaign_name": "campaign_name",
    "ad_group_name": "ad_group_name",
    "keyword": "keyword",
    "match_type": "match_type",
    "state": "state",
    "bid": "bid",
    # Handle variations
    "Keyword Text": "keyword",
    "Campaign": "campaign_name",
    "Ad Group": "ad_group_name",
}

# Match type normalization
MATCH_TYPE_MAP = {
    "exact": "exact",
    "phrase": "phrase",
    "broad": "broad",
    "Exact": "exact",
    "Phrase": "phrase",
    "Broad": "broad",
    "EXACT": "exact",
    "PHRASE": "phrase",
    "BROAD": "broad",
}

# Record types that indicate keyword rows
KEYWORD_RECORD_TYPES = {"Keyword", "keyword", "KEYWORD"}


def normalize_keyword(keyword: str) -> str:
    """
    Normalize keyword for consistent matching.

    - Lowercase
    - Strip whitespace
    - Collapse multiple spaces to single space
    """
    return " ".join(keyword.lower().strip().split())


def _detect_file_type(filename: str) -> str:
    """Detect file type from filename extension."""
    filename_lower = filename.lower()
    if filename_lower.endswith(".csv"):
        return "csv"
    elif filename_lower.endswith((".xlsx", ".xls")):
        return "excel"
    else:
        raise ValueError(f"Unsupported file format: {filename}. Use CSV or XLSX.")


def _read_file_to_dataframe(file_content: bytes, filename: str) -> pd.DataFrame:
    """Read file content into a pandas DataFrame."""
    file_type = _detect_file_type(filename)

    try:
        if file_type == "csv":
            # Try different encodings
            for encoding in ["utf-8", "latin-1", "cp1252"]:
                try:
                    return pd.read_csv(BytesIO(file_content), encoding=encoding)
                except UnicodeDecodeError:
                    continue
            raise ValueError("Could not decode CSV file. Check file encoding.")
        else:
            return pd.read_excel(BytesIO(file_content), engine="openpyxl")
    except Exception as e:
        logger.error(f"Failed to read file {filename}: {e}")
        raise ValueError(f"Failed to read file: {str(e)}")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to standardized names."""
    # Create a mapping for columns that exist in the dataframe
    rename_map = {}
    for col in df.columns:
        col_str = str(col).strip()
        if col_str in COLUMN_MAP:
            rename_map[col] = COLUMN_MAP[col_str]

    return df.rename(columns=rename_map)


def _filter_keyword_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Filter dataframe to only include keyword rows."""
    if "record_type" in df.columns:
        # Filter by record type
        mask = df["record_type"].astype(str).str.strip().isin(KEYWORD_RECORD_TYPES)
        return df[mask].copy()
    else:
        # No record type column - assume all rows are keywords
        # but require keyword and match_type columns
        return df.copy()


def _validate_required_columns(df: pd.DataFrame) -> Tuple[bool, List[str]]:
    """Check that required columns exist."""
    required = ["keyword", "match_type"]
    missing = [col for col in required if col not in df.columns]
    return len(missing) == 0, missing


def _parse_row(row: pd.Series, row_num: int) -> Tuple[BulkSheetTarget | None, ParseErrorDetail | None]:
    """Parse a single row into a BulkSheetTarget."""
    try:
        # Get and validate keyword
        keyword = str(row.get("keyword", "")).strip()
        if not keyword or keyword.lower() == "nan":
            return None, None  # Skip empty rows silently

        # Get and validate match type
        match_type_raw = str(row.get("match_type", "")).strip()
        match_type = MATCH_TYPE_MAP.get(match_type_raw)
        if not match_type:
            return None, ParseErrorDetail(
                row=row_num,
                error=f"Invalid match type: {match_type_raw}"
            )

        # Parse optional fields
        campaign_name = str(row.get("campaign_name", "")).strip()
        ad_group_name = str(row.get("ad_group_name", "")).strip()
        state = str(row.get("state", "enabled")).strip().lower()

        # Parse bid (handle NaN and empty values)
        bid = None
        bid_raw = row.get("bid")
        if pd.notna(bid_raw):
            try:
                bid = float(bid_raw)
            except (ValueError, TypeError):
                pass  # Keep bid as None if invalid

        # Clean up empty strings
        if campaign_name.lower() in ("nan", ""):
            campaign_name = None
        if ad_group_name.lower() in ("nan", ""):
            ad_group_name = None
        if state.lower() in ("nan", ""):
            state = "enabled"

        return BulkSheetTarget(
            campaign_name=campaign_name,
            ad_group_name=ad_group_name,
            keyword=keyword,
            keyword_normalized=normalize_keyword(keyword),
            match_type=match_type,
            targeting_type="keyword",
            state=state,
            bid=bid
        ), None

    except Exception as e:
        return None, ParseErrorDetail(row=row_num, error=str(e))


def parse_bulk_sheet(file_content: bytes, filename: str) -> ParseResult:
    """
    Parse an Amazon PPC bulk sheet (CSV or XLSX).

    Args:
        file_content: Raw file bytes
        filename: Original filename (used to detect format)

    Returns:
        ParseResult with targets and metadata

    Raises:
        ValueError: If file format is unsupported or required columns are missing
    """
    logger.info(f"Parsing bulk sheet: {filename}")

    # Read file into DataFrame
    df = _read_file_to_dataframe(file_content, filename)
    original_row_count = len(df)
    logger.info(f"Read {original_row_count} rows from {filename}")

    # Normalize column names
    df = _normalize_columns(df)

    # Filter to keyword rows only
    df = _filter_keyword_rows(df)
    logger.info(f"Found {len(df)} keyword rows after filtering")

    # Validate required columns
    valid, missing = _validate_required_columns(df)
    if not valid:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    # Parse each row
    targets: List[BulkSheetTarget] = []
    errors: List[ParseErrorDetail] = []
    skipped = 0

    for idx, row in df.iterrows():
        row_num = int(idx) + 2  # +2 for header row and 0-indexing
        target, error = _parse_row(row, row_num)

        if error:
            errors.append(error)
        elif target:
            targets.append(target)
        else:
            skipped += 1

    logger.info(
        f"Parse complete: {len(targets)} targets, "
        f"{skipped} skipped, {len(errors)} errors"
    )

    return ParseResult(
        targets=targets,
        row_count=len(targets),
        skipped_rows=skipped,
        errors=errors[:100]  # Limit errors to first 100
    )


def check_targeting_status(
    normalized_keywords: List[str],
    targets: List[BulkSheetTarget]
) -> dict:
    """
    Check which keywords are already targeted in the bulk sheet.

    Args:
        normalized_keywords: List of normalized keywords to check
        targets: List of parsed bulk sheet targets

    Returns:
        Dict mapping each keyword to its targeting info
    """
    # Build a lookup map: normalized_keyword -> list of targets
    target_map: dict = {}
    for target in targets:
        norm_kw = target.keyword_normalized
        if norm_kw not in target_map:
            target_map[norm_kw] = []
        target_map[norm_kw].append(target)

    # Check each keyword
    result = {}
    for kw in normalized_keywords:
        norm_kw = normalize_keyword(kw)
        matching_targets = target_map.get(norm_kw, [])

        if matching_targets:
            match_types = list(set(t.match_type for t in matching_targets))
            campaigns = list(set(t.campaign_name for t in matching_targets if t.campaign_name))
            result[kw] = {
                "is_targeted": True,
                "match_types": sorted(match_types),
                "campaigns": sorted(campaigns)
            }
        else:
            result[kw] = {
                "is_targeted": False,
                "match_types": [],
                "campaigns": []
            }

    return result
