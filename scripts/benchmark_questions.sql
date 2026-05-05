-- DB-Navigator AI Benchmark: 100 NL-SQL pairs for evaluation
-- Difficulty: 30 easy, 40 medium, 20 hard, 10 extra-hard
-- Categories: accounts, transactions, customers, loans, cards, branches, employees, cross-domain

DELETE FROM public.benchmark;

-- ============================================================
-- EASY (30) - Single table SELECT, simple WHERE, basic COUNT
-- ============================================================

INSERT INTO public.benchmark (question, gold_sql, difficulty, category, tables_involved) VALUES

-- Accounts (easy)
('Show me all accounts', 'SELECT * FROM [bank].[tbl_acct]', 'easy', 'accounts', '{tbl_acct}'),
('Show me dormant accounts', 'SELECT * FROM [bank].[tbl_acct] WHERE [stat_cd] = ''DORMANT''', 'easy', 'accounts', '{tbl_acct}'),
('How many accounts are there?', 'SELECT COUNT(*) as total_accounts FROM [bank].[tbl_acct]', 'easy', 'accounts', '{tbl_acct}'),
('Show me frozen accounts', 'SELECT * FROM [bank].[tbl_acct] WHERE [stat_cd] = ''FROZEN''', 'easy', 'accounts', '{tbl_acct}'),
('Show accounts opened after 2020', 'SELECT * FROM [bank].[tbl_acct] WHERE [open_dt] > ''2020-01-01''', 'easy', 'accounts', '{tbl_acct}'),
('What account types exist?', 'SELECT * FROM [bank].[tbl_acct_tp]', 'easy', 'accounts', '{tbl_acct_tp}'),
('Show me accounts in EUR currency', 'SELECT * FROM [bank].[tbl_acct] WHERE [ccy_cd] = ''EUR''', 'easy', 'accounts', '{tbl_acct}'),

-- Customers (easy)
('Show me all active customers', 'SELECT * FROM [bank].[tbl_cust] WHERE [stat_cd] = ''ACTIVE''', 'easy', 'customers', '{tbl_cust}'),
('How many customers does the bank have?', 'SELECT COUNT(*) as total_customers FROM [bank].[tbl_cust]', 'easy', 'customers', '{tbl_cust}'),
('Show me blocked customers', 'SELECT * FROM [bank].[tbl_cust] WHERE [stat_cd] = ''BLOCKED''', 'easy', 'customers', '{tbl_cust}'),
('Show individual customers', 'SELECT * FROM [bank].[tbl_cust] WHERE [cust_tp] = ''PF''', 'easy', 'customers', '{tbl_cust}'),
('Show corporate customers', 'SELECT * FROM [bank].[tbl_cust] WHERE [cust_tp] = ''PJ''', 'easy', 'customers', '{tbl_cust}'),
('List customers registered in 2024', 'SELECT * FROM [bank].[tbl_cust] WHERE [reg_dt] >= ''2024-01-01'' AND [reg_dt] < ''2025-01-01''', 'easy', 'customers', '{tbl_cust}'),

-- Loans (easy)
('Show me all active loans', 'SELECT * FROM [bank].[tbl_loan] WHERE [stat_cd] = ''ACTIVE''', 'easy', 'loans', '{tbl_loan}'),
('Show non-performing loans', 'SELECT * FROM [bank].[tbl_loan] WHERE [npl_flag] = ''Y''', 'easy', 'loans', '{tbl_loan}'),
('How many loans are there?', 'SELECT COUNT(*) as total_loans FROM [bank].[tbl_loan]', 'easy', 'loans', '{tbl_loan}'),
('What loan products are available?', 'SELECT * FROM [bank].[tbl_loan_prod] WHERE [is_active] = 1', 'easy', 'loans', '{tbl_loan_prod}'),
('Show loans with overdue amounts', 'SELECT * FROM [bank].[tbl_loan] WHERE [overdue_amt] > 0', 'easy', 'loans', '{tbl_loan}'),

-- Branches (easy)
('Show me all branches', 'SELECT * FROM [bank].[tbl_br]', 'easy', 'branches', '{tbl_br}'),
('Show active branches', 'SELECT * FROM [bank].[tbl_br] WHERE [stat_cd] = 1', 'easy', 'branches', '{tbl_br}'),
('How many branches does the bank have?', 'SELECT COUNT(*) as total_branches FROM [bank].[tbl_br]', 'easy', 'branches', '{tbl_br}'),

-- Employees (easy)
('Show me all employees', 'SELECT * FROM [bank].[tbl_emp]', 'easy', 'employees', '{tbl_emp}'),
('How many employees are there?', 'SELECT COUNT(*) as total_employees FROM [bank].[tbl_emp] WHERE [stat_cd] = 1', 'easy', 'employees', '{tbl_emp}'),
('Show terminated employees', 'SELECT * FROM [bank].[tbl_emp] WHERE [term_dt] IS NOT NULL', 'easy', 'employees', '{tbl_emp}'),

-- Transactions (easy)
('Show me all transaction types', 'SELECT * FROM [bank].[tbl_txn_tp]', 'easy', 'transactions', '{tbl_txn_tp}'),
('How many transactions are in the database?', 'SELECT COUNT(*) as total_txns FROM [bank].[tbl_txn]', 'easy', 'transactions', '{tbl_txn}'),

-- Cards (easy)
('Show me all cards', 'SELECT * FROM [bank].[tbl_card]', 'easy', 'cards', '{tbl_card}'),
('Show expired cards', 'SELECT * FROM [bank].[tbl_card] WHERE [stat_cd] = ''EXPIRED''', 'easy', 'cards', '{tbl_card}'),
('How many credit cards exist?', 'SELECT COUNT(*) as credit_cards FROM [bank].[tbl_card] WHERE [card_tp] = ''CREDIT''', 'easy', 'cards', '{tbl_card}'),

-- FX (easy)
('Show me the latest exchange rates', 'SELECT TOP 1 [rate_dt] FROM [bank].[tbl_fx_rate] ORDER BY [rate_dt] DESC', 'easy', 'fx', '{tbl_fx_rate}');


-- ============================================================
-- MEDIUM (40) - JOINs, GROUP BY, ORDER BY, aggregate functions
-- ============================================================

INSERT INTO public.benchmark (question, gold_sql, difficulty, category, tables_involved) VALUES

-- Accounts + Customers
('Show me all accounts with customer names', 'SELECT a.[acct_no], c.[cust_nm], a.[ccy_cd], a.[cur_bal], a.[stat_cd] FROM [bank].[tbl_acct] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no]', 'medium', 'accounts', '{tbl_acct,tbl_cust}'),
('How many accounts does each customer have?', 'SELECT c.[cust_nm], COUNT(a.[acct_no]) as account_count FROM [bank].[tbl_acct] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no] GROUP BY c.[cust_nm] ORDER BY account_count DESC', 'medium', 'accounts', '{tbl_acct,tbl_cust}'),
('What is the total balance per currency?', 'SELECT [ccy_cd], SUM([cur_bal]) as total_balance FROM [bank].[tbl_acct] WHERE [stat_cd] = ''OPEN'' GROUP BY [ccy_cd]', 'medium', 'accounts', '{tbl_acct}'),
('Show the top 5 accounts by balance', 'SELECT TOP 5 a.[acct_no], c.[cust_nm], a.[ccy_cd], a.[cur_bal] FROM [bank].[tbl_acct] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no] WHERE a.[stat_cd] = ''OPEN'' ORDER BY a.[cur_bal] DESC', 'medium', 'accounts', '{tbl_acct,tbl_cust}'),
('How many accounts are there per branch?', 'SELECT b.[br_nm], COUNT(a.[acct_no]) as acct_count FROM [bank].[tbl_acct] a JOIN [bank].[tbl_br] b ON a.[br_cd] = b.[br_cd] GROUP BY b.[br_nm] ORDER BY acct_count DESC', 'medium', 'accounts', '{tbl_acct,tbl_br}'),
('Show accounts with their account type names', 'SELECT a.[acct_no], at.[acct_tp_nm], a.[ccy_cd], a.[cur_bal] FROM [bank].[tbl_acct] a JOIN [bank].[tbl_acct_tp] at ON a.[acct_tp_cd] = at.[acct_tp_cd]', 'medium', 'accounts', '{tbl_acct,tbl_acct_tp}'),
('What is the average account balance per account type?', 'SELECT at.[acct_tp_nm], AVG(a.[cur_bal]) as avg_balance FROM [bank].[tbl_acct] a JOIN [bank].[tbl_acct_tp] at ON a.[acct_tp_cd] = at.[acct_tp_cd] WHERE a.[stat_cd] = ''OPEN'' GROUP BY at.[acct_tp_nm]', 'medium', 'accounts', '{tbl_acct,tbl_acct_tp}'),

-- Transactions
('Show the total transaction volume per day', 'SELECT [txn_dt], COUNT(*) as txn_count, SUM([txn_amt]) as total_amount FROM [bank].[tbl_txn] GROUP BY [txn_dt] ORDER BY [txn_dt]', 'medium', 'transactions', '{tbl_txn}'),
('What is the total debit and credit per account?', 'SELECT [acct_no], [dr_cr_ind], SUM([txn_amt]) as total FROM [bank].[tbl_txn] GROUP BY [acct_no], [dr_cr_ind] ORDER BY [acct_no]', 'medium', 'transactions', '{tbl_txn}'),
('Show transactions with their type names', 'SELECT t.[txn_dt], t.[txn_amt], t.[dr_cr_ind], tp.[txn_tp_nm] FROM [bank].[tbl_txn] t JOIN [bank].[tbl_txn_tp] tp ON t.[txn_tp_cd] = tp.[txn_tp_cd] ORDER BY t.[txn_dt] DESC', 'medium', 'transactions', '{tbl_txn,tbl_txn_tp}'),
('How many transactions per channel?', 'SELECT [channel_cd], COUNT(*) as txn_count FROM [bank].[tbl_txn] GROUP BY [channel_cd] ORDER BY txn_count DESC', 'medium', 'transactions', '{tbl_txn}'),
('What is the largest transaction in the database?', 'SELECT TOP 1 t.[txn_id], t.[acct_no], t.[txn_amt], t.[txn_dt], t.[descr] FROM [bank].[tbl_txn] t ORDER BY t.[txn_amt] DESC', 'medium', 'transactions', '{tbl_txn}'),

-- Loans
('Show non-performing loans with customer names', 'SELECT c.[cust_nm], l.[loan_no], l.[loan_amt], l.[outst_princ], l.[overdue_amt], l.[overdue_days] FROM [bank].[tbl_loan] l JOIN [bank].[tbl_cust] c ON l.[cust_no] = c.[cust_no] WHERE l.[npl_flag] = ''Y''', 'medium', 'loans', '{tbl_loan,tbl_cust}'),
('What is the total loan portfolio by product category?', 'SELECT lp.[prod_categ], COUNT(l.[loan_no]) as loan_count, SUM(l.[outst_princ]) as total_outstanding FROM [bank].[tbl_loan] l JOIN [bank].[tbl_loan_prod] lp ON l.[prod_cd] = lp.[prod_cd] WHERE l.[stat_cd] = ''ACTIVE'' GROUP BY lp.[prod_categ] ORDER BY total_outstanding DESC', 'medium', 'loans', '{tbl_loan,tbl_loan_prod}'),
('Show loans with their product names', 'SELECT l.[loan_no], lp.[prod_nm], l.[loan_amt], l.[int_rate], l.[term_mo], l.[stat_cd] FROM [bank].[tbl_loan] l JOIN [bank].[tbl_loan_prod] lp ON l.[prod_cd] = lp.[prod_cd]', 'medium', 'loans', '{tbl_loan,tbl_loan_prod}'),
('What is the average interest rate per loan category?', 'SELECT lp.[prod_categ], AVG(l.[int_rate]) as avg_rate FROM [bank].[tbl_loan] l JOIN [bank].[tbl_loan_prod] lp ON l.[prod_cd] = lp.[prod_cd] WHERE l.[stat_cd] = ''ACTIVE'' GROUP BY lp.[prod_categ]', 'medium', 'loans', '{tbl_loan,tbl_loan_prod}'),
('Show me loans that are overdue by more than 30 days', 'SELECT l.[loan_no], c.[cust_nm], l.[overdue_amt], l.[overdue_days] FROM [bank].[tbl_loan] l JOIN [bank].[tbl_cust] c ON l.[cust_no] = c.[cust_no] WHERE l.[overdue_days] > 30', 'medium', 'loans', '{tbl_loan,tbl_cust}'),

-- Employees + Branches
('How many employees work at each branch?', 'SELECT b.[br_nm], COUNT(e.[emp_no]) as emp_count FROM [bank].[tbl_emp] e JOIN [bank].[tbl_br] b ON e.[br_cd] = b.[br_cd] WHERE e.[stat_cd] = 1 GROUP BY b.[br_nm] ORDER BY emp_count DESC', 'medium', 'employees', '{tbl_emp,tbl_br}'),
('Show employees with their branch names', 'SELECT e.[emp_nm], e.[emp_surnm], e.[emp_pos], b.[br_nm] FROM [bank].[tbl_emp] e JOIN [bank].[tbl_br] b ON e.[br_cd] = b.[br_cd] WHERE e.[stat_cd] = 1', 'medium', 'employees', '{tbl_emp,tbl_br}'),
('What is the average salary per department?', 'SELECT [dept_cd], AVG([sal_amt]) as avg_salary FROM [bank].[tbl_emp] WHERE [stat_cd] = 1 GROUP BY [dept_cd]', 'medium', 'employees', '{tbl_emp}'),
('Who are the branch managers?', 'SELECT b.[br_nm], e.[emp_nm], e.[emp_surnm] FROM [bank].[tbl_br] b JOIN [bank].[tbl_emp] e ON b.[br_mgr_emp_no] = e.[emp_no]', 'medium', 'employees', '{tbl_br,tbl_emp}'),
('Show employees hired in the last 2 years', 'SELECT [emp_nm], [emp_surnm], [emp_pos], [hire_dt] FROM [bank].[tbl_emp] WHERE [hire_dt] >= ''2024-01-01'' AND [stat_cd] = 1 ORDER BY [hire_dt] DESC', 'medium', 'employees', '{tbl_emp}'),

-- Cards
('Show cards with customer names', 'SELECT cd.[card_no_hash], c.[cust_nm], cd.[card_tp], cd.[card_brand], cd.[stat_cd] FROM [bank].[tbl_card] cd JOIN [bank].[tbl_cust] c ON cd.[cust_no] = c.[cust_no]', 'medium', 'cards', '{tbl_card,tbl_cust}'),
('How many cards per card type and brand?', 'SELECT [card_tp], [card_brand], COUNT(*) as card_count FROM [bank].[tbl_card] GROUP BY [card_tp], [card_brand]', 'medium', 'cards', '{tbl_card}'),

-- Customers
('Show customers with their branch names', 'SELECT c.[cust_nm], c.[cust_tp], b.[br_nm], c.[stat_cd] FROM [bank].[tbl_cust] c JOIN [bank].[tbl_br] b ON c.[br_cd] = b.[br_cd]', 'medium', 'customers', '{tbl_cust,tbl_br}'),
('How many customers per risk category?', 'SELECT [risk_categ], COUNT(*) as cust_count FROM [bank].[tbl_cust] GROUP BY [risk_categ]', 'medium', 'customers', '{tbl_cust}'),
('Show customers registered per month', 'SELECT FORMAT([reg_dt], ''yyyy-MM'') as reg_month, COUNT(*) as cust_count FROM [bank].[tbl_cust] GROUP BY FORMAT([reg_dt], ''yyyy-MM'') ORDER BY reg_month', 'medium', 'customers', '{tbl_cust}'),

-- Collateral
('Show collateral for each loan', 'SELECT l.[loan_no], c.[coll_tp], c.[coll_desc], c.[appraisal_val] FROM [bank].[tbl_coll] c JOIN [bank].[tbl_loan] l ON c.[loan_no] = l.[loan_no]', 'medium', 'loans', '{tbl_coll,tbl_loan}'),
('What is the total collateral value per loan?', 'SELECT [loan_no], SUM([appraisal_val]) as total_collateral FROM [bank].[tbl_coll] WHERE [stat_cd] = ''ACTIVE'' GROUP BY [loan_no]', 'medium', 'loans', '{tbl_coll}'),

-- Guarantors
('Show guarantors for each loan', 'SELECT g.[loan_no], g.[guar_nm], g.[guar_tp], g.[guar_amt] FROM [bank].[tbl_guar] g', 'medium', 'loans', '{tbl_guar}'),

-- FX
('Show USD to MDL exchange rates', 'SELECT [rate_dt], [buy_rate], [sell_rate], [bnm_rate] FROM [bank].[tbl_fx_rate] WHERE [ccy_from] = ''USD'' AND [ccy_to] = ''MDL'' ORDER BY [rate_dt]', 'medium', 'fx', '{tbl_fx_rate}'),

-- Addresses
('Show customer addresses with customer names', 'SELECT c.[cust_nm], a.[addr_tp], a.[addr_line1], a.[city], a.[region] FROM [bank].[tbl_cust_addr] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no]', 'medium', 'customers', '{tbl_cust_addr,tbl_cust}'),
('How many customers per city?', 'SELECT a.[city], COUNT(DISTINCT a.[cust_no]) as cust_count FROM [bank].[tbl_cust_addr] a GROUP BY a.[city] ORDER BY cust_count DESC', 'medium', 'customers', '{tbl_cust_addr}'),

-- Mixed
('Show the total balance per branch', 'SELECT b.[br_nm], SUM(a.[cur_bal]) as total_balance FROM [bank].[tbl_acct] a JOIN [bank].[tbl_br] b ON a.[br_cd] = b.[br_cd] WHERE a.[stat_cd] = ''OPEN'' GROUP BY b.[br_nm] ORDER BY total_balance DESC', 'medium', 'accounts', '{tbl_acct,tbl_br}'),
('Which customers have the most transactions?', 'SELECT TOP 10 c.[cust_nm], COUNT(t.[txn_id]) as txn_count FROM [bank].[tbl_txn] t JOIN [bank].[tbl_acct] a ON t.[acct_no] = a.[acct_no] JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no] GROUP BY c.[cust_nm] ORDER BY txn_count DESC', 'medium', 'transactions', '{tbl_txn,tbl_acct,tbl_cust}'),
('Show total loan amounts per branch', 'SELECT b.[br_nm], COUNT(l.[loan_no]) as loan_count, SUM(l.[loan_amt]) as total_amount FROM [bank].[tbl_loan] l JOIN [bank].[tbl_br] b ON l.[br_cd] = b.[br_cd] GROUP BY b.[br_nm] ORDER BY total_amount DESC', 'medium', 'loans', '{tbl_loan,tbl_br}');


-- ============================================================
-- HARD (20) - Nested queries, window functions, complex JOINs
-- ============================================================

INSERT INTO public.benchmark (question, gold_sql, difficulty, category, tables_involved) VALUES

('Show customers who have accounts but no loans', 'SELECT DISTINCT c.[cust_no], c.[cust_nm] FROM [bank].[tbl_cust] c JOIN [bank].[tbl_acct] a ON c.[cust_no] = a.[cust_no] WHERE c.[cust_no] NOT IN (SELECT [cust_no] FROM [bank].[tbl_loan])', 'hard', 'cross-domain', '{tbl_cust,tbl_acct,tbl_loan}'),

('Show customers who have both loans and cards', 'SELECT DISTINCT c.[cust_no], c.[cust_nm] FROM [bank].[tbl_cust] c WHERE c.[cust_no] IN (SELECT [cust_no] FROM [bank].[tbl_loan]) AND c.[cust_no] IN (SELECT [cust_no] FROM [bank].[tbl_card])', 'hard', 'cross-domain', '{tbl_cust,tbl_loan,tbl_card}'),

('Which loans have total collateral value less than the outstanding principal?', 'SELECT l.[loan_no], l.[outst_princ], COALESCE(SUM(c.[appraisal_val]), 0) as total_collateral FROM [bank].[tbl_loan] l LEFT JOIN [bank].[tbl_coll] c ON l.[loan_no] = c.[loan_no] WHERE l.[stat_cd] = ''ACTIVE'' GROUP BY l.[loan_no], l.[outst_princ] HAVING COALESCE(SUM(c.[appraisal_val]), 0) < l.[outst_princ]', 'hard', 'loans', '{tbl_loan,tbl_coll}'),

('Show the running balance for each account ordered by transaction date', 'SELECT t.[acct_no], t.[txn_dt], t.[txn_amt], t.[dr_cr_ind], t.[bal_after] FROM [bank].[tbl_txn] t ORDER BY t.[acct_no], t.[txn_dt]', 'hard', 'transactions', '{tbl_txn}'),

('Which branch has the highest average account balance?', 'SELECT TOP 1 b.[br_nm], AVG(a.[cur_bal]) as avg_balance FROM [bank].[tbl_acct] a JOIN [bank].[tbl_br] b ON a.[br_cd] = b.[br_cd] WHERE a.[stat_cd] = ''OPEN'' GROUP BY b.[br_nm] ORDER BY avg_balance DESC', 'hard', 'accounts', '{tbl_acct,tbl_br}'),

('Show employees who manage other employees', 'SELECT DISTINCT m.[emp_no], m.[emp_nm], m.[emp_surnm], m.[emp_pos] FROM [bank].[tbl_emp] m WHERE m.[emp_no] IN (SELECT [mgr_emp_no] FROM [bank].[tbl_emp] WHERE [mgr_emp_no] IS NOT NULL)', 'hard', 'employees', '{tbl_emp}'),

('What percentage of loans are non-performing?', 'SELECT CAST(SUM(CASE WHEN [npl_flag] = ''Y'' THEN 1 ELSE 0 END) AS FLOAT) * 100.0 / COUNT(*) as npl_percentage FROM [bank].[tbl_loan]', 'hard', 'loans', '{tbl_loan}'),

('Show accounts where the hold amount exceeds 10% of the balance', 'SELECT a.[acct_no], c.[cust_nm], a.[cur_bal], a.[hold_amt] FROM [bank].[tbl_acct] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no] WHERE a.[hold_amt] > a.[cur_bal] * 0.1 AND a.[cur_bal] > 0', 'hard', 'accounts', '{tbl_acct,tbl_cust}'),

('Show loan officers and how many loans each has processed', 'SELECT e.[emp_nm], e.[emp_surnm], COUNT(l.[loan_no]) as loans_processed FROM [bank].[tbl_loan] l JOIN [bank].[tbl_emp] e ON l.[loan_off_emp_no] = e.[emp_no] GROUP BY e.[emp_nm], e.[emp_surnm] ORDER BY loans_processed DESC', 'hard', 'loans', '{tbl_loan,tbl_emp}'),

('Which customers have accounts in multiple currencies?', 'SELECT c.[cust_nm], COUNT(DISTINCT a.[ccy_cd]) as currency_count FROM [bank].[tbl_acct] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no] WHERE a.[stat_cd] = ''OPEN'' GROUP BY c.[cust_nm] HAVING COUNT(DISTINCT a.[ccy_cd]) > 1', 'hard', 'accounts', '{tbl_acct,tbl_cust}'),

('Show the net transaction amount per account (credits minus debits)', 'SELECT [acct_no], SUM(CASE WHEN [dr_cr_ind] = ''C'' THEN [txn_amt] ELSE 0 END) - SUM(CASE WHEN [dr_cr_ind] = ''D'' THEN [txn_amt] ELSE 0 END) as net_amount FROM [bank].[tbl_txn] GROUP BY [acct_no] ORDER BY net_amount DESC', 'hard', 'transactions', '{tbl_txn}'),

('Show customers with more than 3 accounts', 'SELECT c.[cust_nm], COUNT(a.[acct_no]) as acct_count FROM [bank].[tbl_acct] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no] GROUP BY c.[cust_nm] HAVING COUNT(a.[acct_no]) > 3', 'hard', 'customers', '{tbl_acct,tbl_cust}'),

('Show the collateral coverage ratio for each active loan', 'SELECT l.[loan_no], l.[outst_princ], COALESCE(SUM(c.[appraisal_val]), 0) as collateral_value, CASE WHEN l.[outst_princ] > 0 THEN COALESCE(SUM(c.[appraisal_val]), 0) / l.[outst_princ] ELSE 0 END as coverage_ratio FROM [bank].[tbl_loan] l LEFT JOIN [bank].[tbl_coll] c ON l.[loan_no] = c.[loan_no] WHERE l.[stat_cd] = ''ACTIVE'' GROUP BY l.[loan_no], l.[outst_princ]', 'hard', 'loans', '{tbl_loan,tbl_coll}'),

('Show the spread between buy and sell rates for each currency pair', 'SELECT [ccy_from], [ccy_to], [rate_dt], [sell_rate] - [buy_rate] as spread FROM [bank].[tbl_fx_rate] ORDER BY [rate_dt], [ccy_from]', 'hard', 'fx', '{tbl_fx_rate}'),

('Which branches have no loans?', 'SELECT b.[br_cd], b.[br_nm] FROM [bank].[tbl_br] b WHERE b.[br_cd] NOT IN (SELECT DISTINCT [br_cd] FROM [bank].[tbl_loan] WHERE [br_cd] IS NOT NULL)', 'hard', 'branches', '{tbl_br,tbl_loan}'),

('Show cards that will expire within the next 6 months', 'SELECT cd.[card_no_hash], c.[cust_nm], cd.[card_brand], cd.[exp_dt] FROM [bank].[tbl_card] cd JOIN [bank].[tbl_cust] c ON cd.[cust_no] = c.[cust_no] WHERE cd.[exp_dt] <= DATEADD(month, 6, GETDATE()) AND cd.[stat_cd] = ''ACTIVE''', 'hard', 'cards', '{tbl_card,tbl_cust}'),

('What is the total outstanding principal per customer?', 'SELECT c.[cust_nm], SUM(l.[outst_princ]) as total_outstanding FROM [bank].[tbl_loan] l JOIN [bank].[tbl_cust] c ON l.[cust_no] = c.[cust_no] WHERE l.[stat_cd] = ''ACTIVE'' GROUP BY c.[cust_nm] ORDER BY total_outstanding DESC', 'hard', 'loans', '{tbl_loan,tbl_cust}'),

('Show the BNM rate trend for USD to MDL', 'SELECT [rate_dt], [bnm_rate] FROM [bank].[tbl_fx_rate] WHERE [ccy_from] = ''USD'' AND [ccy_to] = ''MDL'' ORDER BY [rate_dt]', 'hard', 'fx', '{tbl_fx_rate}'),

('Which accounts have not had any transactions?', 'SELECT a.[acct_no], c.[cust_nm], a.[open_dt] FROM [bank].[tbl_acct] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no] WHERE a.[acct_no] NOT IN (SELECT DISTINCT [acct_no] FROM [bank].[tbl_txn])', 'hard', 'accounts', '{tbl_acct,tbl_cust,tbl_txn}'),

('Show the number of guarantors per loan', 'SELECT l.[loan_no], COUNT(g.[guar_id]) as guarantor_count FROM [bank].[tbl_loan] l LEFT JOIN [bank].[tbl_guar] g ON l.[loan_no] = g.[loan_no] GROUP BY l.[loan_no] ORDER BY guarantor_count DESC', 'hard', 'loans', '{tbl_loan,tbl_guar}');


-- ============================================================
-- EXTRA-HARD (10) - Multi-step reasoning, 3+ table JOINs, complex logic
-- ============================================================

INSERT INTO public.benchmark (question, gold_sql, difficulty, category, tables_involved) VALUES

('Show a complete customer profile with their accounts, loans, and cards count', 'SELECT c.[cust_nm], c.[cust_tp], c.[stat_cd], COUNT(DISTINCT a.[acct_no]) as accounts, COUNT(DISTINCT l.[loan_no]) as loans, COUNT(DISTINCT cd.[card_no_hash]) as cards FROM [bank].[tbl_cust] c LEFT JOIN [bank].[tbl_acct] a ON c.[cust_no] = a.[cust_no] LEFT JOIN [bank].[tbl_loan] l ON c.[cust_no] = l.[cust_no] LEFT JOIN [bank].[tbl_card] cd ON c.[cust_no] = cd.[cust_no] GROUP BY c.[cust_nm], c.[cust_tp], c.[stat_cd]', 'extra-hard', 'cross-domain', '{tbl_cust,tbl_acct,tbl_loan,tbl_card}'),

('Show branch performance summary with total deposits, loans, and employee count', 'SELECT b.[br_nm], COUNT(DISTINCT e.[emp_no]) as employees, COUNT(DISTINCT a.[acct_no]) as accounts, SUM(CASE WHEN a.[stat_cd] = ''OPEN'' THEN a.[cur_bal] ELSE 0 END) as total_deposits, COUNT(DISTINCT l.[loan_no]) as loans FROM [bank].[tbl_br] b LEFT JOIN [bank].[tbl_emp] e ON b.[br_cd] = e.[br_cd] AND e.[stat_cd] = 1 LEFT JOIN [bank].[tbl_acct] a ON b.[br_cd] = a.[br_cd] LEFT JOIN [bank].[tbl_loan] l ON b.[br_cd] = l.[br_cd] GROUP BY b.[br_nm]', 'extra-hard', 'cross-domain', '{tbl_br,tbl_emp,tbl_acct,tbl_loan}'),

('For each non-performing loan, show the customer name, loan details, collateral coverage, and guarantor count', 'SELECT c.[cust_nm], l.[loan_no], l.[loan_amt], l.[outst_princ], l.[overdue_days], COALESCE(coll.[total_coll], 0) as total_collateral, COALESCE(guar.[guar_count], 0) as guarantors FROM [bank].[tbl_loan] l JOIN [bank].[tbl_cust] c ON l.[cust_no] = c.[cust_no] LEFT JOIN (SELECT [loan_no], SUM([appraisal_val]) as total_coll FROM [bank].[tbl_coll] GROUP BY [loan_no]) coll ON l.[loan_no] = coll.[loan_no] LEFT JOIN (SELECT [loan_no], COUNT(*) as guar_count FROM [bank].[tbl_guar] GROUP BY [loan_no]) guar ON l.[loan_no] = guar.[loan_no] WHERE l.[npl_flag] = ''Y''', 'extra-hard', 'loans', '{tbl_loan,tbl_cust,tbl_coll,tbl_guar}'),

('Which loan officers have the highest NPL rate?', 'SELECT e.[emp_nm], e.[emp_surnm], COUNT(l.[loan_no]) as total_loans, SUM(CASE WHEN l.[npl_flag] = ''Y'' THEN 1 ELSE 0 END) as npl_loans, CAST(SUM(CASE WHEN l.[npl_flag] = ''Y'' THEN 1 ELSE 0 END) AS FLOAT) * 100.0 / COUNT(l.[loan_no]) as npl_rate FROM [bank].[tbl_loan] l JOIN [bank].[tbl_emp] e ON l.[loan_off_emp_no] = e.[emp_no] GROUP BY e.[emp_nm], e.[emp_surnm] ORDER BY npl_rate DESC', 'extra-hard', 'loans', '{tbl_loan,tbl_emp}'),

('Show a daily transaction summary with total credits, total debits, and net flow', 'SELECT [txn_dt], SUM(CASE WHEN [dr_cr_ind] = ''C'' THEN [txn_amt] ELSE 0 END) as total_credits, SUM(CASE WHEN [dr_cr_ind] = ''D'' THEN [txn_amt] ELSE 0 END) as total_debits, SUM(CASE WHEN [dr_cr_ind] = ''C'' THEN [txn_amt] ELSE -[txn_amt] END) as net_flow FROM [bank].[tbl_txn] GROUP BY [txn_dt] ORDER BY [txn_dt]', 'extra-hard', 'transactions', '{tbl_txn}'),

('Show customers whose total loan exposure exceeds their total account balances', 'SELECT c.[cust_nm], COALESCE(acct.[total_bal], 0) as total_balance, COALESCE(loan.[total_outstanding], 0) as total_loans FROM [bank].[tbl_cust] c LEFT JOIN (SELECT [cust_no], SUM([cur_bal]) as total_bal FROM [bank].[tbl_acct] WHERE [stat_cd] = ''OPEN'' GROUP BY [cust_no]) acct ON c.[cust_no] = acct.[cust_no] LEFT JOIN (SELECT [cust_no], SUM([outst_princ]) as total_outstanding FROM [bank].[tbl_loan] WHERE [stat_cd] = ''ACTIVE'' GROUP BY [cust_no]) loan ON c.[cust_no] = loan.[cust_no] WHERE COALESCE(loan.[total_outstanding], 0) > COALESCE(acct.[total_bal], 0) AND COALESCE(loan.[total_outstanding], 0) > 0', 'extra-hard', 'cross-domain', '{tbl_cust,tbl_acct,tbl_loan}'),

('Show the product mix for each branch - how many of each loan product category each branch has', 'SELECT b.[br_nm], lp.[prod_categ], COUNT(l.[loan_no]) as loan_count, SUM(l.[loan_amt]) as total_amount FROM [bank].[tbl_loan] l JOIN [bank].[tbl_br] b ON l.[br_cd] = b.[br_cd] JOIN [bank].[tbl_loan_prod] lp ON l.[prod_cd] = lp.[prod_cd] GROUP BY b.[br_nm], lp.[prod_categ] ORDER BY b.[br_nm], loan_count DESC', 'extra-hard', 'loans', '{tbl_loan,tbl_br,tbl_loan_prod}'),

('For each customer, show their total deposits, total loans, and the net position', 'SELECT c.[cust_nm], c.[cust_tp], COALESCE(SUM(a.[cur_bal]), 0) as total_deposits, COALESCE(loan.[total_outstanding], 0) as total_loans, COALESCE(SUM(a.[cur_bal]), 0) - COALESCE(loan.[total_outstanding], 0) as net_position FROM [bank].[tbl_cust] c LEFT JOIN [bank].[tbl_acct] a ON c.[cust_no] = a.[cust_no] AND a.[stat_cd] = ''OPEN'' LEFT JOIN (SELECT [cust_no], SUM([outst_princ]) as total_outstanding FROM [bank].[tbl_loan] WHERE [stat_cd] = ''ACTIVE'' GROUP BY [cust_no]) loan ON c.[cust_no] = loan.[cust_no] GROUP BY c.[cust_nm], c.[cust_tp], loan.[total_outstanding] ORDER BY net_position', 'extra-hard', 'cross-domain', '{tbl_cust,tbl_acct,tbl_loan}'),

('Show the employee hierarchy - each employee with their manager name', 'SELECT e.[emp_nm], e.[emp_surnm], e.[emp_pos], m.[emp_nm] as mgr_nm, m.[emp_surnm] as mgr_surnm FROM [bank].[tbl_emp] e LEFT JOIN [bank].[tbl_emp] m ON e.[mgr_emp_no] = m.[emp_no] WHERE e.[stat_cd] = 1', 'extra-hard', 'employees', '{tbl_emp}'),

('Show transaction activity per customer per month with totals', 'SELECT c.[cust_nm], FORMAT(t.[txn_dt], ''yyyy-MM'') as txn_month, COUNT(t.[txn_id]) as txn_count, SUM(t.[txn_amt]) as total_amount FROM [bank].[tbl_txn] t JOIN [bank].[tbl_acct] a ON t.[acct_no] = a.[acct_no] JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no] GROUP BY c.[cust_nm], FORMAT(t.[txn_dt], ''yyyy-MM'') ORDER BY c.[cust_nm], txn_month', 'extra-hard', 'transactions', '{tbl_txn,tbl_acct,tbl_cust}');