"""
FastAPI application for keyword analysis
"""
import asyncio
import logging
import sys
import time
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import os

# Load environment variables early
load_dotenv()

# Configure logging
log_level = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Initialize Sentry for error tracking
SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get("RAILWAY_ENVIRONMENT", "development"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.2")),
    )
    logger.info(f"Sentry initialized for environment: {os.environ.get('RAILWAY_ENVIRONMENT', 'development')}")

from models import (
    KeywordAnalysisRequest,
    KeywordAnalysisResponse,
    ProductDetails,
    AnalysisSummary,
    RootAnalysisRequest,
    RootAnalysisResponse,
    NegativePhraseRequest,
    RootComparisonRequest,
    RootComparisonResponse,
)
from keepa_client import get_basic_product_details
from keyword_analyzer import analyze_keywords
from root_analysis_service import generate_root_analysis
from negative_phrase_service import generate_negative_phrases
from datadive_client import DataDiveClient, compare_root_analysis
from bulk_sheets_router import router as bulk_sheets_router
from campaign_router import router as campaign_router
from supabase_client import is_supabase_configured

# Create FastAPI app
app = FastAPI(
    title="Keyword Analysis API",
    description="Analyze Amazon keywords for product relevance using AI",
    version="1.0.0"
)

# Configure CORS - use environment variable for frontend URL
frontend_url = os.environ.get("FRONTEND_URL", "*")
allowed_origins = [frontend_url] if frontend_url != "*" else ["*"]

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Include routers
app.include_router(bulk_sheets_router)
app.include_router(campaign_router)


# Global exception handler for unhandled errors
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions gracefully"""
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again later."}
    )


# Startup event
@app.on_event("startup")
async def startup_event():
    """Log startup information"""
    logger.info("Keyword Analysis API starting up...")
    logger.info(f"Workers: {os.environ.get('WORKERS', 'default')}")
    logger.info(f"Max concurrent requests: {os.environ.get('MAX_CONCURRENT_REQUESTS', '10')}")
    logger.info(f"Model: {os.environ.get('OPENROUTER_MODEL', 'google/gemini-2.5-flash-lite')}")


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Keyword Analysis API",
        "version": "1.0.0",
        "endpoints": {
            "POST /analyze-keywords": "Analyze keywords for product relevance",
            "POST /root-analysis": "Generate normalized root keywords from CSV data",
            "POST /negative-phrase": "Generate Amazon PPC negative keyword list",
            "POST /validation/compare-roots": "Compare local root analysis with Data Dive",
            "POST /bulk-sheets/upload": "Upload Amazon PPC bulk sheet",
            "GET /bulk-sheets": "List user's bulk sheets",
            "GET /bulk-sheets/{id}/targets": "Get targets from bulk sheet",
            "DELETE /bulk-sheets/{id}": "Delete bulk sheet",
            "POST /bulk-sheets/check-targeting": "Check keyword targeting status",
            "POST /campaign-sessions": "Create campaign session from keyword session",
            "GET /campaign-sessions/{id}": "Get campaign session with all data",
            "PUT /campaign-sessions/{id}": "Update campaign session config",
            "POST /campaign-sessions/{id}/normalize": "Generate normalization suggestions",
            "PUT /campaign-sessions/{id}/normalize": "Save normalization decisions",
            "POST /campaign-sessions/{id}/campaigns": "Generate campaigns from keywords",
            "GET /campaign-sessions/{id}/campaigns": "List campaigns for session",
            "PUT /campaign-sessions/{id}/campaigns/{cid}": "Update a campaign",
            "DELETE /campaign-sessions/{id}/campaigns/{cid}": "Delete a campaign",
            "GET /campaign-sessions/{id}/negatives": "List negative keywords",
            "POST /campaign-sessions/{id}/negatives": "Add negative keyword",
            "DELETE /campaign-sessions/{id}/negatives/{nid}": "Delete negative keyword",
            "POST /campaign-sessions/{id}/export": "Generate bulk sheet export",
            "GET /campaign-sessions/{id}/export/download": "Download bulk sheet XLSX",
        },
        "documentation": "/docs"
    }


@app.post("/analyze-keywords", response_model=KeywordAnalysisResponse)
async def analyze_keywords_endpoint(request: KeywordAnalysisRequest):
    """
    Analyze keywords for product relevance
    
    Accepts either:
    1. ASIN + country (fetches product details from Keepa)
    2. Product description text (uses directly for analysis)
    """
    
    # Validate input type
    try:
        request.validate_input_type()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    # Start timing
    start_time = time.time()
    
    # Determine input type and prepare product details
    input_type = "asin" if request.asin else "description"
    product_details = None
    product_description = None
    errors = []
    
    try:
        if input_type == "asin":
            # Fetch product details from Keepa
            logger.info(f"Fetching product details for ASIN: {request.asin}")
            try:
                keepa_data = get_basic_product_details(request.asin, request.country)
                product_details = ProductDetails(**keepa_data)
            except Exception as e:
                # If Keepa fails, return error
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Failed to fetch product details from Keepa: {str(e)}"
                )
        else:
            # Use provided description
            product_description = request.product_description
            product_details = ProductDetails(raw_description=product_description)
        
        # Analyze keywords
        logger.info(f"Analyzing {len(request.keywords)} keywords...")
        analysis_results = await analyze_keywords(
            keywords=request.keywords,
            product_details=product_details if input_type == "asin" else None,
            product_description=product_description if input_type == "description" else None,
            retry_failed=True
        )
        
        # Calculate summary statistics
        analyzed_count = len(analysis_results)
        failed_count = len(request.keywords) - analyzed_count
        
        # Count by type
        by_type = {}
        total_score = 0
        for result in analysis_results:
            by_type[result.type] = by_type.get(result.type, 0) + 1
            total_score += result.score
        
        # Calculate average score
        average_score = total_score / analyzed_count if analyzed_count > 0 else 0
        
        # Processing time
        processing_time = time.time() - start_time
        
        # Create summary
        summary = AnalysisSummary(
            total_keywords=len(request.keywords),
            analyzed=analyzed_count,
            failed=failed_count,
            by_type=by_type,
            average_score=round(average_score, 2) if average_score > 0 else None,
            processing_time=round(processing_time, 2)
        )
        
        # Add any failed keywords to errors
        if failed_count > 0:
            failed_keywords = set(request.keywords) - {r.keyword for r in analysis_results}
            errors.append(f"Failed to analyze {failed_count} keywords: {', '.join(list(failed_keywords)[:10])}")
        
        # Create response
        response = KeywordAnalysisResponse(
            input_type=input_type,
            product_info=product_details,
            analysis_results=analysis_results,
            summary=summary,
            errors=errors if errors else None
        )
        
        logger.info(f"Analysis complete in {processing_time:.2f}s - {analyzed_count}/{len(request.keywords)} keywords")
        return response
        
    except HTTPException:
        raise
    except RuntimeError as e:
        error_msg = str(e).lower()
        logger.error(f"Runtime error during analysis: {str(e)}", exc_info=True)
        if "rate limit" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again in 1 minute."
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error during analysis: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}"
        )


@app.post("/root-analysis", response_model=RootAnalysisResponse)
async def root_analysis_endpoint(request: RootAnalysisRequest):
    """Aggregate uploaded keyword rows into normalized roots."""

    rows = [(row.keyword.strip(), row.search_volume) for row in request.keywords if row.keyword.strip()]
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid keywords supplied")

    try:
        payload = generate_root_analysis(rows, request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - safeguard for unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Root analysis failed: {str(exc)}"
        ) from exc

    return RootAnalysisResponse(**payload)


@app.post("/negative-phrase", response_model=List[str])
async def negative_phrase_endpoint(request: NegativePhraseRequest) -> List[str]:
    """Generate negative keyword phrases for Amazon PPC campaigns."""

    try:
        keepa_data = get_basic_product_details(request.asin, request.country)
    except Exception as exc:  # pragma: no cover - Keepa availability
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to fetch product details from Keepa: {str(exc)}"
        ) from exc

    product_details = ProductDetails(**keepa_data)

    try:
        phrases = await generate_negative_phrases(product_details)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc
    except RuntimeError as exc:  # pragma: no cover - upstream issues
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc)
        ) from exc
    except Exception as exc:  # pragma: no cover - safeguard
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Negative phrase generation failed: {str(exc)}"
        ) from exc

    return phrases


@app.post("/validation/compare-roots", response_model=RootComparisonResponse)
async def compare_roots_endpoint(request: RootComparisonRequest):
    """
    Compare local root keyword analysis with Data Dive.

    Fetches the master keyword list and roots from Data Dive for the given niche,
    runs the local root analysis algorithm on the same keywords, and produces
    a detailed comparison report.

    This endpoint is useful for validating that the local algorithm matches
    Data Dive's output, ensuring consistent campaign grouping behavior.
    """
    try:
        # Initialize Data Dive client
        client = DataDiveClient()

        # Fetch data from Data Dive
        logger.info(f"Fetching Data Dive roots for niche: {request.niche_id}")
        dd_roots_data = await client.get_niche_roots(request.niche_id)
        dd_mkl_data = await client.get_master_keyword_list(request.niche_id)

        # Extract normalized roots from Data Dive response (MKL normalized roots)
        dd_roots = dd_roots_data.get("normalizedRoots", [])
        if not dd_roots:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No normalizedRoots found for niche: {request.niche_id}"
            )

        # Extract keywords for local analysis
        dd_keywords = dd_mkl_data.get("keywords", [])
        if not dd_keywords:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No keywords found for niche: {request.niche_id}"
            )

        # Prepare keyword rows for local analysis
        keyword_rows = [
            (kw.get("keyword", ""), kw.get("searchVolume", 0))
            for kw in dd_keywords
            if kw.get("keyword")
        ]

        if not keyword_rows:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid keywords to analyze"
            )

        # Run local root analysis
        logger.info(f"Running local root analysis on {len(keyword_rows)} keywords")
        local_result = generate_root_analysis(keyword_rows, mode="full")
        local_roots = local_result.get("results", [])

        # Compare results
        comparison = compare_root_analysis(dd_roots, local_roots)

        logger.info(
            f"Root comparison complete: {comparison['summary']['match_rate']}% match rate, "
            f"passed={comparison['summary']['passed']}"
        )

        return RootComparisonResponse(**comparison)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Root comparison failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Root comparison failed: {str(e)}"
        )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Check if required API keys are configured
    openrouter_configured = bool(os.environ.get("OPENROUTER_API_KEY"))
    keepa_configured = bool(os.environ.get("KEEPA_API_KEY")) and os.environ.get("KEEPA_API_KEY") != "your_keepa_api_key_here"
    datadive_configured = bool(os.environ.get("DATADIVE_API_KEY"))
    supabase_configured = is_supabase_configured()

    max_concurrent = os.environ.get("MAX_CONCURRENT_REQUESTS", "0")
    concurrency_desc = "unlimited (all at once)" if max_concurrent == "0" else max_concurrent

    return {
        "status": "healthy",
        "configuration": {
            "openrouter_api_key": "configured" if openrouter_configured else "missing",
            "keepa_api_key": "configured" if keepa_configured else "missing",
            "datadive_api_key": "configured" if datadive_configured else "missing",
            "supabase": "configured" if supabase_configured else "missing",
            "model": os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash-lite"),
            "batch_size": os.environ.get("BATCH_SIZE", 30),
            "max_concurrent_requests": concurrency_desc
        }
    }


@app.get("/health/sentry-test")
async def test_sentry(trigger_error: bool = False):
    """
    Test Sentry integration.

    - GET /health/sentry-test - Shows Sentry config debug info
    - GET /health/sentry-test?trigger_error=true - Triggers a test error

    DELETE THIS ENDPOINT AFTER TESTING
    """
    import sentry_sdk

    # Debug info
    debug_info = {
        "sentry_dsn_configured": bool(os.environ.get("SENTRY_DSN")),
        "sentry_environment": os.environ.get("RAILWAY_ENVIRONMENT", "development"),
        "sentry_sdk_initialized": sentry_sdk.is_initialized(),
        "sentry_hub_client": str(sentry_sdk.Hub.current.client),
    }

    if trigger_error:
        # Send a test message first
        sentry_sdk.capture_message("Sentry test message from keyword-analysis-API")
        # Then raise an exception
        raise Exception("Sentry test error - keyword-analysis-API")

    return debug_info


if __name__ == "__main__":
    import uvicorn

    # Run the FastAPI app (development only)
    logger.info("Starting Keyword Analysis API (development mode)...")
    logger.info("Documentation available at: http://localhost:8000/docs")
    logger.info("Health check at: http://localhost:8000/health")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=True
    )
