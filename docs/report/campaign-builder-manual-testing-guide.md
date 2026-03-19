# Campaign Builder API - Manual Testing Guide

**API Base URL:** `https://keyword-analysis-api-production.up.railway.app`

---

## Environment Variables

Set these before running the tests:

```bash
export API_URL="https://keyword-analysis-api-production.up.railway.app"
export USER_ID="00000000-0000-0000-0000-000000000001"
export KEYWORD_SESSION_ID="6e4ac732-43e8-4c38-96c5-a42c66794cd7"
```

---

## Test 1: Create Campaign Session

**Endpoint:** `POST /campaign-sessions`

**Description:** Creates a new campaign builder session linked to an existing keyword analysis session.

### Request

```bash
curl -X POST "${API_URL}/campaign-sessions" \
  -H "Content-Type: application/json" \
  -d '{
    "keyword_session_id": "6e4ac732-43e8-4c38-96c5-a42c66794cd7",
    "user_id": "00000000-0000-0000-0000-000000000001",
    "name": "My Test Campaign Session"
  }'
```

### Example Request Body

```json
{
  "keyword_session_id": "6e4ac732-43e8-4c38-96c5-a42c66794cd7",
  "user_id": "00000000-0000-0000-0000-000000000001",
  "name": "My Test Campaign Session"
}
```

### Expected Response (201 Created)

```json
{
  "id": "a8959bdf-6283-4e51-9a58-34afcdcdb97b",
  "keyword_session_id": "6e4ac732-43e8-4c38-96c5-a42c66794cd7",
  "user_id": "00000000-0000-0000-0000-000000000001",
  "name": "My Test Campaign Session",
  "status": "draft",
  "current_step": 1,
  "config": {
    "sku": "",
    "naming_template": {
      "tokens": ["SKU", "SP", "MATCH", "ROOT"],
      "separator": "_",
      "custom_tokens": {}
    },
    "match_type_configs": {}
  },
  "existing_targeting": null,
  "created_at": "2026-03-19T14:54:14.729323+00:00",
  "updated_at": "2026-03-19T14:54:14.729323+00:00"
}
```

### Save for Next Tests

```bash
export CAMPAIGN_SESSION_ID="<id from response>"
```

---

## Test 2: Generate Normalization Suggestions

**Endpoint:** `POST /campaign-sessions/{session_id}/normalize`

**Description:** Analyzes keywords and suggests normalization (plural→singular, filler word removal).

### Request

```bash
curl -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/normalize?user_id=${USER_ID}" \
  -H "Content-Type: application/json"
```

### Expected Response (200 OK)

```json
{
  "groups": [
    {
      "id": "norm_84",
      "normalized_text": "water bottle",
      "combined_search_volume": 1985740,
      "variants": [
        {
          "keyword": "water bottle",
          "keyword_id": "ecf09e13-d78c-4c7e-8b32-3fd94b84f8da",
          "search_volume": 1984921,
          "reason": "Original - Kept",
          "is_merged": false
        },
        {
          "keyword": "a water bottle",
          "keyword_id": "4002a5da-c2d7-48b7-bf17-7024a8195cad",
          "search_volume": 819,
          "reason": "Filler: a",
          "is_merged": true
        }
      ],
      "is_included": true
    },
    {
      "id": "norm_38",
      "normalized_text": "insulated water bottle",
      "combined_search_volume": 194489,
      "variants": [
        {
          "keyword": "insulated water bottle",
          "keyword_id": "d3c0fc58-c682-4568-8ab4-53117db80f37",
          "search_volume": 181561,
          "reason": "Original - Kept",
          "is_merged": false
        },
        {
          "keyword": "insulated water bottles",
          "keyword_id": "b9ce41ac-0e0b-4c8d-9f18-24bf97f1ba1f",
          "search_volume": 12928,
          "reason": "Plural → Singular",
          "is_merged": true
        }
      ],
      "is_included": true
    }
  ]
}
```

---

## Test 3: Get Root Keyword Groups

**Endpoint:** `GET /campaign-sessions/{session_id}/roots`

**Description:** Returns detected root keywords with frequency and search volume data.

### Request

```bash
curl "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/roots?user_id=${USER_ID}" \
  -H "Content-Type: application/json"
```

### Expected Response (200 OK)

```json
{
  "roots": [
    {
      "name": "water",
      "frequency": 402,
      "total_sv": 3496861,
      "keyword_count": 402
    },
    {
      "name": "bottle",
      "frequency": 321,
      "total_sv": 3276891,
      "keyword_count": 321
    },
    {
      "name": "water bottle",
      "frequency": 285,
      "total_sv": 3225500,
      "keyword_count": 285
    },
    {
      "name": "insulated",
      "frequency": 98,
      "total_sv": 468992,
      "keyword_count": 98
    }
  ]
}
```

---

## Test 4: Generate Campaigns (BUG FIX TEST)

**Endpoint:** `POST /campaign-sessions/{session_id}/campaigns`

**Description:** Generates Amazon PPC campaigns from keywords. This is the critical test for the bug fix.

### Test Case 4A: No Roots Selected + Include Ungrouped (BUG FIX)

**Scenario:** User wants all keywords grouped into campaigns without selecting specific roots.

### Request

```bash
curl -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/campaigns?user_id=${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "sku": "WATERBOTTLE-001",
      "naming_template": {
        "tokens": ["SKU", "SP", "MATCH", "ROOT"],
        "separator": "_"
      },
      "match_type_configs": {
        "exact": {
          "enabled": true,
          "daily_budget": "25.00",
          "default_bid": "0.75",
          "keyword_bid": "0.75",
          "bidding_strategy": "Fixed",
          "max_kw_per_campaign": 10,
          "start_date": "2026-03-19",
          "status": "Enabled"
        }
      }
    },
    "selected_roots": {
      "exact": []
    },
    "solo_keyword_ids": [],
    "include_ungrouped": true
  }'
```

### Example Request Body

```json
{
  "config": {
    "sku": "WATERBOTTLE-001",
    "naming_template": {
      "tokens": ["SKU", "SP", "MATCH", "ROOT"],
      "separator": "_"
    },
    "match_type_configs": {
      "exact": {
        "enabled": true,
        "daily_budget": "25.00",
        "default_bid": "0.75",
        "keyword_bid": "0.75",
        "bidding_strategy": "Fixed",
        "max_kw_per_campaign": 10,
        "start_date": "2026-03-19",
        "status": "Enabled"
      }
    }
  },
  "selected_roots": {
    "exact": []
  },
  "solo_keyword_ids": [],
  "include_ungrouped": true
}
```

### Expected Response (200 OK) - SHOULD RETURN CAMPAIGNS

```json
{
  "session_id": "a8959bdf-6283-4e51-9a58-34afcdcdb97b",
  "campaigns": [
    {
      "id": "b6c91717-65a3-4e9f-ba60-cf49e7c7ae2c",
      "name": "WATERBOTTLE-001_SP_EX_water_bottle_for",
      "match_type": "exact",
      "root_group": "water bottle for",
      "keyword_count": 10,
      "daily_budget": "25.0",
      "default_bid": "0.75",
      "keyword_bid": "0.75",
      "bidding_strategy": "Fixed",
      "start_date": "2026-03-19",
      "status": "Enabled",
      "is_solo": false,
      "is_auto": false,
      "sv_tier": "All"
    },
    {
      "id": "54b22469-9b1d-46ad-b04f-32b6cf81027f",
      "name": "WATERBOTTLE-001_SP_EX_water_bottle_for 2",
      "match_type": "exact",
      "root_group": "water bottle for",
      "keyword_count": 5,
      "daily_budget": "25.0",
      "default_bid": "0.75"
    }
  ]
}
```

**IMPORTANT:** Before the bug fix, this returned 0 campaigns. After the fix, it returns 146 campaigns.

---

### Test Case 4B: With Specific Roots Selected

**Scenario:** User selects specific root keywords to target.

### Request

```bash
curl -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/campaigns?user_id=${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "sku": "WATERBOTTLE-001",
      "naming_template": {
        "tokens": ["SKU", "SP", "MATCH", "ROOT"],
        "separator": "_"
      },
      "match_type_configs": {
        "exact": {
          "enabled": true,
          "daily_budget": "25.00",
          "default_bid": "0.75",
          "keyword_bid": "0.75",
          "bidding_strategy": "Fixed",
          "max_kw_per_campaign": 10,
          "start_date": "2026-03-19",
          "status": "Enabled"
        },
        "phrase": {
          "enabled": true,
          "daily_budget": "20.00",
          "default_bid": "0.60",
          "keyword_bid": "0.60",
          "bidding_strategy": "Fixed",
          "max_kw_per_campaign": 15,
          "start_date": "2026-03-19",
          "status": "Enabled"
        }
      }
    },
    "selected_roots": {
      "exact": ["water bottle", "insulated"],
      "phrase": ["water bottle"]
    },
    "solo_keyword_ids": [],
    "include_ungrouped": false
  }'
```

---

### Test Case 4C: With Solo Keywords

**Scenario:** Create individual campaigns for high-value keywords.

### Request

```bash
curl -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/campaigns?user_id=${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "sku": "WATERBOTTLE-001",
      "naming_template": {
        "tokens": ["SKU", "SP", "MATCH", "ROOT"],
        "separator": "_"
      },
      "match_type_configs": {
        "exact": {
          "enabled": true,
          "daily_budget": "50.00",
          "default_bid": "1.25",
          "keyword_bid": "1.25",
          "bidding_strategy": "Fixed",
          "max_kw_per_campaign": 10,
          "start_date": "2026-03-19",
          "status": "Enabled"
        }
      }
    },
    "selected_roots": {
      "exact": []
    },
    "solo_keyword_ids": [
      "ecf09e13-d78c-4c7e-8b32-3fd94b84f8da",
      "d3c0fc58-c682-4568-8ab4-53117db80f37"
    ],
    "include_ungrouped": true
  }'
```

---

## Test 5: Add Negative Keyword

**Endpoint:** `POST /campaign-sessions/{session_id}/negatives`

**Description:** Adds a negative keyword to exclude from campaigns.

### Request

```bash
curl -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/negatives?user_id=${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "keyword_text": "cheap water bottle",
    "match_type": "negative_phrase"
  }'
```

### Example Request Body

```json
{
  "keyword_text": "cheap water bottle",
  "match_type": "negative_phrase"
}
```

### Valid Match Types

- `negative_exact`
- `negative_phrase`

### Expected Response (201 Created)

```json
{
  "id": "605fc108-2fc3-431a-9e15-5b5d602b99fe",
  "keyword_text": "cheap water bottle",
  "match_type": "negative_phrase"
}
```

### Save for Delete Test

```bash
export NEGATIVE_ID="<id from response>"
```

---

## Test 6: List Negative Keywords

**Endpoint:** `GET /campaign-sessions/{session_id}/negatives`

**Description:** Lists all negative keywords for the session.

### Request

```bash
curl "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/negatives?user_id=${USER_ID}" \
  -H "Content-Type: application/json"
```

### Expected Response (200 OK)

```json
[
  {
    "id": "605fc108-2fc3-431a-9e15-5b5d602b99fe",
    "keyword_text": "cheap water bottle",
    "match_type": "negative_phrase"
  },
  {
    "id": "abc123...",
    "keyword_text": "free water bottle",
    "match_type": "negative_exact"
  }
]
```

---

## Test 7: Delete Negative Keyword

**Endpoint:** `DELETE /campaign-sessions/{session_id}/negatives/{negative_id}`

**Description:** Deletes a negative keyword.

### Request

```bash
curl -X DELETE "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/negatives/${NEGATIVE_ID}?user_id=${USER_ID}" \
  -H "Content-Type: application/json"
```

### Expected Response (200 OK)

```json
{
  "success": true,
  "message": "Negative keyword deleted"
}
```

---

## Test 8: Export Summary

**Endpoint:** `POST /campaign-sessions/{session_id}/export`

**Description:** Generates export summary without downloading the file.

### Request

```bash
curl -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/export?user_id=${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_ids": null,
    "options": {
      "include_negatives": true
    }
  }'
```

### Example Request Body

```json
{
  "campaign_ids": null,
  "options": {
    "include_negatives": true
  }
}
```

### Export Specific Campaigns Only

```json
{
  "campaign_ids": [
    "b6c91717-65a3-4e9f-ba60-cf49e7c7ae2c",
    "54b22469-9b1d-46ad-b04f-32b6cf81027f"
  ],
  "options": {
    "include_negatives": true
  }
}
```

### Expected Response (200 OK)

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

## Test 9: Download Bulk Sheet

**Endpoint:** `GET /campaign-sessions/{session_id}/export/download`

**Description:** Downloads the Amazon SP bulk sheet as XLSX file.

### Request

```bash
curl "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/export/download?user_id=${USER_ID}&format=xlsx" \
  -H "Content-Type: application/json" \
  -o bulk_sheet.xlsx
```

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| user_id | string | required | User ID |
| format | string | xlsx | Export format (xlsx) |

### Expected Response

Binary XLSX file download.

---

## Test 10: Get Campaign Session (Full)

**Endpoint:** `GET /campaign-sessions/{session_id}`

**Description:** Gets the full campaign session with all campaigns.

### Request

```bash
curl "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}?user_id=${USER_ID}" \
  -H "Content-Type: application/json"
```

### Expected Response (200 OK)

```json
{
  "id": "a8959bdf-6283-4e51-9a58-34afcdcdb97b",
  "keyword_session_id": "6e4ac732-43e8-4c38-96c5-a42c66794cd7",
  "user_id": "00000000-0000-0000-0000-000000000001",
  "name": "My Test Campaign Session",
  "status": "draft",
  "current_step": 1,
  "config": {...},
  "existing_targeting": null,
  "campaigns": [
    {
      "id": "b6c91717-65a3-4e9f-ba60-cf49e7c7ae2c",
      "name": "WATERBOTTLE-001_SP_EX_water_bottle_for",
      "match_type": "exact",
      "root_group": "water bottle for",
      "keyword_count": 10,
      "daily_budget": "25.0",
      "default_bid": "0.75",
      "keyword_bid": "0.75",
      "bidding_strategy": "Fixed",
      "start_date": "2026-03-19",
      "status": "Enabled",
      "is_solo": false,
      "is_auto": false,
      "sv_tier": "All"
    }
  ],
  "normalization_decisions": null,
  "created_at": "2026-03-19T14:54:14.729323+00:00",
  "updated_at": "2026-03-19T14:54:14.729323+00:00"
}
```

---

## Error Responses

### 404 Not Found

```json
{
  "detail": "Campaign session not found"
}
```

### 409 Conflict

```json
{
  "detail": "Campaign session already exists for this keyword session"
}
```

### 422 Validation Error

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "config"],
      "msg": "Field required",
      "input": {...}
    }
  ]
}
```

### 503 Service Unavailable

```json
{
  "detail": "Database service unavailable"
}
```

---

## Complete Test Script

Save this as `test-campaign-api.sh` and run it:

```bash
#!/bin/bash

API_URL="https://keyword-analysis-api-production.up.railway.app"
USER_ID="00000000-0000-0000-0000-000000000001"
KEYWORD_SESSION_ID="6e4ac732-43e8-4c38-96c5-a42c66794cd7"

echo "=== Test 1: Create Campaign Session ==="
RESPONSE=$(curl -s -X POST "${API_URL}/campaign-sessions" \
  -H "Content-Type: application/json" \
  -d '{
    "keyword_session_id": "'${KEYWORD_SESSION_ID}'",
    "user_id": "'${USER_ID}'",
    "name": "Manual Test Session"
  }')
echo "$RESPONSE" | python -m json.tool
CAMPAIGN_SESSION_ID=$(echo "$RESPONSE" | python -c "import sys, json; print(json.load(sys.stdin).get('id', ''))")
echo "Campaign Session ID: $CAMPAIGN_SESSION_ID"

echo ""
echo "=== Test 2: Generate Normalization ==="
curl -s -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/normalize?user_id=${USER_ID}" \
  -H "Content-Type: application/json" | python -m json.tool | head -50

echo ""
echo "=== Test 3: Get Roots ==="
curl -s "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/roots?user_id=${USER_ID}" \
  -H "Content-Type: application/json" | python -m json.tool | head -30

echo ""
echo "=== Test 4: Generate Campaigns (BUG FIX TEST) ==="
curl -s -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/campaigns?user_id=${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "sku": "TEST-001",
      "naming_template": {"tokens": ["SKU", "SP", "MATCH", "ROOT"], "separator": "_"},
      "match_type_configs": {
        "exact": {
          "enabled": true,
          "daily_budget": "25.00",
          "default_bid": "0.75",
          "keyword_bid": "0.75",
          "max_kw_per_campaign": 10,
          "start_date": "'$(date +%Y-%m-%d)'"
        }
      }
    },
    "selected_roots": {"exact": []},
    "solo_keyword_ids": [],
    "include_ungrouped": true
  }' | python -m json.tool | head -50

echo ""
echo "=== Test 5: Add Negative ==="
RESPONSE=$(curl -s -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/negatives?user_id=${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"keyword_text": "cheap", "match_type": "negative_phrase"}')
echo "$RESPONSE" | python -m json.tool
NEGATIVE_ID=$(echo "$RESPONSE" | python -c "import sys, json; print(json.load(sys.stdin).get('id', ''))")

echo ""
echo "=== Test 6: List Negatives ==="
curl -s "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/negatives?user_id=${USER_ID}" \
  -H "Content-Type: application/json" | python -m json.tool

echo ""
echo "=== Test 7: Delete Negative ==="
curl -s -X DELETE "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/negatives/${NEGATIVE_ID}?user_id=${USER_ID}" \
  -H "Content-Type: application/json" | python -m json.tool

echo ""
echo "=== Test 8: Export Summary ==="
curl -s -X POST "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}/export?user_id=${USER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"campaign_ids": null, "options": {"include_negatives": true}}' | python -m json.tool

echo ""
echo "=== Test 9: Get Campaign Session ==="
curl -s "${API_URL}/campaign-sessions/${CAMPAIGN_SESSION_ID}?user_id=${USER_ID}" \
  -H "Content-Type: application/json" | python -m json.tool | head -80

echo ""
echo "=== ALL TESTS COMPLETE ==="
```

Make it executable and run:

```bash
chmod +x test-campaign-api.sh
./test-campaign-api.sh
```
