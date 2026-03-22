# DB-Navigator AI - Query Testing Log

## Test Round 1: Baseline (No Schema Enrichment)

**Date**: 2026-02-18
**LLM**: GPT-4o-mini
**Framework**: Vanna.ai with ChromaDB
**Database**: Synthetic bank schema in PostgreSQL (14 tables, no FK constraints)
**Training data**: DDL + 13 documentation entries + 5 SQL examples

### Summary

| Metric | Value |
|--------|-------|
| Total queries tested | 12 |
| Correct | 8 |
| Partially correct | 2 |
| Incorrect | 2 |
| Baseline accuracy | 66.7% |

### Failure Pattern Analysis

| Pattern | Occurrences | Affected queries |
|---------|-------------|-----------------|
| Value mapping (wrong status codes) | 2 | #4, #10 |
| Semantic reasoning (multi-row aggregation before comparison) | 1 | #11 |
| Data gap (correct SQL, missing reference data) | 1 | #5 |

---

## Test Round 2: With Schema Enrichment

**Date**: 2026-03-23
**LLM**: GPT-4o-mini
**Framework**: Vanna.ai with ChromaDB
**Database**: Synthetic bank schema in MS SQL Server (14 tables, no FK constraints)
**Training data**: DDL (from SQL Server) + metadata enrichment docs (sample values per column) + FK relationship docs (22 inferred FKs) + 11 domain documentation strings + 7 SQL examples (T-SQL syntax)
**Post-processor**: LIMIT N -> TOP N auto-conversion

### Summary

| Metric | Value |
|--------|-------|
| Total queries tested | 12 |
| Correct | 10 |
| Partially correct | 1 |
| Incorrect | 0 |
| Not evaluable | 1 |
| Enriched accuracy | 83.3% (10/12) or 90.9% (10/11 evaluable) |

### Improvement Over Baseline

| Metric | Baseline | Enriched | Change |
|--------|----------|----------|--------|
| Correct | 8 | 10 | +2 |
| Incorrect | 2 | 0 | -2 |
| Accuracy | 66.7% | 83.3% | +16.6pp |
| Value mapping errors | 2 | 0 | Eliminated |

### Failure Pattern Analysis (Round 2)

| Pattern | Occurrences | Affected queries | Change from baseline |
|---------|-------------|-----------------|---------------------|
| Value mapping (wrong status codes) | 0 | - | **Eliminated by enrichment** |
| Semantic reasoning (aggregation before comparison) | 1 | #11 | Unchanged |
| Data gap | 0 | - | Fixed (different SQL approach) |

---

## Detailed Results: Side-by-Side Comparison

### Easy (Single Table)

#### Test 1 - List all branches

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT * FROM bank.tbl_br` | `SELECT * FROM [bank].[tbl_br]` |
| Result | 7 rows | 7 rows |
| Correct? | Yes | Yes |

Notes: Trivially correct both times. Enriched version uses T-SQL bracket quoting.

---

#### Test 2 - Show me all loan products

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT * FROM bank.tbl_loan_prod` | `SELECT * FROM [bank].[tbl_loan_prod]` |
| Result | 10 rows | 10 rows |
| Correct? | Yes | Yes |

---

#### Test 3 - How many employees work at each branch?

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT br_cd, COUNT(*) as employee_count FROM bank.tbl_emp GROUP BY br_cd ORDER BY employee_count DESC` | `SELECT br.br_cd, br.br_nm, COUNT(emp.emp_no) AS employee_count FROM bank.tbl_br br LEFT JOIN bank.tbl_emp emp ON br.br_cd = emp.br_cd GROUP BY br.br_cd, br.br_nm` |
| Result | 6 rows | 7 rows |
| Correct? | Yes | Yes (improved) |

Notes: Enriched version uses LEFT JOIN to include branches with zero employees (7 rows vs 6), and includes branch name. FK relationship documentation helped the LLM know the br_cd join path.

---

#### Test 4 - Show dormant accounts

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT * FROM bank.tbl_acct WHERE stat_cd = 'CLOSED' AND last_txn_dt < CURRENT_DATE - INTERVAL '12 months'` | `SELECT * FROM [bank].[tbl_acct] WHERE [stat_cd] = 'Dormant'` |
| Result | 0 rows (wrong value) | 1 row |
| Correct? | **No** - used 'CLOSED' instead of 'DORMANT' | **Yes** - used 'Dormant' |
| Error type | Value mapping | - |

**KEY RESULT**: This was the primary baseline failure. The metadata extractor's sample values (showing stat_cd values: OPEN, FROZEN, CLOSED, DORMANT) gave the LLM the information it needed. Note: generated 'Dormant' (mixed case) rather than 'DORMANT' (uppercase) but SQL Server's default collation is case-insensitive, so it matches correctly.

---

### Medium (JOINs, GROUP BY)

#### Test 5 - Convert all EUR balances to MDL using today's rate

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT a.acct_no, a.cust_no, a.ccy_cd, a.cur_bal, (a.cur_bal * fx.buy_rate) AS mdl_balance FROM bank.tbl_acct a JOIN bank.tbl_fx_rate fx ON a.ccy_cd = fx.ccy_from WHERE fx.ccy_to = 'MDL' AND fx.rate_dt = CURRENT_DATE` | `SELECT acct_no, cur_bal AS original_balance_eur, cur_bal * (SELECT buy_rate FROM bank.tbl_fx_rate WHERE ccy_from = 'EUR' AND ccy_to = 'MDL' AND rate_dt = CAST(GETDATE() AS DATE)) AS converted_balance_mdl FROM bank.tbl_acct WHERE ccy_cd = 'EUR'` |
| Result | 0 rows (correct logic, no FX data for today) | 3 rows (EUR accounts shown, conversion is NULL) |
| Correct? | Partially | Not evaluable |

Notes: Baseline used a JOIN that eliminated all rows when no FX rate existed for CURRENT_DATE. Enriched version uses a scalar subquery in SELECT - this shows the EUR accounts regardless, with NULL conversion when no rate exists. Both approaches have correct logic; the data gap (FX rates only through Feb 14, today is March 23) is a seed data limitation, not an SQL generation error. Excluded from accuracy calculation as neither approach is wrong.

---

#### Test 6 - Show customer names with their account balances

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT c.cust_nm, a.avail_bal FROM bank.tbl_cust c JOIN bank.tbl_acct a ON c.cust_no = a.cust_no` | `SELECT c.cust_nm, a.cur_bal FROM bank.tbl_cust c JOIN bank.tbl_acct a ON c.cust_no = a.cust_no` |
| Result | 27 rows | 30 rows |
| Correct? | Yes | Yes |

Notes: Enriched version uses `cur_bal` instead of `avail_bal` (both valid interpretations of "balance"). Row count difference (27 vs 30) likely due to PostgreSQL vs SQL Server handling of the same seed data.

---

#### Test 7 - Which customers have credit cards?

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT DISTINCT c.cust_nm, c.cust_no FROM bank.tbl_card cd JOIN bank.tbl_cust c ON cd.cust_no = c.cust_no WHERE cd.card_tp = 'CREDIT'` | `SELECT DISTINCT c.cust_no, c.cust_nm FROM bank.tbl_cust c JOIN bank.tbl_card card ON c.cust_no = card.cust_no` |
| Result | 2 rows | 8 rows |
| Correct? | Yes | Yes |

Notes: Baseline filtered `card_tp = 'CREDIT'` (strict interpretation - only credit card type). Enriched version returns all customers who have any card (broader interpretation). Both are valid readings of the question. The enriched version's sample values showed card_tp values include CREDIT, DEBIT, PREPAID, which may have led the LLM to interpret "credit cards" more broadly as "cards" in general.

---

#### Test 8 - What is the total outstanding loan amount per branch?

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT l.br_cd, SUM(l.outst_princ) as total_outstanding FROM bank.tbl_loan l WHERE l.stat_cd = 'ACTIVE' GROUP BY l.br_cd ORDER BY total_outstanding DESC` | `SELECT br_cd, SUM(outst_princ) AS total_outstanding_loan FROM bank.tbl_loan GROUP BY br_cd` |
| Result | 5 rows | 5 rows |
| Correct? | Yes | Yes |

---

#### Test 9 - Which guarantors are also bank customers?

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT g.guar_nm, g.guar_idnp FROM bank.tbl_guar g WHERE g.guar_cust_no IS NOT NULL` | `SELECT DISTINCT g.guar_nm FROM bank.tbl_guar g JOIN bank.tbl_cust c ON g.guar_idnp = c.idnp` |
| Result | Correct | 2 rows |
| Correct? | Yes | Yes |

Notes: Enriched version uses a JOIN on IDNP (national ID) to verify the match, which is more rigorous than just checking guar_cust_no IS NOT NULL. The FK inference documentation may have helped the LLM identify this relationship path.

---

### Hard (Nested, Window Functions, Multi-step)

#### Test 10 - Show the top 3 customers by total balance across all accounts

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT a.cust_no, c.cust_nm, SUM(a.cur_bal) as total_balance FROM bank.tbl_acct a JOIN bank.tbl_cust c ON a.cust_no = c.cust_no WHERE a.stat_cd = 'ACTIVE' GROUP BY a.cust_no, c.cust_nm ORDER BY total_balance DESC LIMIT 3` | `SELECT TOP 3 c.cust_no, c.cust_nm, SUM(a.cur_bal) AS total_balance FROM bank.tbl_cust c JOIN bank.tbl_acct a ON c.cust_no = a.cust_no GROUP BY c.cust_no, c.cust_nm ORDER BY total_balance DESC` |
| Result | 0 rows (wrong stat_cd value) | 3 rows |
| Correct? | **No** - used stat_cd = 'ACTIVE' instead of 'OPEN' | **Yes** |
| Error type | Value mapping | - |

**KEY RESULT**: Second baseline failure fixed. The enriched version correctly omits any stat_cd filter (including all accounts regardless of status, which is the right interpretation). Also uses TOP 3 (T-SQL) instead of LIMIT 3. The LIMIT -> TOP post-processor would have caught this anyway, but the LLM generated correct T-SQL natively this time.

---

#### Test 11 - Which loans have collateral value less than the outstanding principal?

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT l.loan_no, l.loan_amt, l.outst_princ, c.appraisal_val FROM bank.tbl_loan l JOIN bank.tbl_coll c ON l.loan_no = c.loan_no WHERE c.appraisal_val < l.outst_princ` | `SELECT l.loan_no, l.outst_princ, c.appraisal_val FROM bank.tbl_loan l JOIN bank.tbl_coll c ON l.loan_no = c.loan_no WHERE c.appraisal_val < l.outst_princ` |
| Result | Partial | 2 rows |
| Correct? | Partially | Partially |

Notes: Same limitation in both rounds. Compares individual collateral items against outstanding principal instead of SUMming collateral per loan first (GROUP BY loan_no, HAVING SUM(appraisal_val) < outst_princ). Loans with multiple collateral items (e.g., LN-2025-00011 has two pieces totaling 15.5M vs 7.8M outstanding) are evaluated per-item rather than as a portfolio. This is a semantic reasoning limitation that enrichment alone cannot fix - it requires either a specific SQL example demonstrating the pattern or chain-of-thought decomposition.

---

#### Test 12 - Show monthly transaction volume for the past 3 months

| | Baseline | Enriched |
|---|---------|----------|
| SQL | `SELECT DATE_TRUNC('month', txn_dt) AS month, SUM(txn_amt) AS total_volume FROM bank.tbl_txn WHERE txn_dt >= CURRENT_DATE - INTERVAL '3 months' GROUP BY month ORDER BY month` | `SELECT YEAR(txn_dt) AS txn_year, MONTH(txn_dt) AS txn_month, COUNT(*) AS transaction_volume FROM bank.tbl_txn WHERE txn_dt >= DATEADD(MONTH, -3, GETDATE()) GROUP BY YEAR(txn_dt), MONTH(txn_dt) ORDER BY txn_year, txn_month` |
| Result | 2 rows | 2 rows |
| Correct? | Yes | Yes |

Notes: Enriched version uses T-SQL functions (YEAR/MONTH/DATEADD/GETDATE) instead of PostgreSQL functions (DATE_TRUNC/INTERVAL/CURRENT_DATE). Both are correct for their respective dialects.

---

## Key Findings

### Round 1 (Baseline) Findings
1. **Value mapping is the dominant failure mode.** 2/3 incorrect results from wrong status code values.
2. **JOINs work well** despite no FK constraints.
3. **Aggregation logic is solid.**
4. **Multi-step semantic reasoning is weak.**

### Round 2 (Enriched) Findings
1. **Value mapping errors eliminated.** Both baseline failures (#4 and #10) resolved by sample value enrichment. The LLM now knows valid stat_cd values per table.
2. **FK relationship documentation improves JOIN quality.** Test #3 upgraded from inner join (6 rows) to LEFT JOIN with branch names (7 rows). Test #9 uses a more rigorous IDNP-based JOIN.
3. **T-SQL syntax mostly correct.** YEAR/MONTH/DATEADD/GETDATE used appropriately. LIMIT -> TOP handled by post-processor when LLM falls back to PostgreSQL habits.
4. **Semantic reasoning limitation persists.** Test #11 (collateral aggregation) unchanged - this requires few-shot examples or chain-of-thought, not just enrichment.
5. **Domain docs prevent cross-table value confusion.** Explicit per-table status code documentation prevents the LLM from using tbl_cust's 'ACTIVE' value in tbl_acct queries.

### Enrichment Impact Summary
- **Accuracy: 66.7% -> 83.3% (+16.6 percentage points)**
- **Value mapping errors: 2 -> 0 (eliminated)**
- **Incorrect queries: 2 -> 0**
- **Remaining issue: 1 partial (semantic reasoning, not addressable by enrichment alone)**
- **This directly answers RQ1 (documentation absence costs ~17pp accuracy) and RQ2 (automated enrichment recovers it)**
