-- ============================================================
-- SEED DATA - enough for meaningful testing
-- Deliberately includes edge cases: NULLs, dormant accounts,
-- NPL loans, closed branches, terminated employees
-- ============================================================

-- Branches
SET IDENTITY_INSERT bank.tbl_br ON;
INSERT INTO bank.tbl_br (br_cd, br_nm, br_addr, br_city, br_region, br_mgr_emp_no, open_dt, stat_cd) VALUES
('BR001', 'Filiala Centrala', 'Bd. Stefan cel Mare 180', 'Chisinau', 'Chisinau', 'E001', '1991-06-15', 1),
('BR002', 'Filiala Botanica', 'Str. Decebal 78', 'Chisinau', 'Chisinau', 'E005', '1995-03-20', 1),
('BR003', 'Filiala Balti', 'Str. Independentei 44', 'Balti', 'Balti', 'E010', '1998-01-10', 1),
('BR004', 'Filiala Cahul', 'Str. Republicii 12', 'Cahul', 'Cahul', 'E015', '2002-05-01', 1),
('BR005', 'Filiala Ungheni', 'Str. Nationala 88', 'Ungheni', 'Ungheni', NULL, '2004-09-15', 0),  -- closed branch
('BR006', 'Filiala Orhei', 'Str. Vasile Lupu 55', 'Orhei', 'Orhei', 'E020', '2008-11-01', 1),
('BR007', 'Filiala Comrat', 'Str. Pobedei 30', 'Comrat', 'Gagauzia', 'E022', '2010-03-01', 1);

-- Employees (25 employees across branches)
SET IDENTITY_INSERT bank.tbl_emp ON;
INSERT INTO bank.tbl_emp (emp_no, emp_nm, emp_surnm, emp_pos, br_cd, dept_cd, hire_dt, term_dt, mgr_emp_no, sal_amt, stat_cd) VALUES
('E001', 'Ion', 'Munteanu', 'Director Filiala', 'BR001', 'MGMT', '1995-01-15', NULL, NULL, 45000.00, 1),
('E002', 'Maria', 'Popescu', 'Specialist Credite Senior', 'BR001', 'CREDIT', '2000-03-01', NULL, 'E001', 28000.00, 1),
('E003', 'Andrei', 'Ciobanu', 'Specialist Credite', 'BR001', 'CREDIT', '2015-06-01', NULL, 'E002', 18000.00, 1),
('E004', 'Elena', 'Rusu', 'Casier Principal', 'BR001', 'OPS', '2005-09-10', NULL, 'E001', 15000.00, 1),
('E005', 'Victor', 'Moraru', 'Director Filiala', 'BR002', 'MGMT', '1998-04-20', NULL, NULL, 42000.00, 1),
('E006', 'Ana', 'Cojocaru', 'Specialist Credite', 'BR002', 'CREDIT', '2018-01-15', NULL, 'E005', 16000.00, 1),
('E007', 'Dumitru', 'Lungu', 'Operator Bancar', 'BR002', 'OPS', '2019-07-01', NULL, 'E005', 12000.00, 1),
('E008', 'Natalia', 'Rosca', 'Specialist Carduri', 'BR002', 'CARDS', '2017-03-15', '2024-08-31', 'E005', 14000.00, 0), -- terminated
('E009', 'Cristian', 'Grosu', 'Analist Risc', 'BR001', 'RISK', '2020-02-01', NULL, 'E001', 22000.00, 1),
('E010', 'Svetlana', 'Bodean', 'Director Filiala', 'BR003', 'MGMT', '2000-01-10', NULL, NULL, 38000.00, 1),
('E011', 'Alexandru', 'Tarna', 'Specialist Credite', 'BR003', 'CREDIT', '2016-04-01', NULL, 'E010', 16500.00, 1),
('E012', 'Olga', 'Bivol', 'Casier', 'BR003', 'OPS', '2021-09-01', NULL, 'E010', 11000.00, 1),
('E013', 'Sergiu', 'Cebotari', 'Operator Bancar', 'BR001', 'OPS', '2022-01-15', NULL, 'E004', 11500.00, 1),
('E014', 'Valentina', 'Ababii', 'Specialist AML', 'BR001', 'COMPL', '2019-05-01', NULL, 'E001', 25000.00, 1),
('E015', 'Mihai', 'Pascaru', 'Director Filiala', 'BR004', 'MGMT', '2003-06-01', NULL, NULL, 36000.00, 1),
('E016', 'Diana', 'Sirbu', 'Specialist Credite', 'BR004', 'CREDIT', '2020-11-01', NULL, 'E015', 15000.00, 1),
('E017', 'Ruslan', 'Ceban', 'Operator Bancar', 'BR004', 'OPS', '2023-03-01', NULL, 'E015', 10500.00, 1),
('E018', 'Irina', 'Gavriliuc', 'Specialist IT', 'BR001', 'IT', '2018-08-15', NULL, 'E001', 30000.00, 1),
('E019', 'Pavel', 'Rotaru', 'Specialist Depozite', 'BR001', 'DEPOSITS', '2017-06-01', NULL, 'E001', 17000.00, 1),
('E020', 'Tatiana', 'Butnaru', 'Director Filiala', 'BR006', 'MGMT', '2009-01-01', NULL, NULL, 35000.00, 1),
('E021', 'Igor', 'Damaschin', 'Specialist Credite', 'BR006', 'CREDIT', '2021-04-15', NULL, 'E020', 14500.00, 1),
('E022', 'Galina', 'Ursachi', 'Director Filiala', 'BR007', 'MGMT', '2010-05-01', NULL, NULL, 34000.00, 1),
('E023', 'Vasile', 'Chitoroaga', 'Operator Bancar', 'BR007', 'OPS', '2022-06-01', NULL, 'E022', 10000.00, 1),
('E024', 'Ludmila', 'Gutu', 'Contabil Sef', 'BR001', 'FINANCE', '2001-02-01', NULL, 'E001', 35000.00, 1),
('E025', 'Nicolae', 'Vrabie', 'Specialist Credite Junior', 'BR001', 'CREDIT', '2024-01-15', NULL, 'E002', 12000.00, 1);

-- Account types
SET IDENTITY_INSERT bank.tbl_acct_t ON;
INSERT INTO bank.tbl_acct_tp (acct_tp_cd, acct_tp_nm, acct_tp_desc, ccy_cd, is_active) VALUES
('CUR_PF', 'Cont Curent PF', 'Cont curent pentru persoane fizice', 'MDL', 1),
('CUR_PJ', 'Cont Curent PJ', 'Cont curent pentru persoane juridice', 'MDL', 1),
('DEP_TRM', 'Depozit la Termen', 'Depozit cu termen fix', 'MDL', 1),
('DEP_VED', 'Depozit la Vedere', 'Depozit fara termen fix', 'MDL', 1),
('SAV', 'Cont Economii', 'Cont de economii cu dobanda', 'MDL', 1),
('CRD_LN', 'Cont Credit', 'Cont asociat unui credit', 'MDL', 1),
('CUR_USD', 'Cont Curent USD', 'Cont curent in dolari', 'USD', 1),
('CUR_EUR', 'Cont Curent EUR', 'Cont curent in euro', 'EUR', 1),
('ESCROW', 'Cont Escrow', 'Cont escrow pentru tranzactii imobiliare', 'MDL', 0); -- discontinued

-- Transaction types
SET IDENTITY_INSERT bank.tbl_txn_tp ON;
INSERT INTO bank.tbl_txn_tp (txn_tp_cd, txn_tp_nm, txn_tp_desc, dr_cr_ind, is_active) VALUES
('DEP_CSH', 'Depunere Numerar', 'Depunere numerar la ghiseu', 'C', 1),
('WDR_CSH', 'Retragere Numerar', 'Retragere numerar la ghiseu sau ATM', 'D', 1),
('TRF_INT', 'Transfer Intern', 'Transfer intre conturi MAIB', 'D', 1),
('TRF_EXT', 'Transfer Extern', 'Transfer catre alta banca', 'D', 1),
('TRF_IN', 'Transfer Primit', 'Transfer primit de la alta banca', 'C', 1),
('PMT_LN', 'Plata Credit', 'Plata rata credit', 'D', 1),
('DISB_LN', 'Disbursare Credit', 'Eliberare credit in cont', 'C', 1),
('FEE', 'Comision', 'Comision bancar', 'D', 1),
('INT_DEP', 'Dobanda Depozit', 'Dobanda acumulata la depozit', 'C', 1),
('POS', 'Plata POS', 'Plata prin terminal POS', 'D', 1),
('ATM_WDR', 'Retragere ATM', 'Retragere de la bancomat', 'D', 1),
('FX_BUY', 'Cumparare Valuta', 'Operatiune de cumparare valuta', 'D', 1),
('FX_SELL', 'Vanzare Valuta', 'Operatiune de vanzare valuta', 'C', 1);

-- Customers (20 customers - mix of PF and PJ, various statuses)
SET IDENTITY_INSERT bank.tbl_cust ON;
INSERT INTO bank.tbl_cust (cust_no, cust_tp, cust_nm, idnp, idno, birth_dt, gender_cd, phone_no, email_addr, reg_dt, br_cd, risk_categ, stat_cd) VALUES
('C00001', 'PF', 'Petru Costin',       '2003456789012', NULL, '1985-03-15', 'M', '+37369123456', 'p.costin@mail.md',     '2015-01-20', 'BR001', 'LOW',  'ACTIVE'),
('C00002', 'PF', 'Alina Dumbraveanu',  '2003456789013', NULL, '1990-07-22', 'F', '+37368234567', 'a.dumbr@mail.md',      '2016-05-10', 'BR001', 'LOW',  'ACTIVE'),
('C00003', 'PJ', 'SRL Agroterm Plus',  NULL, '1004600012345', NULL, NULL, '+37322567890',         'office@agroterm.md',    '2018-02-01', 'BR001', 'MED',  'ACTIVE'),
('C00004', 'PF', 'Gheorghe Bostan',    '2003456789014', NULL, '1978-11-30', 'M', '+37360345678', NULL,                    '2010-08-15', 'BR002', 'MED',  'ACTIVE'),
('C00005', 'PF', 'Oxana Negru',        '2003456789015', NULL, '1995-04-08', 'F', '+37369456789', 'o.negru@gmail.com',     '2019-09-01', 'BR002', 'LOW',  'ACTIVE'),
('C00006', 'PJ', 'SA Vinaria Purcari', NULL, '1004600054321', NULL, NULL, '+37322678901',         'finance@purcari.md',    '2005-03-15', 'BR001', 'LOW',  'ACTIVE'),
('C00007', 'PF', 'Vitalie Ursu',       '2003456789016', NULL, '1970-01-25', 'M', '+37368567890', NULL,                    '2008-12-01', 'BR003', 'HIGH', 'ACTIVE'),
('C00008', 'PF', 'Lidia Cazacu',       '2003456789017', NULL, '1988-09-14', 'F', '+37369678901', 'l.cazacu@yahoo.com',    '2020-01-15', 'BR003', 'LOW',  'ACTIVE'),
('C00009', 'PJ', 'SRL TransLogistic',  NULL, '1004600067890', NULL, NULL, '+37322789012',         'contabil@translog.md',  '2017-06-20', 'BR004', 'MED',  'ACTIVE'),
('C00010', 'PF', 'Dorin Eni',          '2003456789018', NULL, '1965-05-03', 'M', '+37360456789', NULL,                    '2001-11-10', 'BR001', 'LOW',  'DORMANT'),  -- dormant customer
('C00011', 'PF', 'Mariana Covali',     '2003456789019', NULL, '1992-12-20', 'F', '+37369789012', 'm.covali@mail.md',      '2021-03-01', 'BR002', 'LOW',  'ACTIVE'),
('C00012', 'PJ', 'SRL PanifStar',      NULL, '1004600078901', NULL, NULL, '+37322890123',         NULL,                    '2019-07-10', 'BR006', 'HIGH', 'ACTIVE'),
('C00013', 'PF', 'Roman Gorea',        '2003456789020', NULL, '1982-06-17', 'M', '+37368678901', 'r.gorea@gmail.com',     '2014-04-25', 'BR001', 'LOW',  'ACTIVE'),
('C00014', 'PF', 'Nadejda Chiriac',    '2003456789021', NULL, '2001-08-30', 'F', '+37369890123', 'n.chiriac@mail.md',     '2023-01-10', 'BR007', 'LOW',  'ACTIVE'),
('C00015', 'PJ', 'II Florescu Ana',    NULL, '1004600089012', NULL, NULL, '+37360567890',         'ana.florescu@mail.md',  '2022-05-15', 'BR004', 'LOW',  'ACTIVE'),
('C00016', 'PF', 'Boris Revenco',      '2003456789022', NULL, '1975-10-11', 'M', '+37368789012', NULL,                    '2007-02-20', 'BR003', 'CRIT', 'BLOCKED'), -- blocked
('C00017', 'PF', 'Ecaterina Popa',     '2003456789023', NULL, '1998-03-05', 'F', '+37369901234', 'e.popa@gmail.com',      '2020-11-01', 'BR001', 'LOW',  'ACTIVE'),
('C00018', 'PJ', 'SRL AgriMold',       NULL, '1004600090123', NULL, NULL, '+37322901234',         'office@agrimold.md',    '2013-08-01', 'BR003', 'MED',  'ACTIVE'),
('C00019', 'PF', 'Serghei Platon',     '2003456789024', NULL, '1983-07-19', 'M', '+37360678901', 's.platon@yahoo.com',    '2016-10-05', 'BR002', 'MED',  'ACTIVE'),
('C00020', 'PF', 'Victoria Tautu',     '2003456789025', NULL, '2000-02-14', 'F', '+37369012345', 'v.tautu@mail.md',       '2024-06-01', 'BR001', 'LOW',  'ACTIVE');

-- Accounts (30 accounts across customers - some have multiple)
SET IDENTITY_INSERT bank.tbl_acct ON;
INSERT INTO bank.tbl_acct (acct_no, cust_no, acct_tp_cd, ccy_cd, br_cd, open_dt, close_dt, cur_bal, avail_bal, hold_amt, stat_cd, last_txn_dt) VALUES
('MD24AG000000000001MDL', 'C00001', 'CUR_PF',  'MDL', 'BR001', '2015-01-20', NULL,         45230.50,  44230.50, 1000.00, 'OPEN',    '2026-02-10'),
('MD24AG000000000002USD', 'C00001', 'CUR_USD', 'USD', 'BR001', '2018-06-15', NULL,          3250.00,   3250.00,    0.00, 'OPEN',    '2026-01-28'),
('MD24AG000000000003MDL', 'C00002', 'CUR_PF',  'MDL', 'BR001', '2016-05-10', NULL,         12780.30,  12780.30,    0.00, 'OPEN',    '2026-02-12'),
('MD24AG000000000004MDL', 'C00002', 'DEP_TRM', 'MDL', 'BR001', '2025-01-15', NULL,        100000.00, 100000.00,    0.00, 'OPEN',    '2025-01-15'),
('MD24AG000000000005MDL', 'C00003', 'CUR_PJ',  'MDL', 'BR001', '2018-02-01', NULL,        587420.15, 587420.15,    0.00, 'OPEN',    '2026-02-14'),
('MD24AG000000000006EUR', 'C00003', 'CUR_EUR', 'EUR', 'BR001', '2018-02-01', NULL,         28500.00,  28500.00,    0.00, 'OPEN',    '2026-02-05'),
('MD24AG000000000007MDL', 'C00004', 'CUR_PF',  'MDL', 'BR002', '2010-08-15', NULL,          8950.00,   8950.00,    0.00, 'OPEN',    '2026-01-30'),
('MD24AG000000000008MDL', 'C00004', 'CRD_LN',  'MDL', 'BR002', '2023-03-01', NULL,              0.00,      0.00,    0.00, 'OPEN',    '2026-02-01'),
('MD24AG000000000009MDL', 'C00005', 'CUR_PF',  'MDL', 'BR002', '2019-09-01', NULL,         22150.75,  22150.75,    0.00, 'OPEN',    '2026-02-11'),
('MD24AG000000000010MDL', 'C00005', 'SAV',     'MDL', 'BR002', '2020-06-01', NULL,         55000.00,  55000.00,    0.00, 'OPEN',    '2025-12-31'),
('MD24AG000000000011MDL', 'C00006', 'CUR_PJ',  'MDL', 'BR001', '2005-03-15', NULL,       2450000.00,2400000.00,50000.00, 'OPEN',    '2026-02-14'),
('MD24AG000000000012EUR', 'C00006', 'CUR_EUR', 'EUR', 'BR001', '2005-03-15', NULL,        185000.00, 185000.00,    0.00, 'OPEN',    '2026-02-10'),
('MD24AG000000000013USD', 'C00006', 'CUR_USD', 'USD', 'BR001', '2010-01-10', NULL,         95000.00,  95000.00,    0.00, 'OPEN',    '2026-01-15'),
('MD24AG000000000014MDL', 'C00007', 'CUR_PF',  'MDL', 'BR003', '2008-12-01', NULL,          1250.00,   1250.00,    0.00, 'FROZEN', '2025-06-15'),  -- frozen
('MD24AG000000000015MDL', 'C00008', 'CUR_PF',  'MDL', 'BR003', '2020-01-15', NULL,         18400.00,  18400.00,    0.00, 'OPEN',    '2026-02-08'),
('MD24AG000000000016MDL', 'C00009', 'CUR_PJ',  'MDL', 'BR004', '2017-06-20', NULL,        320500.00, 320500.00,    0.00, 'OPEN',    '2026-02-13'),
('MD24AG000000000017MDL', 'C00010', 'CUR_PF',  'MDL', 'BR001', '2001-11-10', NULL,           520.30,    520.30,    0.00, 'DORMANT','2020-03-15'),  -- dormant
('MD24AG000000000018MDL', 'C00011', 'CUR_PF',  'MDL', 'BR002', '2021-03-01', NULL,          9870.00,   9870.00,    0.00, 'OPEN',    '2026-02-09'),
('MD24AG000000000019MDL', 'C00012', 'CUR_PJ',  'MDL', 'BR006', '2019-07-10', NULL,        145600.00, 145600.00,    0.00, 'OPEN',    '2026-02-07'),
('MD24AG000000000020MDL', 'C00013', 'CUR_PF',  'MDL', 'BR001', '2014-04-25', NULL,         67800.00,  67800.00,    0.00, 'OPEN',    '2026-02-14'),
('MD24AG000000000021MDL', 'C00013', 'DEP_TRM', 'MDL', 'BR001', '2024-06-01', NULL,        200000.00, 200000.00,    0.00, 'OPEN',    '2024-06-01'),
('MD24AG000000000022MDL', 'C00014', 'CUR_PF',  'MDL', 'BR007', '2023-01-10', NULL,          5430.00,   5430.00,    0.00, 'OPEN',    '2026-02-03'),
('MD24AG000000000023MDL', 'C00015', 'CUR_PJ',  'MDL', 'BR004', '2022-05-15', NULL,         78900.00,  78900.00,    0.00, 'OPEN',    '2026-01-25'),
('MD24AG000000000024MDL', 'C00016', 'CUR_PF',  'MDL', 'BR003', '2007-02-20', NULL,          3200.00,      0.00, 3200.00, 'FROZEN', '2024-11-01'),  -- frozen, full hold
('MD24AG000000000025MDL', 'C00017', 'CUR_PF',  'MDL', 'BR001', '2020-11-01', NULL,         31500.00,  31500.00,    0.00, 'OPEN',    '2026-02-12'),
('MD24AG000000000026MDL', 'C00018', 'CUR_PJ',  'MDL', 'BR003', '2013-08-01', NULL,        890000.00, 890000.00,    0.00, 'OPEN',    '2026-02-14'),
('MD24AG000000000027EUR', 'C00018', 'CUR_EUR', 'EUR', 'BR003', '2015-04-10', NULL,         42000.00,  42000.00,    0.00, 'OPEN',    '2026-01-20'),
('MD24AG000000000028MDL', 'C00019', 'CUR_PF',  'MDL', 'BR002', '2016-10-05', NULL,         15600.00,  15600.00,    0.00, 'OPEN',    '2026-02-06'),
('MD24AG000000000029MDL', 'C00019', 'CRD_LN',  'MDL', 'BR002', '2024-01-10', NULL,              0.00,      0.00,    0.00, 'OPEN',    '2026-02-01'),
('MD24AG000000000030MDL', 'C00020', 'CUR_PF',  'MDL', 'BR001', '2024-06-01', NULL,          2100.00,   2100.00,    0.00, 'OPEN',    '2026-01-30');

-- Loan products
SET IDENTITY_INSERT bank.tbl_loan_prod ON;
INSERT INTO bank.tbl_loan_prod (prod_cd, prod_nm, prod_categ, min_amt, max_amt, min_term_mo, max_term_mo, base_rate, is_active) VALUES
('MORT_STD',  'Ipoteca Standard',      'MORTGAGE', 200000.00,  5000000.00,  60, 300, 9.50, 1),
('MORT_PRM',  'Ipoteca Prima Casa',    'MORTGAGE', 100000.00,  2000000.00,  60, 240, 7.00, 1),
('CONS_STD',  'Credit Consum',         'CONSUMER',   5000.00,   300000.00,   6,  84, 14.50, 1),
('CONS_SAL',  'Credit Salarial',       'CONSUMER',   1000.00,   100000.00,   3,  60, 12.00, 1),
('AUTO_NEW',  'Credit Auto Nou',       'AUTO',      50000.00,  1500000.00,  12,  84, 10.50, 1),
('AUTO_SH',   'Credit Auto SH',        'AUTO',      30000.00,   800000.00,  12,  60, 13.00, 1),
('BIZ_INV',   'Credit Investitional',  'BUSINESS', 100000.00, 20000000.00,  12, 120, 11.00, 1),
('BIZ_WC',    'Credit Capital Circ.',  'BUSINESS',  50000.00, 10000000.00,   3,  36, 12.50, 1),
('BIZ_AGRO',  'Credit Agricol',        'BUSINESS', 100000.00, 15000000.00,  12,  84,  9.00, 1),
('OVERDRAFT', 'Overdraft',             'CONSUMER',   5000.00,   200000.00,   1,  12, 16.00, 1);

-- Loans (12 loans - mix of statuses, some overdue, one NPL)
SET IDENTITY_INSERT bank.tbl_loan ON;
INSERT INTO bank.tbl_loan (loan_no, cust_no, prod_cd, disb_acct_no, repay_acct_no, appl_dt, appr_dt, disb_dt, mat_dt, loan_amt, ccy_cd, int_rate, term_mo, outst_princ, outst_int, overdue_amt, overdue_days, npl_flag, br_cd, loan_off_emp_no, stat_cd) VALUES
('LN-2023-00001', 'C00001', 'MORT_PRM',  'MD24AG000000000001MDL', 'MD24AG000000000001MDL', '2023-01-10', '2023-01-25', '2023-02-01', '2043-02-01', 1200000.00, 'MDL', 7.25, 240, 1125000.00, 4500.00, 0.00, 0, 'N', 'BR001', 'E002', 'ACTIVE'),
('LN-2023-00002', 'C00004', 'CONS_STD',   'MD24AG000000000008MDL', 'MD24AG000000000007MDL', '2023-02-15', '2023-02-20', '2023-03-01', '2028-03-01', 150000.00,  'MDL', 14.50, 60,  98000.00, 1200.00, 0.00, 0, 'N', 'BR002', 'E006', 'ACTIVE'),
('LN-2022-00003', 'C00003', 'BIZ_INV',    'MD24AG000000000005MDL', 'MD24AG000000000005MDL', '2022-05-01', '2022-05-20', '2022-06-01', '2029-06-01', 5000000.00, 'MDL', 11.00, 84,  3200000.00, 28000.00, 0.00, 0, 'N', 'BR001', 'E002', 'ACTIVE'),
('LN-2024-00004', 'C00005', 'CONS_SAL',   'MD24AG000000000009MDL', 'MD24AG000000000009MDL', '2024-03-01', '2024-03-05', '2024-03-10', '2027-03-10', 50000.00,   'MDL', 12.00, 36,   35000.00,   350.00, 0.00, 0, 'N', 'BR002', 'E006', 'ACTIVE'),
('LN-2024-00005', 'C00013', 'AUTO_NEW',   'MD24AG000000000020MDL', 'MD24AG000000000020MDL', '2024-06-01', '2024-06-10', '2024-06-15', '2030-06-15', 450000.00,  'MDL', 10.50, 72,  390000.00, 3400.00, 0.00, 0, 'N', 'BR001', 'E003', 'ACTIVE'),
('LN-2021-00006', 'C00007', 'CONS_STD',   'MD24AG000000000014MDL', 'MD24AG000000000014MDL', '2021-01-15', '2021-01-20', '2021-02-01', '2026-02-01', 200000.00,  'MDL', 14.50, 60,   45000.00, 8500.00, 22000.00, 95, 'Y', 'BR003', 'E011', 'ACTIVE'),  -- NPL!
('LN-2019-00007', 'C00006', 'BIZ_WC',     'MD24AG000000000011MDL', 'MD24AG000000000011MDL', '2019-09-01', '2019-09-10', '2019-09-15', '2022-09-15', 3000000.00, 'MDL', 12.50, 36,        0.00,     0.00, 0.00, 0, 'N', 'BR001', 'E002', 'CLOSED'),
('LN-2023-00008', 'C00009', 'BIZ_AGRO',   'MD24AG000000000016MDL', 'MD24AG000000000016MDL', '2023-04-01', '2023-04-15', '2023-05-01', '2028-05-01', 2500000.00, 'MDL', 9.00,  60,  1800000.00, 13500.00, 0.00, 0, 'N', 'BR004', 'E016', 'ACTIVE'),
('LN-2024-00009', 'C00019', 'CONS_STD',   'MD24AG000000000029MDL', 'MD24AG000000000028MDL', '2024-01-05', '2024-01-10', '2024-01-15', '2029-01-15', 180000.00,  'MDL', 14.50, 60,  155000.00,  1900.00, 4500.00, 32, 'N', 'BR002', 'E006', 'ACTIVE'),  -- overdue but not NPL
('LN-2024-00010', 'C00012', 'BIZ_INV',    'MD24AG000000000019MDL', 'MD24AG000000000019MDL', '2024-08-01', '2024-08-20', '2024-09-01', '2031-09-01', 3500000.00, 'MDL', 11.00, 84,  3200000.00, 29000.00, 0.00, 0, 'N', 'BR006', 'E021', 'ACTIVE'),
('LN-2025-00011', 'C00018', 'BIZ_AGRO',   'MD24AG000000000026MDL', 'MD24AG000000000026MDL', '2025-01-10', '2025-01-25', '2025-02-01', '2030-02-01', 8000000.00, 'MDL', 9.00,  60,  7800000.00, 58500.00, 0.00, 0, 'N', 'BR003', 'E011', 'ACTIVE'),
('LN-2020-00012', 'C00016', 'CONS_STD',   'MD24AG000000000024MDL', 'MD24AG000000000024MDL', '2020-06-01', '2020-06-05', '2020-06-15', '2025-06-15', 100000.00,  'MDL', 15.00, 60,   32000.00, 12000.00, 44000.00, 180, 'Y', 'BR003', 'E011', 'ACTIVE');  -- NPL, account frozen

-- Sample transactions (50 transactions for testing)
SET IDENTITY_INSERT bank.tbl_txn ON;
INSERT INTO bank.tbl_txn (acct_no, txn_tp_cd, txn_dt, val_dt, txn_amt, ccy_cd, dr_cr_ind, bal_after, ref_no, cntrp_acct_no, cntrp_nm, descr, channel_cd, auth_emp_no, stat_cd) VALUES
('MD24AG000000000001MDL', 'DEP_CSH',  '2026-02-01', '2026-02-01', 15000.00,  'MDL', 'C', 40230.50, 'REF2026020101', NULL, NULL, 'Depunere salariu', 'BRANCH', 'E004', 'POST'),
('MD24AG000000000001MDL', 'PMT_LN',   '2026-02-01', '2026-02-01',  6200.00,  'MDL', 'D', 34030.50, 'REF2026020102', 'MD24AG000000000001MDL', 'MAIB Credit', 'Plata rata credit ipotecar LN-2023-00001', 'WEB', NULL, 'POST'),
('MD24AG000000000001MDL', 'POS',       '2026-02-03', '2026-02-03',   450.00,  'MDL', 'D', 33580.50, 'REF2026020301', NULL, 'Nr.1 SRL', 'Cumparaturi alimentare', 'POS', NULL, 'POST'),
('MD24AG000000000001MDL', 'TRF_INT',  '2026-02-05', '2026-02-05',  2000.00,  'MDL', 'D', 31580.50, 'REF2026020501', 'MD24AG000000000002USD', 'Petru Costin', 'Transfer in cont USD', 'MOBILE', NULL, 'POST'),
('MD24AG000000000001MDL', 'FEE',       '2026-02-05', '2026-02-05',    50.00,  'MDL', 'D', 31530.50, 'REF2026020502', NULL, 'MAIB', 'Comision transfer valutar', 'MOBILE', NULL, 'POST'),
('MD24AG000000000001MDL', 'TRF_IN',   '2026-02-10', '2026-02-10', 13700.00,  'MDL', 'C', 45230.50, 'REF2026021001', 'MD99XX000000999999', 'Compania ABC SRL', 'Salariu februarie 2026', 'WEB', NULL, 'POST'),
('MD24AG000000000003MDL', 'DEP_CSH',  '2026-01-15', '2026-01-15',  5000.00,  'MDL', 'C', 10780.30, 'REF2026011501', NULL, NULL, 'Depunere economii', 'BRANCH', 'E004', 'POST'),
('MD24AG000000000003MDL', 'ATM_WDR',  '2026-01-20', '2026-01-20',  2000.00,  'MDL', 'D',  8780.30, 'REF2026012001', NULL, NULL, 'Retragere ATM Stefan cel Mare', 'ATM', NULL, 'POST'),
('MD24AG000000000003MDL', 'POS',       '2026-02-01', '2026-02-01',   780.00,  'MDL', 'D',  8000.30, 'REF2026020103', NULL, 'Farmacia Felicia', 'Medicamente', 'POS', NULL, 'POST'),
('MD24AG000000000003MDL', 'TRF_IN',   '2026-02-12', '2026-02-12',  4780.00,  'MDL', 'C', 12780.30, 'REF2026021201', 'MD99XX000000888888', 'Min. Educatiei', 'Salariu profesor', 'WEB', NULL, 'POST'),
('MD24AG000000000005MDL', 'TRF_IN',   '2026-02-01', '2026-02-01',250000.00,  'MDL', 'C', 487420.15,'REF2026020104', 'MD99XX000000777777', 'Metro Cash&Carry', 'Plata factura F-2026-0145', 'WEB', NULL, 'POST'),
('MD24AG000000000005MDL', 'TRF_EXT',  '2026-02-05', '2026-02-07', 85000.00,  'MDL', 'D', 402420.15,'REF2026020503', 'MD24VB000000123456', 'Furnizor Import SRL', 'Plata factura import piese', 'WEB', NULL, 'POST'),
('MD24AG000000000005MDL', 'FEE',       '2026-02-05', '2026-02-05',   350.00,  'MDL', 'D', 402070.15,'REF2026020504', NULL, 'MAIB', 'Comision transfer extern', 'WEB', NULL, 'POST'),
('MD24AG000000000005MDL', 'PMT_LN',   '2026-02-10', '2026-02-10', 95000.00,  'MDL', 'D', 307070.15,'REF2026021002', 'MD24AG000000000005MDL', 'MAIB Credit', 'Rata credit investitional LN-2022-00003', 'WEB', NULL, 'POST'),
('MD24AG000000000005MDL', 'TRF_IN',   '2026-02-14', '2026-02-14',280350.00,  'MDL', 'C', 587420.15,'REF2026021401', 'MD99XX000000666666', 'Agropiese SRL', 'Incasare factura F-2026-0203', 'WEB', NULL, 'POST'),
('MD24AG000000000011MDL', 'TRF_IN',   '2026-02-01', '2026-02-01',850000.00,  'MDL', 'C',2300000.00,'REF2026020105', 'MD99XX000000555555', 'Duty Free Moldova', 'Vanzari export lot 2026-02', 'WEB', NULL, 'POST'),
('MD24AG000000000011MDL', 'TRF_EXT',  '2026-02-03', '2026-02-05',200000.00,  'MDL', 'D',2100000.00,'REF2026020302', 'RO49AAAA1B31007593840000', 'Viticol Romania SRL', 'Achizitie sticle import', 'WEB', NULL, 'POST'),
('MD24AG000000000011MDL', 'FEE',       '2026-02-03', '2026-02-03',  1500.00,  'MDL', 'D',2098500.00,'REF2026020303', NULL, 'MAIB', 'Comision transfer international', 'WEB', NULL, 'POST'),
('MD24AG000000000011MDL', 'TRF_IN',   '2026-02-10', '2026-02-10',320000.00,  'MDL', 'C',2418500.00,'REF2026021003', 'MD99XX000000444444', 'HoReCa Plus SRL', 'Contract furnizare vin 2026', 'WEB', NULL, 'POST'),
('MD24AG000000000011MDL', 'FEE',       '2026-02-14', '2026-02-14', 31500.00,  'MDL', 'D',2387000.00,'REF2026021402', NULL, 'MAIB', 'Comision administrare cont PJ T1 2026', 'WEB', NULL, 'POST'),
('MD24AG000000000011MDL', 'TRF_IN',   '2026-02-14', '2026-02-14', 63000.00,  'MDL', 'C',2450000.00,'REF2026021403', 'MD99XX000000333333', 'Magazin Nr.5 SRL', 'Factura vin retail ianuarie', 'WEB', NULL, 'POST'),
('MD24AG000000000007MDL', 'DEP_CSH',  '2026-01-15', '2026-01-15',  8000.00,  'MDL', 'C',  8950.00, 'REF2026011502', NULL, NULL, 'Depunere numerar', 'BRANCH', 'E007', 'POST'),
('MD24AG000000000007MDL', 'PMT_LN',   '2026-01-30', '2026-01-30',  3500.00,  'MDL', 'D',  5450.00, 'REF2026013001', 'MD24AG000000000008MDL', 'MAIB Credit', 'Plata rata credit LN-2023-00002', 'BRANCH', 'E007', 'POST'),
('MD24AG000000000007MDL', 'TRF_IN',   '2026-01-30', '2026-01-30',  3500.00,  'MDL', 'C',  8950.00, 'REF2026013002', 'MD99XX000000222222', 'Fabrica Speranța SRL', 'Salariu', 'WEB', NULL, 'POST'),
('MD24AG000000000009MDL', 'TRF_IN',   '2026-02-05', '2026-02-05', 14000.00,  'MDL', 'C', 20150.75, 'REF2026020505', 'MD99XX000000111111', 'IT Solutions SRL', 'Salariu IT consultant', 'WEB', NULL, 'POST'),
('MD24AG000000000009MDL', 'POS',       '2026-02-08', '2026-02-08',  1200.00,  'MDL', 'D', 18950.75, 'REF2026020801', NULL, 'Zara Moldova', 'Imbracaminte', 'POS', NULL, 'POST'),
('MD24AG000000000009MDL', 'ATM_WDR',  '2026-02-10', '2026-02-10',  3000.00,  'MDL', 'D', 15950.75, 'REF2026021004', NULL, NULL, 'ATM Botanica', 'ATM', NULL, 'POST'),
('MD24AG000000000009MDL', 'PMT_LN',   '2026-02-11', '2026-02-11',  1800.00,  'MDL', 'D', 14150.75, 'REF2026021101', 'MD24AG000000000009MDL', 'MAIB Credit', 'Rata credit salarial LN-2024-00004', 'MOBILE', NULL, 'POST'),
('MD24AG000000000009MDL', 'TRF_IN',   '2026-02-11', '2026-02-11',  8000.00,  'MDL', 'C', 22150.75, 'REF2026021102', 'MD24AG000000000010MDL', 'Oxana Negru', 'Transfer din cont economii', 'MOBILE', NULL, 'POST'),
('MD24AG000000000015MDL', 'TRF_IN',   '2026-02-01', '2026-02-01', 12000.00,  'MDL', 'C', 16400.00, 'REF2026020106', 'MD99XX000000999888', 'Universitatea de Stat', 'Salariu lector universitar', 'WEB', NULL, 'POST'),
('MD24AG000000000015MDL', 'POS',       '2026-02-04', '2026-02-04',   350.00,  'MDL', 'D', 16050.00, 'REF2026020401', NULL, 'Linella SRL', 'Cumparaturi', 'POS', NULL, 'POST'),
('MD24AG000000000015MDL', 'TRF_EXT',  '2026-02-08', '2026-02-10',  2000.00,  'MDL', 'D', 14050.00, 'REF2026020802', 'RO49BCCC1C31007593840000', 'Elefant.ro', 'Comanda online carti', 'MOBILE', NULL, 'POST'),
('MD24AG000000000015MDL', 'TRF_IN',   '2026-02-08', '2026-02-08',  4350.00,  'MDL', 'C', 18400.00, 'REF2026020803', 'MD24AG000000000015MDL', 'Lidia Cazacu', 'Restituire imprumut personal', 'MOBILE', NULL, 'POST'),
('MD24AG000000000016MDL', 'TRF_IN',   '2026-02-01', '2026-02-01',180000.00,  'MDL', 'C', 280500.00,'REF2026020107', 'MD99XX000000777666', 'Fermierii Cahul SA', 'Plata servicii transport', 'WEB', NULL, 'POST'),
('MD24AG000000000016MDL', 'PMT_LN',   '2026-02-05', '2026-02-05', 55000.00,  'MDL', 'D', 225500.00,'REF2026020506', 'MD24AG000000000016MDL', 'MAIB Credit', 'Rata credit agricol LN-2023-00008', 'WEB', NULL, 'POST'),
('MD24AG000000000016MDL', 'TRF_EXT',  '2026-02-10', '2026-02-12', 45000.00,  'MDL', 'D', 180500.00,'REF2026021005', 'MD24VB000000654321', 'Carburanti Plus SRL', 'Achizitie motorina', 'WEB', NULL, 'POST'),
('MD24AG000000000016MDL', 'TRF_IN',   '2026-02-13', '2026-02-13',140000.00,  'MDL', 'C', 320500.00,'REF2026021301', 'MD99XX000000888777', 'Cereale Moldova SA', 'Vanzare recolta porumb', 'WEB', NULL, 'POST'),
('MD24AG000000000020MDL', 'TRF_IN',   '2026-02-01', '2026-02-01', 25000.00,  'MDL', 'C', 52800.00, 'REF2026020108', 'MD99XX000000111222', 'Employer SRL', 'Salariu luna ianuarie', 'WEB', NULL, 'POST'),
('MD24AG000000000020MDL', 'PMT_LN',   '2026-02-01', '2026-02-01',  8500.00,  'MDL', 'D', 44300.00, 'REF2026020109', 'MD24AG000000000020MDL', 'MAIB Credit', 'Rata credit auto LN-2024-00005', 'WEB', NULL, 'POST'),
('MD24AG000000000020MDL', 'POS',       '2026-02-07', '2026-02-07',  1500.00,  'MDL', 'D', 42800.00, 'REF2026020701', NULL, 'Supraten SRL', 'Materiale constructii', 'POS', NULL, 'POST'),
('MD24AG000000000020MDL', 'TRF_INT',  '2026-02-10', '2026-02-10',  5000.00,  'MDL', 'D', 37800.00, 'REF2026021006', 'MD24AG000000000021MDL', 'Roman Gorea', 'Alimentare depozit', 'MOBILE', NULL, 'POST'),
('MD24AG000000000020MDL', 'TRF_IN',   '2026-02-14', '2026-02-14', 30000.00,  'MDL', 'C', 67800.00, 'REF2026021404', 'MD99XX000000111222', 'Employer SRL', 'Bonus anual 2025', 'WEB', NULL, 'POST'),
('MD24AG000000000018MDL', 'TRF_IN',   '2026-02-05', '2026-02-05',  9000.00,  'MDL', 'C',  8870.00, 'REF2026020507', 'MD99XX000000333222', 'Retail Corp SRL', 'Salariu consultant', 'WEB', NULL, 'POST'),
('MD24AG000000000018MDL', 'POS',       '2026-02-07', '2026-02-07',   500.00,  'MDL', 'D',  8370.00, 'REF2026020702', NULL, 'Kaufland Moldova', 'Alimentare', 'POS', NULL, 'POST'),
('MD24AG000000000018MDL', 'ATM_WDR',  '2026-02-09', '2026-02-09',  1500.00,  'MDL', 'D',  6870.00, 'REF2026020901', NULL, NULL, 'ATM Ciocana', 'ATM', NULL, 'POST'),
('MD24AG000000000018MDL', 'DEP_CSH',  '2026-02-09', '2026-02-09',  3000.00,  'MDL', 'C',  9870.00, 'REF2026020902', NULL, NULL, 'Depunere numerar', 'BRANCH', 'E007', 'POST'),
('MD24AG000000000025MDL', 'TRF_IN',   '2026-02-05', '2026-02-05', 18000.00,  'MDL', 'C', 29500.00, 'REF2026020508', 'MD99XX000000444333', 'Design Studio SRL', 'Salariu designer', 'WEB', NULL, 'POST'),
('MD24AG000000000025MDL', 'POS',       '2026-02-08', '2026-02-08',  2500.00,  'MDL', 'D', 27000.00, 'REF2026020804', NULL, 'IKEA Online', 'Mobilier apartament', 'POS', NULL, 'POST'),
('MD24AG000000000025MDL', 'TRF_INT',  '2026-02-12', '2026-02-12',  4500.00,  'MDL', 'C', 31500.00, 'REF2026021202', 'MD24AG000000000003MDL', 'Alina Dumbraveanu', 'Rambursare datorie', 'MOBILE', NULL, 'POST'),
('MD24AG000000000026MDL', 'TRF_IN',   '2026-02-01', '2026-02-01',450000.00,  'MDL', 'C', 790000.00,'REF2026020110', 'MD99XX000000555444', 'Cereale Balti SA', 'Vanzare seminte', 'WEB', NULL, 'POST'),
('MD24AG000000000026MDL', 'PMT_LN',   '2026-02-05', '2026-02-05',150000.00,  'MDL', 'D', 640000.00,'REF2026020509', 'MD24AG000000000026MDL', 'MAIB Credit', 'Rata credit agricol LN-2025-00011', 'WEB', NULL, 'POST'),
('MD24AG000000000026MDL', 'TRF_IN',   '2026-02-14', '2026-02-14',250000.00,  'MDL', 'C', 890000.00,'REF2026021405', 'MD99XX000000666555', 'AgriExport Moldova', 'Livrare cereale contract C-2026-01', 'WEB', NULL, 'POST');

-- Cards (10 cards)
SET IDENTITY_INSERT bank.tbl_card ON;
INSERT INTO bank.tbl_card (card_no_hash, acct_no, cust_no, card_tp, card_brand, issue_dt, exp_dt, lim_amt, stat_cd) VALUES
('a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2', 'MD24AG000000000001MDL', 'C00001', 'DEBIT', 'VISA',       '2024-01-15', '2027-01-15', NULL, 'ACTIVE'),
('b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3', 'MD24AG000000000001MDL', 'C00001', 'CREDIT','VISA',       '2023-06-01', '2026-06-01', 50000.00, 'ACTIVE'),
('c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4', 'MD24AG000000000003MDL', 'C00002', 'DEBIT', 'MASTERCARD', '2024-05-10', '2027-05-10', NULL, 'ACTIVE'),
('d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5', 'MD24AG000000000005MDL', 'C00003', 'DEBIT', 'VISA',       '2023-02-01', '2026-02-01', NULL, 'EXPIRED'),  -- expired
('e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6', 'MD24AG000000000007MDL', 'C00004', 'DEBIT', 'MASTERCARD', '2025-01-01', '2028-01-01', NULL, 'ACTIVE'),
('f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1', 'MD24AG000000000009MDL', 'C00005', 'DEBIT', 'VISA',       '2024-09-01', '2027-09-01', NULL, 'ACTIVE'),
('a1a2a3a4a5a6a1a2a3a4a5a6a1a2a3a4a5a6a1a2a3a4a5a6a1a2a3a4a5a6a1a2', 'MD24AG000000000009MDL', 'C00005', 'CREDIT','MASTERCARD', '2024-09-01', '2027-09-01', 30000.00, 'ACTIVE'),
('b1b2b3b4b5b6b1b2b3b4b5b6b1b2b3b4b5b6b1b2b3b4b5b6b1b2b3b4b5b6b1b2', 'MD24AG000000000014MDL', 'C00007', 'DEBIT', 'MASTERCARD', '2022-06-15', '2025-06-15', NULL, 'BLOCKED'),  -- blocked with account
('c1c2c3c4c5c6c1c2c3c4c5c6c1c2c3c4c5c6c1c2c3c4c5c6c1c2c3c4c5c6c1c2', 'MD24AG000000000020MDL', 'C00013', 'DEBIT', 'VISA',       '2025-04-01', '2028-04-01', NULL, 'ACTIVE'),
('d1d2d3d4d5d6d1d2d3d4d5d6d1d2d3d4d5d6d1d2d3d4d5d6d1d2d3d4d5d6d1d2', 'MD24AG000000000025MDL', 'C00017', 'DEBIT', 'VISA',       '2024-11-01', '2027-11-01', NULL, 'ACTIVE');

-- Collateral
SET IDENTITY_INSERT bank.tbl_coll ON;
INSERT INTO bank.tbl_coll (loan_no, coll_tp, coll_desc, appraisal_val, appraisal_dt, ccy_cd, stat_cd) VALUES
('LN-2023-00001', 'REAL_ESTATE', 'Apartament 3 camere, Chisinau, Botanica, 75mp', 1800000.00, '2023-01-15', 'MDL', 'ACTIVE'),
('LN-2022-00003', 'EQUIPMENT',   'Linie productie piese auto, an fabric. 2021',   3500000.00, '2022-05-10', 'MDL', 'ACTIVE'),
('LN-2022-00003', 'REAL_ESTATE', 'Hala industriala Chisinau, 500mp',              6000000.00, '2022-05-10', 'MDL', 'ACTIVE'),
('LN-2024-00005', 'VEHICLE',     'Toyota Camry 2024, VIN: JT2BF22K2W0123456',      520000.00, '2024-06-05', 'MDL', 'ACTIVE'),
('LN-2023-00008', 'REAL_ESTATE', 'Teren agricol 50ha, r-ul Cahul',               3000000.00, '2023-04-10', 'MDL', 'ACTIVE'),
('LN-2023-00008', 'EQUIPMENT',   'Combina agricola John Deere S780, an 2022',      2200000.00, '2023-04-10', 'MDL', 'ACTIVE'),
('LN-2024-00010', 'REAL_ESTATE', 'Depozit frigorific Orhei, 300mp',               2800000.00, '2024-08-10', 'MDL', 'ACTIVE'),
('LN-2025-00011', 'REAL_ESTATE', 'Teren agricol 120ha, r-ul Balti',              10000000.00, '2025-01-15', 'MDL', 'ACTIVE'),
('LN-2025-00011', 'EQUIPMENT',   'Parc utilaje agricole (3 tractoare, 2 combine)', 5500000.00, '2025-01-15', 'MDL', 'ACTIVE');

-- Guarantors
SET IDENTITY_INSERT bank.tbl_guar ON;
INSERT INTO bank.tbl_guar (loan_no, guar_cust_no, guar_nm, guar_idnp, guar_tp, guar_amt, stat_cd) VALUES
('LN-2023-00001', 'C00002', 'Alina Dumbraveanu',  '2003456789013', 'PF', 1200000.00, 'ACTIVE'),
('LN-2023-00002', NULL,      'Vasile Bostan',       '2003456780001', 'PF',  150000.00, 'ACTIVE'),
('LN-2022-00003', 'C00013', 'Roman Gorea',         '2003456789020', 'PF', 2000000.00, 'ACTIVE'),
('LN-2024-00009', NULL,      'Marina Platon',       '2003456780002', 'PF',  180000.00, 'ACTIVE'),
('LN-2024-00010', 'C00018', 'SRL AgriMold',        NULL,             'PJ', 3500000.00, 'ACTIVE');

-- FX Rates (last 5 days)
SET IDENTITY_INSERT bank.tbl_fx_rate ON;
INSERT INTO bank.tbl_fx_rate (rate_dt, ccy_from, ccy_to, buy_rate, sell_rate, bnm_rate) VALUES
('2026-02-10', 'USD', 'MDL', 17.65, 17.85, 17.75),
('2026-02-10', 'EUR', 'MDL', 19.20, 19.45, 19.32),
('2026-02-10', 'RON', 'MDL',  3.85,  3.95,  3.90),
('2026-02-11', 'USD', 'MDL', 17.60, 17.80, 17.70),
('2026-02-11', 'EUR', 'MDL', 19.15, 19.40, 19.28),
('2026-02-11', 'RON', 'MDL',  3.83,  3.93,  3.88),
('2026-02-12', 'USD', 'MDL', 17.70, 17.90, 17.80),
('2026-02-12', 'EUR', 'MDL', 19.25, 19.50, 19.38),
('2026-02-12', 'RON', 'MDL',  3.87,  3.97,  3.92),
('2026-02-13', 'USD', 'MDL', 17.68, 17.88, 17.78),
('2026-02-13', 'EUR', 'MDL', 19.22, 19.47, 19.35),
('2026-02-13', 'RON', 'MDL',  3.86,  3.96,  3.91),
('2026-02-14', 'USD', 'MDL', 17.72, 17.92, 17.82),
('2026-02-14', 'EUR', 'MDL', 19.28, 19.53, 19.40),
('2026-02-14', 'RON', 'MDL',  3.88,  3.98,  3.93);

-- Customer addresses (sample)
SET IDENTITY_INSERT bank.tbl_cust_addr ON;
INSERT INTO bank.tbl_cust_addr (cust_no, addr_tp, addr_line1, addr_line2, city, region, postal_cd, country_cd, is_primary) VALUES
('C00001', 'HOME', 'Str. Alba Iulia 75', 'ap. 42',  'Chisinau', 'Chisinau', 'MD-2051', 'MDA', 1),
('C00001', 'WORK', 'Bd. Stefan cel Mare 180', NULL,  'Chisinau', 'Chisinau', 'MD-2004', 'MDA', 0),
('C00002', 'HOME', 'Str. Ismail 48', 'ap. 15',      'Chisinau', 'Chisinau', 'MD-2001', 'MDA', 1),
('C00003', 'REG',  'Str. Industriala 22', NULL,       'Chisinau', 'Chisinau', 'MD-2023', 'MDA', 1),
('C00004', 'HOME', 'Str. Decebal 120', 'ap. 8',     'Chisinau', 'Chisinau', 'MD-2060', 'MDA', 1),
('C00005', 'HOME', 'Str. Grenoble 128', 'ap. 33',   'Chisinau', 'Chisinau', 'MD-2019', 'MDA', 1),
('C00006', 'REG',  'Sat. Purcari, com. Stefan Voda', NULL, 'Stefan Voda', 'Stefan Voda', 'MD-4201', 'MDA', 1),
('C00007', 'HOME', 'Str. Independentei 88', 'ap. 5', 'Balti',   'Balti',    'MD-3100', 'MDA', 1),
('C00013', 'HOME', 'Str. Bucuresti 55', 'ap. 21',   'Chisinau', 'Chisinau', 'MD-2012', 'MDA', 1),
('C00014', 'HOME', 'Str. Pobedei 15', NULL,          'Comrat',   'Gagauzia',  'MD-3805', 'MDA', 1);