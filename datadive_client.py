"""
Data Dive API client for fetching niche research data.
"""
import os
import httpx
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Data Dive API configuration
DATADIVE_API_URL = os.environ.get("DATADIVE_API_URL", "https://api.datadive.tools")
DATADIVE_API_KEY = os.environ.get("DATADIVE_API_KEY")


class DataDiveClient:
    """Client for interacting with Data Dive API."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        Initialize Data Dive client.

        Args:
            api_key: API key for authentication. Defaults to env var DATADIVE_API_KEY.
            base_url: Base URL for API. Defaults to env var DATADIVE_API_URL.
        """
        self.api_key = api_key or DATADIVE_API_KEY
        self.base_url = (base_url or DATADIVE_API_URL).rstrip("/")

        if not self.api_key:
            raise ValueError("DATADIVE_API_KEY not found in environment variables")

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            "x-api-key": self.api_key,
            "accept": "application/json",
        }

    async def get_niche_roots(self, niche_id: str) -> Dict[str, Any]:
        """
        Fetch keyword roots for a niche.

        Args:
            niche_id: The unique identifier of the niche.

        Returns:
            Dictionary containing:
                - roots: List of root keywords with frequency and search volume
                - normalizedRoots: Normalized version of roots
                - keywords: Original keywords with normalized mappings
                - consolidatedKeywords: Grouped by normalized form
                - latestResearchDate: When niche was last researched

        Raises:
            httpx.HTTPStatusError: If API returns error status
            Exception: If API returns error in response body
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/v1/niches/{niche_id}/roots",
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()

            # Check for API-level errors
            if "error" in result:
                raise Exception(f"Data Dive API error: {result['error']}")

            return result.get("data", [{}])[0] if result.get("data") else result

    async def get_master_keyword_list(self, niche_id: str) -> Dict[str, Any]:
        """
        Fetch master keyword list for a niche.

        Args:
            niche_id: The unique identifier of the niche.

        Returns:
            Dictionary containing:
                - keywords: List of keywords with searchVolume, relevancy, ranks
                - latestResearchDate: When niche was last researched

        Raises:
            httpx.HTTPStatusError: If API returns error status
            Exception: If API returns error in response body
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/v1/niches/{niche_id}/keywords",
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()

            if "error" in result:
                raise Exception(f"Data Dive API error: {result['error']}")

            return result.get("data", [{}])[0] if result.get("data") else result

    async def list_niches(
        self, page: int = 1, page_size: int = 20
    ) -> Dict[str, Any]:
        """
        List all niches with pagination.

        Args:
            page: Page number (default: 1)
            page_size: Items per page (default: 20, max: 50)

        Returns:
            Dictionary containing:
                - currentPage, pageSize, hasNext, hasPrev, lastPage, total
                - data: List of niche items
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.base_url}/v1/niches",
                headers=self._get_headers(),
                params={"currentPage": page, "pageSize": page_size},
            )
            response.raise_for_status()
            return response.json()


def compare_root_analysis(
    datadive_roots: List[Dict[str, Any]],
    local_roots: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compare Data Dive roots with local algorithm output.

    Args:
        datadive_roots: List of roots from Data Dive API
            Each item has: root, frequency, broadSearchVolume, broadSearchVolumeRatio
        local_roots: List of roots from local algorithm
            Each item has: normalized_term, frequency, search_volume, relative_volume

    Returns:
        Comparison report with match rate and detailed differences.
    """
    # Build lookup maps
    dd_map = {r["root"]: r for r in datadive_roots}
    local_map = {r["normalized_term"]: r for r in local_roots}

    matches = []
    mismatches = []
    only_datadive = []
    only_local = []

    # Compare Data Dive roots against local
    for root, dd_data in dd_map.items():
        if root in local_map:
            local_data = local_map[root]

            # Check if frequency and search volume match
            freq_match = dd_data.get("frequency") == local_data.get("frequency")
            sv_match = dd_data.get("broadSearchVolume") == local_data.get("search_volume")

            if freq_match and sv_match:
                matches.append(root)
            else:
                mismatches.append({
                    "root": root,
                    "datadive": {
                        "frequency": dd_data.get("frequency"),
                        "broadSearchVolume": dd_data.get("broadSearchVolume"),
                    },
                    "local": {
                        "frequency": local_data.get("frequency"),
                        "search_volume": local_data.get("search_volume"),
                    },
                    "differences": {
                        "frequency": not freq_match,
                        "search_volume": not sv_match,
                    },
                })
        else:
            only_datadive.append({
                "root": root,
                "frequency": dd_data.get("frequency"),
                "broadSearchVolume": dd_data.get("broadSearchVolume"),
            })

    # Find roots only in local
    for root in local_map:
        if root not in dd_map:
            local_data = local_map[root]
            only_local.append({
                "root": root,
                "frequency": local_data.get("frequency"),
                "search_volume": local_data.get("search_volume"),
            })

    # Calculate match rate
    total = len(dd_map)
    match_count = len(matches)
    match_rate = (match_count / total * 100) if total > 0 else 0

    return {
        "summary": {
            "match_rate": round(match_rate, 2),
            "total_datadive_roots": total,
            "total_local_roots": len(local_map),
            "exact_matches": match_count,
            "mismatches": len(mismatches),
            "only_in_datadive": len(only_datadive),
            "only_in_local": len(only_local),
            "passed": match_rate >= 95,
        },
        "matches": matches,
        "mismatches": mismatches,
        "only_datadive": only_datadive,
        "only_local": only_local,
    }
