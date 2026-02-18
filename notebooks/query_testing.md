# DB-Navigator AI - Baseline Query Testing (No Schema Enrichment)

**Date**: 2026-02-18
**LLM**: GPT-4o-mini
**Framework**: Vanna.ai with ChromaDB
**Database**: Synthetic bank schema (14 tables, no FK constraints)
**Training data**: DDL + 13 documentation entries + 5 SQL examples

## Summary

| Metric | Value |
|--------|-------|
| Total queries tested | 12 |
| Correct | 8 |
| Partially correct | 2 |
| Incorrect | 2 |
| Baseline accuracy | 66.7% |

## Failure Pattern Analysis

| Pattern | Occurrences | Affected queries |
|---------|-------------|-----------------|
| Value mapping (wrong status codes) | 2 | #4, #10 |
| Semantic reasoning (multi-row aggregation before comparison) | 1 | #11 |
| Data gap (correct SQL, missing reference data) | 1 | #5 |

## Detailed Results

### Easy (Single Table)

#### Test 1 - List all branches
- **Difficulty**: Easy
- **Generated SQL**: `SELECT * FROM bank.tbl_br`
- **Correct?**: Yes
- **Notes**: Straightforward table retrieval.

#### Test 2 - Show me all loan products
- **Difficulty**: Easy
- **Generated SQL**: `SELECT * FROM bank.tbl_loan_prod`
- **Correct?**: Yes
- **Notes**: Correct table identification from natural language.

#### Test 3 - How many employees work at each branch?
- **Difficulty**: Easy
- **Generated SQL**: `SELECT br_cd, COUNT(*) as employee_count FROM bank.tbl_emp GROUP BY br_cd ORDER BY employee_count DESC`
- **Correct?**: Yes
- **Notes**: Correct GROUP BY with alias ordering.

#### Test 4 - Show dormant accounts
- **Difficulty**: Easy
- **Generated SQL**: `SELECT * FROM bank.tbl_acct WHERE stat_cd = 'CLOSED' AND last_txn_dt < CURRENT_DATE - INTERVAL '12 months'`
- **Correct?**: No
- **Expected SQL**: `SELECT * FROM bank.tbl_acct WHERE stat_cd = 'DORMANT'`
- **Error type**: Value mapping
- **Notes**: LLM does not know 'DORMANT' is a valid stat_cd value. Inferred dormancy from business logic instead. Schema enrichment with sample values per column would resolve this.

### Medium (JOINs, GROUP BY)

#### Test 5 - Convert all EUR balances to MDL using today's rate
- **Difficulty**: Medium
- **Generated SQL**: `SELECT a.acct_no, a.cust_no, a.ccy_cd, a.cur_bal, (a.cur_bal * fx.buy_rate) AS mdl_balance FROM bank.tbl_acct a JOIN bank.tbl_fx_rate fx ON a.ccy_cd = fx.ccy_from WHERE fx.ccy_to = 'MDL' AND fx.rate_dt = CURRENT_DATE`
- **Correct?**: Partially - logic correct, no results due to missing FX data for today
- **Error type**: Data gap (not SQL generation error)
- **Notes**: Correct JOIN, conversion math, and WHERE filter. A production system would need fallback to latest available rate.

#### Test 6 - Show customer names with their account balances
- **Difficulty**: Medium
- **Generated SQL**: `SELECT c.cust_nm, a.avail_bal FROM bank.tbl_cust c JOIN bank.tbl_acct a ON c.cust_no = a.cust_no`
- **Correct?**: Yes
- **Notes**: Correct JOIN on cust_no. Returned 27 rows (customers with multiple accounts appear multiple times, which is valid).

#### Test 7 - Which customers have credit cards?
- **Difficulty**: Medium
- **Generated SQL**: `SELECT DISTINCT c.cust_nm, c.cust_no FROM bank.tbl_card cd JOIN bank.tbl_cust c ON cd.cust_no = c.cust_no WHERE cd.card_tp = 'CREDIT'`
- **Correct?**: Yes
- **Notes**: Correct DISTINCT to avoid duplicates. Correctly filtered card_tp = 'CREDIT'. Returned 2 rows.

#### Test 8 - What is the total outstanding loan amount per branch?
- **Difficulty**: Medium
- **Generated SQL**: `SELECT l.br_cd, SUM(l.outst_princ) as total_outstanding FROM bank.tbl_loan l WHERE l.stat_cd = 'ACTIVE' GROUP BY l.br_cd ORDER BY total_outstanding DESC`
- **Correct?**: Yes
- **Notes**: Correct aggregation with status filter and ordering.

#### Test 9 - Which guarantors are also bank customers?
- **Difficulty**: Medium
- **Generated SQL**: `SELECT g.guar_nm, g.guar_idnp FROM bank.tbl_guar g WHERE g.guar_cust_no IS NOT NULL`
- **Correct?**: Yes
- **Notes**: Correctly used nullable FK pattern. Could be improved by JOINing to tbl_cust to show customer details, but logic is sound.

### Hard (Nested, Window Functions, Multi-step)

#### Test 10 - Show the top 3 customers by total balance across all accounts
- **Difficulty**: Hard
- **Generated SQL**: `SELECT a.cust_no, c.cust_nm, SUM(a.cur_bal) as total_balance FROM bank.tbl_acct a JOIN bank.tbl_cust c ON a.cust_no = c.cust_no WHERE a.stat_cd = 'ACTIVE' GROUP BY a.cust_no, c.cust_nm ORDER BY total_balance DESC LIMIT 3`
- **Correct?**: No
- **Expected**: `WHERE a.stat_cd = 'OPEN'` (or no WHERE filter)
- **Error type**: Value mapping - same pattern as Test 4
- **Notes**: SQL logic is correct (JOIN, GROUP BY, ORDER, LIMIT) but stat_cd = 'ACTIVE' returns 0 rows. Account status uses 'OPEN', not 'ACTIVE'. Second occurrence of this exact failure pattern.

#### Test 11 - Which loans have collateral value less than the outstanding principal?
- **Difficulty**: Hard
- **Generated SQL**: `SELECT l.loan_no, l.loan_amt, l.outst_princ, c.appraisal_val FROM bank.tbl_loan l JOIN bank.tbl_coll c ON l.loan_no = c.loan_no WHERE c.appraisal_val < l.outst_princ`
- **Correct?**: Partially
- **Notes**: Compares individual collateral items against outstanding principal. Loans can have multiple collateral items (e.g., LN-2025-00011 has two pieces totaling 15.5M vs 7.8M outstanding). Correct query would SUM(appraisal_val) GROUP BY loan_no first, then compare with HAVING. This is a semantic reasoning limitation, not a schema linking error.

#### Test 12 - Show monthly transaction volume for the past 3 months
- **Difficulty**: Hard
- **Generated SQL**: `SELECT DATE_TRUNC('month', txn_dt) AS month, SUM(txn_amt) AS total_volume FROM bank.tbl_txn WHERE txn_dt >= CURRENT_DATE - INTERVAL '3 months' GROUP BY month ORDER BY month`
- **Correct?**: Yes
- **Notes**: Correct use of DATE_TRUNC, INTERVAL, and aggregation. Returned 2 months of data (only Jan-Feb exist in seed data).

## Key Findings

1. **Value mapping is the dominant failure mode.** Two out of three incorrect/empty results stem from the LLM not knowing valid values for status code columns. The tbl_acct table uses 'OPEN'/'FROZEN'/'CLOSED'/'DORMANT' while the LLM defaults to 'ACTIVE' (which is used in tbl_cust and tbl_loan). This inconsistency without documentation is the exact problem schema enrichment addresses.

2. **JOINs work well.** The system correctly identified join columns (cust_no, loan_no, br_cd) across all multi-table queries despite no FK constraints being defined. The DDL training and column naming conventions were sufficient.

3. **Aggregation logic is solid.** GROUP BY, SUM, COUNT, DATE_TRUNC, ORDER BY, LIMIT all generated correctly.

4. **Multi-step semantic reasoning is weak.** The collateral comparison (Test 11) required aggregating before comparing, which the LLM did not do. This type of error requires either better few-shot examples or chain-of-thought decomposition.

5. **These results directly motivate the Schema Enrichment Pipeline.** Adding sample values per column (e.g., stat_cd: OPEN, FROZEN, CLOSED, DORMANT) to the documentation collection would likely resolve Tests 4 and 10 immediately, raising baseline accuracy from 66.7% to ~83%.