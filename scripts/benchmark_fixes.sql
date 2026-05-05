-- Fix gold SQL that was too prescriptive or ambiguous
-- Run against PostgreSQL public.benchmark table

-- EASY fixes: make questions match gold SQL or vice versa

-- "What account types exist?" - don't filter by is_active, question says "exist" not "available"
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_acct_tp]'
WHERE question = 'What account types exist?';

-- "How many employees are there?" - remove WHERE, question doesn't say "active"
UPDATE public.benchmark SET gold_sql = 'SELECT COUNT(*) as total_employees FROM [bank].[tbl_emp]'
WHERE question = 'How many employees are there?';

-- "Show terminated employees" - use term_dt IS NOT NULL (clearer than stat_cd = 0)
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_emp] WHERE [term_dt] IS NOT NULL'
WHERE question = 'Show terminated employees';

-- "Show expired cards" - use exp_dt < GETDATE() which is more logical
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_card] WHERE [exp_dt] < GETDATE()'
WHERE question = 'Show expired cards';

-- "Show me the latest exchange rates" - get all rates for the latest date
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_fx_rate] WHERE [rate_dt] = (SELECT MAX([rate_dt]) FROM [bank].[tbl_fx_rate])'
WHERE question = 'Show me the latest exchange rates';

-- MEDIUM fixes: remove unnecessary JOINs for display columns

-- "Show me all accounts with customer names" - accept any columns as long as JOIN is correct
UPDATE public.benchmark SET gold_sql = 'SELECT a.*, c.[cust_nm] FROM [bank].[tbl_acct] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no]'
WHERE question = 'Show me all accounts with customer names';

-- "How many accounts does each customer have?" - don't require JOIN to tbl_cust for name
UPDATE public.benchmark SET gold_sql = 'SELECT [cust_no], COUNT(*) as account_count FROM [bank].[tbl_acct] GROUP BY [cust_no] ORDER BY account_count DESC'
WHERE question = 'How many accounts does each customer have?';

-- "What is the total balance per currency?" - don't require WHERE stat_cd = OPEN
UPDATE public.benchmark SET gold_sql = 'SELECT [ccy_cd], SUM([cur_bal]) as total_balance FROM [bank].[tbl_acct] GROUP BY [ccy_cd]'
WHERE question = 'What is the total balance per currency?';

-- "Show the top 5 accounts by balance" - don't require JOIN for cust_nm
UPDATE public.benchmark SET gold_sql = 'SELECT TOP 5 [acct_no], [ccy_cd], [cur_bal] FROM [bank].[tbl_acct] ORDER BY [cur_bal] DESC'
WHERE question = 'Show the top 5 accounts by balance';

-- "How many accounts are there per branch?" - don't require JOIN for br_nm
UPDATE public.benchmark SET gold_sql = 'SELECT [br_cd], COUNT([acct_no]) as acct_count FROM [bank].[tbl_acct] GROUP BY [br_cd] ORDER BY acct_count DESC'
WHERE question = 'How many accounts are there per branch?';

-- "Show transactions with their type names" - accept any column selection
UPDATE public.benchmark SET gold_sql = 'SELECT t.*, tp.[txn_tp_nm] FROM [bank].[tbl_txn] t JOIN [bank].[tbl_txn_tp] tp ON t.[txn_tp_cd] = tp.[txn_tp_cd]'
WHERE question = 'Show transactions with their type names';

-- "Show non-performing loans with customer names" - accept any columns
UPDATE public.benchmark SET gold_sql = 'SELECT l.*, c.[cust_nm] FROM [bank].[tbl_loan] l JOIN [bank].[tbl_cust] c ON l.[cust_no] = c.[cust_no] WHERE l.[npl_flag] = ''Y'''
WHERE question = 'Show non-performing loans with customer names';

-- "Show loans with their product names" - accept any columns
UPDATE public.benchmark SET gold_sql = 'SELECT l.*, lp.[prod_nm] FROM [bank].[tbl_loan] l JOIN [bank].[tbl_loan_prod] lp ON l.[prod_cd] = lp.[prod_cd]'
WHERE question = 'Show loans with their product names';

-- "Show me loans that are overdue by more than 30 days" - don't require JOIN for cust_nm
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_loan] WHERE [overdue_days] > 30'
WHERE question = 'Show me loans that are overdue by more than 30 days';

-- "Show employees with their branch names" - accept any columns
UPDATE public.benchmark SET gold_sql = 'SELECT e.*, b.[br_nm] FROM [bank].[tbl_emp] e JOIN [bank].[tbl_br] b ON e.[br_cd] = b.[br_cd] WHERE e.[stat_cd] = 1'
WHERE question = 'Show employees with their branch names';

-- "Show cards with customer names" - accept any columns
UPDATE public.benchmark SET gold_sql = 'SELECT cd.*, c.[cust_nm] FROM [bank].[tbl_card] cd JOIN [bank].[tbl_cust] c ON cd.[cust_no] = c.[cust_no]'
WHERE question = 'Show cards with customer names';

-- "Show customers with their branch names" - accept any columns
UPDATE public.benchmark SET gold_sql = 'SELECT c.*, b.[br_nm] FROM [bank].[tbl_cust] c JOIN [bank].[tbl_br] b ON c.[br_cd] = b.[br_cd]'
WHERE question = 'Show customers with their branch names';

-- "Show customer addresses with customer names" - accept any columns
UPDATE public.benchmark SET gold_sql = 'SELECT a.*, c.[cust_nm] FROM [bank].[tbl_cust_addr] a JOIN [bank].[tbl_cust] c ON a.[cust_no] = c.[cust_no]'
WHERE question = 'Show customer addresses with customer names';

-- "Show collateral for each loan" - accept any columns
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_coll]'
WHERE question = 'Show collateral for each loan';

-- "Show USD to MDL exchange rates" - don't require specific column selection
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_fx_rate] WHERE [ccy_from] = ''USD'' AND [ccy_to] = ''MDL'' ORDER BY [rate_dt]'
WHERE question = 'Show USD to MDL exchange rates';

-- HARD fixes

-- "Show cards that will expire within the next 6 months" - don't require JOIN for cust_nm
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_card] WHERE [exp_dt] <= DATEADD(month, 6, GETDATE()) AND [stat_cd] = ''ACTIVE'''
WHERE question = 'Show cards that will expire within the next 6 months';

-- "Show accounts where the hold amount exceeds 10% of the balance" - don't require JOIN
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_acct] WHERE [hold_amt] > [cur_bal] * 0.1 AND [cur_bal] > 0'
WHERE question = 'Show accounts where the hold amount exceeds 10% of the balance';

-- "Which accounts have not had any transactions?" - don't require JOIN for cust_nm
UPDATE public.benchmark SET gold_sql = 'SELECT * FROM [bank].[tbl_acct] WHERE [acct_no] NOT IN (SELECT DISTINCT [acct_no] FROM [bank].[tbl_txn])'
WHERE question = 'Which accounts have not had any transactions?';