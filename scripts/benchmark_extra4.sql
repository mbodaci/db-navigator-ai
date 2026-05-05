-- 4 additional medium questions to bring total from 96 to 100

INSERT INTO public.benchmark (question, gold_sql, difficulty, category, tables_involved) VALUES

('Show the total number of transactions per account', 'SELECT [acct_no], COUNT(*) as txn_count FROM [bank].[tbl_txn] GROUP BY [acct_no] ORDER BY txn_count DESC', 'medium', 'transactions', '{tbl_txn}'),

('What is the total credit limit across all credit cards?', 'SELECT SUM([lim_amt]) as total_credit_limit FROM [bank].[tbl_card] WHERE [card_tp] = ''CREDIT''', 'medium', 'cards', '{tbl_card}'),

('Show loan products with their minimum and maximum amounts', 'SELECT [prod_nm], [prod_categ], [min_amt], [max_amt], [base_rate] FROM [bank].[tbl_loan_prod]', 'medium', 'loans', '{tbl_loan_prod}'),

('How many customers are there per branch?', 'SELECT [br_cd], COUNT(*) as cust_count FROM [bank].[tbl_cust] GROUP BY [br_cd] ORDER BY cust_count DESC', 'medium', 'customers', '{tbl_cust}');