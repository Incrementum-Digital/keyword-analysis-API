---
title: "fix: Display calculated base bid instead of max bid in campaign preview and export"
type: fix
status: completed
date: 2026-04-07
---

# fix: Display calculated base bid instead of max bid in campaign preview and export

## Overview

The campaign preview API response (`CampaignResponse`) currently returns `keyword_bid` which is the raw "Max Bid" the user configured. The user expects to see the **calculated base bid** -- the actual bid that will be written to the bulk sheet after accounting for bidding strategy (Dynamic Up & Down divides by 2) and placement multipliers. This change adds `calculated_base_bid` to the campaign preview response so the frontend can display it.

## Problem Frame

The `calculate_base_bid()` function already exists in `bulk_sheet_exporter.py` and correctly computes the base bid at export time. But the preview response never exposes this value -- it only shows the raw `keyword_bid` (Max Bid). The frontend has no way to display the calculated bid in the campaign preview table without duplicating the calculation logic client-side.

## Requirements Trace

- R1. `CampaignResponse` must include a `calculated_base_bid` field showing the bid adjusted for bidding strategy and placement multipliers
- R2. All endpoints that return `CampaignResponse` must compute and populate `calculated_base_bid`
- R3. The calculation must use the same `calculate_base_bid()` function used during export (single source of truth)

## Scope Boundaries

- NOT changing the export XLSX output -- `bulk_sheet_exporter.py` already uses `calculate_base_bid()` correctly
- NOT removing `keyword_bid` or `default_bid` from the response -- those remain for reference
- NOT changing the DB schema -- calculated values are computed at response time from session config

## Context & Research

### Relevant Code and Patterns

- `bulk_sheet_exporter.py:129` -- `calculate_base_bid()` function: `base_bid = max_bid / strategy_divisor / (1 + highest_placement_pct / 100)`
- `campaign_models.py:274` -- `CampaignResponse` model with `default_bid`, `keyword_bid` fields
- `campaign_models.py:30` -- `MatchTypeConfig` with `placement_multipliers_enabled`, `placement_multipliers`, `bidding_strategy`
- `campaign_router.py:163` -- `get_campaign_session` returns session with config + campaigns
- `campaign_router.py:579` -- `generate_campaigns` has config in request body
- `campaign_router.py:850` -- `update_campaign` endpoint
- Session config JSON contains placement multiplier settings per match type in `match_type_configs`

### Key Data Flow

1. User configures `keyword_bid` (Max Bid) per match type along with bidding strategy and placement multipliers
2. Config is stored in session's `config` JSON column
3. Campaigns are generated with raw `keyword_bid` stored in DB
4. At export time, `calculate_base_bid()` computes the actual bid from `keyword_bid` + strategy + placements
5. **Gap**: Preview response returns raw `keyword_bid` without the same calculation

## Key Technical Decisions

- **Import `calculate_base_bid` from `bulk_sheet_exporter` into `campaign_router`**: Reuse the existing function rather than duplicating logic. This keeps bid calculation as a single source of truth.
- **Add field to response model, not replace**: Add `calculated_base_bid` alongside existing `keyword_bid` so the frontend can choose which to display without breaking existing consumers.
- **Extract placement config from session config at response time**: The session config JSON stores placement settings per match type. When building `CampaignResponse`, look up the campaign's match type in the config to get placement multiplier values.

## Open Questions

### Resolved During Planning

- **Where do placement multiplier settings live at preview time?** In the session's `config` JSON under `match_type_configs.<match_type>.placement_multipliers_enabled` and `placement_multipliers`. Available via `row.get("config", {})` in all relevant endpoints.
- **Should we store calculated_base_bid in DB?** No -- it's a derived value from config settings that can change. Compute it at response time.

### Deferred to Implementation

- **Auto campaigns match type lookup**: Auto campaigns may not have a standard match type key in `match_type_configs`. Need to determine fallback behavior (likely use the first enabled match type config or return `keyword_bid` unchanged).

## Implementation Units

- [ ] **Unit 1: Add `calculated_base_bid` field to `CampaignResponse` and helper function**

  **Goal:** Add the response field and a helper that extracts placement config from session config JSON to compute calculated base bid per campaign.

  **Requirements:** R1, R3

  **Dependencies:** None

  **Files:**
  - Modify: `campaign_models.py` -- add `calculated_base_bid: Optional[float] = None` to `CampaignResponse`
  - Modify: `campaign_router.py` -- add helper function that takes a campaign dict/row + session config and returns the calculated base bid by looking up the campaign's match type in `match_type_configs`, extracting placement settings, and calling `calculate_base_bid()` from `bulk_sheet_exporter`

  **Approach:**
  - Import `calculate_base_bid` from `bulk_sheet_exporter` into `campaign_router`
  - Create a helper like `_compute_calculated_bid(campaign, config)` that:
    1. Gets the campaign's `match_type` and `bidding_strategy`
    2. Falls back to `default_bid` when `keyword_bid` is None (matching export pattern at `campaign_router.py:1370`)
    3. Looks up `match_type_configs[match_type]` from session config
    4. Extracts `placement_multipliers_enabled` and multiplier percentages
    5. Converts `keyword_bid` (float) to `Decimal` via `Decimal(str(keyword_bid))` before calling `calculate_base_bid()` (which requires `Decimal` input)
    6. Calls `calculate_base_bid()` with those values and converts result back to `float`
    7. Returns the result, or falls back to `keyword_bid` (or `default_bid`) if config lookup fails

  **Patterns to follow:**
  - `bulk_sheet_exporter.py:189-196` -- how `calculate_base_bid` is called with campaign data and placement config

  **Test scenarios:**
  - Happy path: Campaign with "Dynamic Up & Down" strategy and placement multipliers enabled (top=50%) -> calculated_base_bid = keyword_bid / 2 / 1.5
  - Happy path: Campaign with "Fixed" strategy and no placement multipliers -> calculated_base_bid = keyword_bid
  - Edge case: Config missing `match_type_configs` or match type not found -> falls back to keyword_bid
  - Edge case: `keyword_bid` is None -> falls back to `default_bid` for calculation
  - Edge case: Auto campaign with `is_auto=True` -> uses appropriate config lookup or fallback

  **Verification:**
  - `CampaignResponse` schema includes `calculated_base_bid` field
  - Helper function correctly delegates to `calculate_base_bid` from `bulk_sheet_exporter`

- [ ] **Unit 2: Populate `calculated_base_bid` in all campaign response endpoints**

  **Goal:** Wire up the helper in every place that builds a `CampaignResponse`.

  **Requirements:** R2

  **Dependencies:** Unit 1

  **Files:**
  - Modify: `campaign_router.py` -- update all `CampaignResponse(...)` construction sites

  **Approach:**
  - **`get_campaign_session` (~line 199)**: Session config available from `row.get("config", {})`. Pass to helper for each campaign.
  - **`generate_campaigns` (~line 746)**: Config available from `request.config`. Extract match type configs and pass to helper.
  - **`list_campaigns_for_session` (~line 817)**: Modify session ownership query at ~line 800 from `.select("id")` to `.select("id, config")` and extract config with `session.data[0].get("config", {})`.
  - **`update_campaign` (~line 915)**: Modify session ownership query at ~line 870 from `.select("id")` to `.select("id, config")` and extract config with `session.data[0].get("config", {})`.

  **Patterns to follow:**
  - Existing pattern of building `CampaignResponse` at lines 199, 746, 817, 915

  **Test scenarios:**
  - Happy path: GET session returns campaigns with calculated_base_bid populated
  - Happy path: Generate campaigns returns calculated_base_bid reflecting the submitted config's placement/strategy settings
  - Happy path: Update campaign returns updated calculated_base_bid
  - Edge case: Session with empty config returns keyword_bid as calculated_base_bid
  - Integration: calculated_base_bid matches what bulk_sheet_exporter would compute for the same campaign + config

  **Verification:**
  - All 4 endpoints return `calculated_base_bid` in campaign objects
  - Values match what `calculate_base_bid()` produces for the same inputs

## System-Wide Impact

- **API surface parity:** The `CampaignResponse` model gains a new optional field. This is backward-compatible -- existing consumers ignore unknown fields.
- **Interaction graph:** The `calculate_base_bid` function from `bulk_sheet_exporter` is now called from `campaign_router` as well. Changes to that function will affect both preview and export.
- **Error propagation:** If config lookup fails, the helper falls back to raw `keyword_bid` -- no errors propagated to the response.
- **Unchanged invariants:** The export XLSX output is NOT changed. The existing `keyword_bid` and `default_bid` fields remain in the response.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Config JSON structure varies between sessions | Helper uses safe `.get()` with fallback to raw keyword_bid |
| Auto campaigns have non-standard match type keys | Helper handles missing config gracefully |

## Sources & References

- Recent fix commit `11ff933`: "fix: use calculated base_bid for auto campaign targeting rows" -- confirms the pattern of using calculated base bid
- `bulk_sheet_exporter.py:129-149`: authoritative `calculate_base_bid` implementation
