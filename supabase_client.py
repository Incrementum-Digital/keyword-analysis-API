"""
Supabase client for database operations
"""
import os
import logging
from typing import Optional

from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Environment variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Get or create Supabase client singleton.
    Uses service role key for backend operations (bypasses RLS).
    """
    global _client

    if _client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "Supabase configuration missing. "
                "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables."
            )
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        logger.info("Supabase client initialized")

    return _client


def is_supabase_configured() -> bool:
    """Check if Supabase environment variables are configured."""
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
