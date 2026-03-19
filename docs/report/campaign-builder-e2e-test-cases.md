# Campaign Builder - E2E Manual Test Cases

**Application:** Brand Tools
**Feature:** Campaign Builder (Keyword Analysis → Campaign Creation)
**URL:** https://brandtools.incrementumdigital.com
**Date:** 2026-03-19

---

## Prerequisites

1. Logged into Brand Tools with valid account
2. Have an ASIN ready for testing (e.g., `B0CJTL53NK` - water bottle)
3. Browser DevTools open (F12) to monitor network requests (optional)

---

## Test Case 1: Create Keyword Analysis Session

**Objective:** Create a new keyword analysis session with product data

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to **Keyword Analysis** from sidebar | Keyword Analysis page loads |
| 2 | Click **"New Analysis"** or **"+"** button | "Product Information" modal appears |
| 3 | Enter ASIN: `B0CJTL53NK` | ASIN field populated |
| 4 | Select Country: `United States` | Country dropdown shows US |
| 5 | Click **"Continue"** or **"Create"** | Session created, redirected to session detail page |
| 6 | Wait for keyword analysis to complete | Keywords table populated with results |

### Test Data

```
ASIN: B0CJTL53NK
Country: US (United States)
```

### Verification

- [ ] Session appears in session list
- [ ] Keywords are loaded (check count > 0)
- [ ] Search volume data is displayed
- [ ] No error messages shown

---

## Test Case 2: Navigate to Campaign Builder

**Objective:** Access the Campaign Builder from a completed keyword session

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | From Keyword Analysis session, locate **"Campaign Builder"** tab or button | Tab/button is visible |
| 2 | Click **"Campaign Builder"** | Campaign Builder wizard opens |
| 3 | Verify Step 1 is active | Step indicator shows Step 1 highlighted |

### Verification

- [ ] Campaign Builder UI loads without errors
- [ ] Step indicator shows 4 steps (Config → Normalization → Targeting → Export)
- [ ] Keywords from session are accessible

---

## Test Case 3: Configure Campaign Settings (Step 1)

**Objective:** Set up campaign configuration including SKU, naming, and match types

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Enter SKU: `WATERBOTTLE-001` | SKU field populated |
| 2 | Verify naming template shows: `SKU_SP_MATCH_ROOT` | Template preview displays |
| 3 | Enable **Exact Match** toggle | Exact match section expands |
| 4 | Set Daily Budget: `$25.00` | Budget field shows $25.00 |
| 5 | Set Default Bid: `$0.75` | Bid field shows $0.75 |
| 6 | Set Max Keywords per Campaign: `10` | Field shows 10 |
| 7 | (Optional) Enable **Phrase Match** | Phrase match section expands |
| 8 | Click **"Next"** or **"Continue"** | Proceeds to Step 2 |

### Test Data

```
SKU: WATERBOTTLE-001
Daily Budget: $25.00
Default Bid: $0.75
Keyword Bid: $0.75
Max Keywords per Campaign: 10
Start Date: Today
Bidding Strategy: Fixed
Match Types: Exact (enabled), Phrase (optional)
```

### Verification

- [ ] All form fields accept input
- [ ] Validation errors show for invalid data
- [ ] Campaign name preview updates as you type
- [ ] Can proceed to next step

---

## Test Case 4: Review Normalization Suggestions (Step 2)

**Objective:** Review and accept/reject keyword normalization suggestions

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Wait for normalization to load | Normalization groups appear |
| 2 | Review first group (e.g., "water bottle") | Shows variants: "water bottle", "water bottles", "a water bottle" |
| 3 | Verify reason labels | Shows "Plural → Singular", "Filler: a", etc. |
| 4 | Toggle **Include** checkbox for a group | Group toggles on/off |
| 5 | (Optional) Expand a group to see variants | Variant details visible |
| 6 | Click **"Next"** or **"Continue"** | Proceeds to Step 3 |

### Expected Normalization Groups

| Normalized Keyword | Variants | Reason |
|--------------------|----------|--------|
| water bottle | water bottle, water bottles, a water bottle | Plural→Singular, Filler removal |
| insulated water bottle | insulated water bottle, insulated water bottles | Plural→Singular |
| stainless steel water bottle | stainless steel water bottle, stainless steel water bottles | Plural→Singular |

### Verification

- [ ] Normalization groups load (count > 0)
- [ ] Combined search volume shows for each group
- [ ] Toggle works to include/exclude groups
- [ ] Can proceed to next step

---

## Test Case 5: Configure Targeting & Roots (Step 3)

**Objective:** Select root keywords and configure campaign grouping

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | View root keywords table | Roots displayed with frequency and SV |
| 2 | Select root: `water bottle` | Checkbox selected |
| 3 | Select root: `insulated` | Checkbox selected |
| 4 | (Optional) Mark keyword as **Solo** | Solo toggle enabled for high-value keyword |
| 5 | Verify **"Include Ungrouped"** checkbox | Checkbox is checked by default |
| 6 | Click **"Generate Campaigns"** | Campaigns are generated |
| 7 | Review generated campaigns list | Campaign table shows generated campaigns |

### Test Scenarios

#### Scenario A: With Selected Roots
```
Selected Roots: ["water bottle", "insulated"]
Solo Keywords: []
Include Ungrouped: false
Expected: Campaigns only for selected roots
```

#### Scenario B: No Roots Selected + Include Ungrouped (BUG FIX TEST)
```
Selected Roots: [] (none)
Solo Keywords: []
Include Ungrouped: true (checked)
Expected: ALL keywords grouped into campaigns (146 campaigns)
```

#### Scenario C: With Solo Keywords
```
Selected Roots: ["water bottle"]
Solo Keywords: ["water bottle for men"] (highest SV keyword)
Include Ungrouped: true
Expected: 1 solo campaign + grouped campaigns
```

### Verification

- [ ] Root keywords table loads with frequency data
- [ ] Can select/deselect roots
- [ ] **BUG FIX:** Campaigns generate when NO roots selected but Include Ungrouped is ON
- [ ] Campaign count shows in preview
- [ ] Generated campaigns appear in table

---

## Test Case 6: Review Generated Campaigns

**Objective:** Verify campaigns are correctly generated

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | View campaigns table | Campaigns listed with details |
| 2 | Verify campaign naming | Names follow pattern: `SKU_SP_MATCH_ROOT` |
| 3 | Check keyword count per campaign | Max 10 keywords per campaign |
| 4 | Expand a campaign to see keywords | Keywords listed with search volume |
| 5 | (Optional) Edit campaign name | Name updates |
| 6 | (Optional) Delete a campaign | Campaign removed from list |

### Expected Campaign Structure

| Campaign Name | Match Type | Root Group | Keywords | Budget |
|---------------|------------|------------|----------|--------|
| WATERBOTTLE-001_SP_EX_water_bottle | Exact | water bottle | 10 | $25.00 |
| WATERBOTTLE-001_SP_EX_water_bottle 2 | Exact | water bottle | 10 | $25.00 |
| WATERBOTTLE-001_SP_EX_insulated | Exact | insulated | 10 | $25.00 |

### Verification

- [ ] Campaigns follow naming template
- [ ] Keywords are correctly grouped by root
- [ ] Max keywords per campaign is respected
- [ ] Budget and bid values are correct
- [ ] Solo campaigns marked as "Solo"

---

## Test Case 7: Add Negative Keywords

**Objective:** Add negative keywords to exclude from campaigns

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Locate **"Negative Keywords"** section | Section visible |
| 2 | Click **"Add Negative"** | Input form appears |
| 3 | Enter keyword: `cheap` | Keyword field populated |
| 4 | Select match type: `Negative Phrase` | Dropdown selected |
| 5 | Click **"Add"** | Negative added to list |
| 6 | Verify negative appears in list | Shows "cheap" - Negative Phrase |
| 7 | Add another: `free` as Negative Exact | Second negative added |
| 8 | Delete a negative keyword | Negative removed |

### Test Data

| Negative Keyword | Match Type |
|------------------|------------|
| cheap | Negative Phrase |
| free | Negative Exact |
| used | Negative Phrase |
| broken | Negative Exact |

### Verification

- [ ] Can add negative keywords
- [ ] Match type dropdown works (Negative Exact, Negative Phrase)
- [ ] Negatives appear in list
- [ ] Can delete negatives
- [ ] Negatives included in export

---

## Test Case 8: Export & Download (Step 4)

**Objective:** Export campaigns to Amazon SP bulk sheet format

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to **Export** step | Export summary visible |
| 2 | Review export summary | Shows total campaigns, keywords, negatives |
| 3 | Verify match type breakdown | Shows count per match type |
| 4 | (Optional) Select specific campaigns | Checkboxes for campaign selection |
| 5 | Click **"Download Bulk Sheet"** | XLSX file downloads |
| 6 | Open downloaded file in Excel | File opens correctly |
| 7 | Verify bulk sheet format | Amazon SP format with all columns |

### Expected Export Summary

```
Total Campaigns: 146
Total Keywords: 499
Total Negatives: 2
Total Rows: 793
Match Type Breakdown:
  - Exact: 146
```

### Bulk Sheet Columns to Verify

| Column | Expected Value |
|--------|----------------|
| Record Type | Campaign / Keyword / Negative |
| Campaign Name | WATERBOTTLE-001_SP_EX_... |
| Campaign Daily Budget | 25.00 |
| Campaign Start Date | 2026-03-19 |
| Campaign Targeting Type | Manual |
| Keyword | water bottle for men |
| Match Type | Exact |
| Keyword Bid | 0.75 |

### Verification

- [ ] Export summary shows correct counts
- [ ] XLSX file downloads successfully
- [ ] File opens in Excel without errors
- [ ] All campaigns included in export
- [ ] Negative keywords included (if enabled)
- [ ] Format matches Amazon SP bulk upload requirements

---

## Test Case 9: Session Persistence

**Objective:** Verify session data persists across page refresh

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Complete steps 1-3 (config, normalization, campaigns) | Data entered |
| 2 | Refresh the page (F5) | Page reloads |
| 3 | Verify configuration persists | SKU, budgets, settings retained |
| 4 | Verify campaigns still exist | Generated campaigns still listed |
| 5 | Navigate away and return | Data still intact |

### Verification

- [ ] Configuration survives refresh
- [ ] Generated campaigns persist
- [ ] Negative keywords persist
- [ ] Step progress maintained

---

## Test Case 10: Error Handling

**Objective:** Verify proper error handling for edge cases

### Steps

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Try to generate campaigns without enabling any match type | Error message shown |
| 2 | Enter invalid SKU (special characters) | Validation error |
| 3 | Set budget to $0 | Validation error |
| 4 | Set max keywords to 0 | Validation error |
| 5 | Try to export with no campaigns | Error or disabled button |

### Verification

- [ ] Validation errors are user-friendly
- [ ] Cannot proceed with invalid data
- [ ] Error messages are clear and actionable

---

## Bug Fix Verification Test

**Critical Test:** Verify the campaign generation bug fix

### Scenario: No Roots Selected + Include Ungrouped = TRUE

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to Step 3 (Targeting) | Root keywords table visible |
| 2 | **DO NOT select any roots** | All root checkboxes unchecked |
| 3 | Ensure **"Include Ungrouped"** is CHECKED | Checkbox is ON |
| 4 | Click **"Generate Campaigns"** | Campaigns should generate |
| 5 | Verify campaign count | Should be > 0 (e.g., 146 campaigns) |

### Before Bug Fix
- Result: 0 campaigns generated
- Status: FAIL

### After Bug Fix
- Result: 146 campaigns generated
- Status: PASS

---

## Test Summary Checklist

| Test Case | Description | Status |
|-----------|-------------|--------|
| TC1 | Create Keyword Analysis Session | [ ] |
| TC2 | Navigate to Campaign Builder | [ ] |
| TC3 | Configure Campaign Settings | [ ] |
| TC4 | Review Normalization | [ ] |
| TC5 | Configure Targeting & Roots | [ ] |
| TC6 | Review Generated Campaigns | [ ] |
| TC7 | Add Negative Keywords | [ ] |
| TC8 | Export & Download | [ ] |
| TC9 | Session Persistence | [ ] |
| TC10 | Error Handling | [ ] |
| BUG FIX | No Roots + Include Ungrouped | [ ] |

---

## Notes

- Test with different ASINs to verify consistency
- Test with large keyword sets (500+) for performance
- Verify bulk sheet uploads correctly to Amazon Seller Central
- Report any UI/UX issues found during testing
