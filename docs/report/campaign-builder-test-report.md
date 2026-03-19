# Campaign Builder API Test Report

**Date:** 2026-03-19
**API URL:** `https://keyword-analysis-api-production.up.railway.app`
**Tester:** Claude Code
**Status:** ALL TESTS PASSED (9/9)

---

## Test Data

| Item | Value |
|------|-------|
| Keyword Session ID | `6e4ac732-43e8-4c38-96c5-a42c66794cd7` |
| Campaign Session ID | `a8959bdf-6283-4e51-9a58-34afcdcdb97b` |
| User ID | `00000000-0000-0000-0000-000000000001` |
| Total Keywords | 499 (water bottles niche) |

**Sample Keywords:**

| Keyword | Search Volume |
|---------|---------------|
| water bottle for men | 37,197 |
| leak proof insulated water bottle | 965 |
| good water bottles | 691 |
| man water bottle | 471 |
| leakproof insulated water bottle | 250 |

---

## Test Results Summary

| # | Test Case | Endpoint | Status |
|---|-----------|----------|--------|
| 1 | Create Campaign Session | `POST /campaign-sessions` | PASS |
| 2 | Generate Normalization | `POST /campaign-sessions/{id}/normalize` | PASS |
| 3 | Get Root Keywords | `GET /campaign-sessions/{id}/roots` | PASS |
| 4 | Generate Campaigns (BUG FIX) | `POST /campaign-sessions/{id}/campaigns` | PASS |
| 5 | Add Negative Keyword | `POST /campaign-sessions/{id}/negatives` | PASS |
| 6 | List Negatives | `GET /campaign-sessions/{id}/negatives` | PASS |
| 7 | Delete Negative | `DELETE /campaign-sessions/{id}/negatives/{nid}` | PASS |
| 8 | Export Summary | `POST /campaign-sessions/{id}/export` | PASS |
| 9 | Get Campaign Session | `GET /campaign-sessions/{id}` | PASS |

---

## Bug Fix Verification

**Bug:** Campaign generation returned 0 campaigns when `selected_roots` was empty and `include_ungrouped=true`

**Fix Location:** `campaign_generator.py:150-167`

**Test Input:**
```json
{
  "config": {
    "sku": "TEST-SKU-001",
    "match_type_configs": {
      "exact": {
        "enabled": true,
        "daily_budget": "25.00",
        "default_bid": "0.75",
        "max_kw_per_campaign": 10,
        "start_date": "2026-03-19"
      }
    }
  },
  "selected_roots": {"exact": []},
  "solo_keyword_ids": [],
  "include_ungrouped": true
}
```

**Before Fix:** 0 campaigns
**After Fix:** 146 campaigns

---

## Export Summary

```json
{
  "total_campaigns": 146,
  "total_keywords": 499,
  "total_negatives": 0,
  "total_rows": 791,
  "match_type_breakdown": {
    "exact": 146
  }
}
```

---

## Sample Generated Campaigns

| Campaign Name | Match Type | Root Group | Keywords | Budget |
|---------------|------------|------------|----------|--------|
| TEST-SKU-001_SP_EX_water_bottle_for | exact | water bottle for | 10 | $25.00 |
| TEST-SKU-001_SP_EX_water_bottle_for 2 | exact | water bottle for | 5 | $25.00 |
| TEST-SKU-001_SP_EX_insulated_water_bottle | exact | insulated water bottle | 10 | $25.00 |
| TEST-SKU-001_SP_EX_insulated_water_bottle 2 | exact | insulated water bottle | 10 | $25.00 |
| ... (146 total) | ... | ... | ... | ... |

---

## Conclusion

- 9/9 tests passed
- Bug fix verified - Campaigns now generate correctly when no roots selected
- Backend deployed to production
- Frontend and backend merged to main
