-- ============================================================
-- SYNTHETIC BANK DATABASE - Mimics MAIB SQL Server reality
-- Design principles:
--   1. Cryptic column names 
--   2. NO foreign key constraints 
--   3. Mixed naming conventions 
--   4. Status codes as integers and strings 
-- ============================================================

-- Schema: bank (separates synthetic data from app metadata)
CREATE SCHEMA IF NOT EXISTS bank;

-- -----------------------------------------------------------
-- 1. tbl_br - Branch / Office registry
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_br (
    br_cd           VARCHAR(10)     PRIMARY KEY,
    br_nm           VARCHAR(100)    NOT NULL,
    br_addr         VARCHAR(200),
    br_city         VARCHAR(50),
    br_region       VARCHAR(50),
    br_mgr_emp_no   VARCHAR(20),         -- logical FK to tbl_emp
    open_dt         DATE,
    stat_cd         INTEGER         DEFAULT 1,  -- 1=active, 0=closed
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 2. tbl_emp - Bank employees
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_emp (
    emp_no          VARCHAR(20)     PRIMARY KEY,
    emp_nm          VARCHAR(100)    NOT NULL,
    emp_surnm       VARCHAR(100)    NOT NULL,
    emp_pos         VARCHAR(80),          -- job title
    br_cd           VARCHAR(10),          -- logical FK to tbl_br
    dept_cd         VARCHAR(20),
    hire_dt         DATE,
    term_dt         DATE,                 -- NULL if still employed
    mgr_emp_no      VARCHAR(20),          -- logical FK to self (manager)
    sal_amt         NUMERIC(12,2),
    stat_cd         INTEGER         DEFAULT 1,
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 3. tbl_cust - Customers (individuals and legal entities)
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_cust (
    cust_no         VARCHAR(20)     PRIMARY KEY,
    cust_tp         VARCHAR(5)      NOT NULL,   -- 'PF' = person, 'PJ' = company
    cust_nm         VARCHAR(150)    NOT NULL,    -- full name or company name
    idnp            VARCHAR(20),                 -- national ID (IDNP for Moldova)
    idno            VARCHAR(20),                 -- company reg number
    birth_dt        DATE,
    gender_cd       CHAR(1),                     -- M/F/NULL
    phone_no        VARCHAR(20),
    email_addr      VARCHAR(100),
    reg_dt          DATE            NOT NULL,
    br_cd           VARCHAR(10),                 -- home branch, logical FK
    risk_categ      VARCHAR(10),                 -- LOW/MED/HIGH/CRIT
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE', -- string status here (inconsistent with tbl_br!)
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 4. tbl_cust_addr - Customer addresses (multiple per customer)
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_cust_addr (
    addr_id         SERIAL          PRIMARY KEY,
    cust_no         VARCHAR(20)     NOT NULL,     -- logical FK to tbl_cust
    addr_tp         VARCHAR(10)     NOT NULL,     -- 'HOME','WORK','REG','CORR'
    addr_line1      VARCHAR(200),
    addr_line2      VARCHAR(200),
    city            VARCHAR(50),
    region          VARCHAR(50),
    postal_cd       VARCHAR(10),
    country_cd      CHAR(3)         DEFAULT 'MDA',
    is_primary      BOOLEAN         DEFAULT FALSE,
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 5. tbl_acct_tp - Account type reference table
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_acct_tp (
    acct_tp_cd      VARCHAR(10)     PRIMARY KEY,
    acct_tp_nm      VARCHAR(80)     NOT NULL,
    acct_tp_desc    VARCHAR(200),
    ccy_cd          CHAR(3),                      -- default currency
    is_active       BOOLEAN         DEFAULT TRUE
);

-- -----------------------------------------------------------
-- 6. tbl_acct - Bank accounts
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_acct (
    acct_no         VARCHAR(30)     PRIMARY KEY,   -- IBAN or internal number
    cust_no         VARCHAR(20)     NOT NULL,       -- logical FK to tbl_cust
    acct_tp_cd      VARCHAR(10)     NOT NULL,       -- logical FK to tbl_acct_tp
    ccy_cd          CHAR(3)         NOT NULL,       -- MDL, USD, EUR, RON
    br_cd           VARCHAR(10),                    -- logical FK to tbl_br
    open_dt         DATE            NOT NULL,
    close_dt        DATE,
    cur_bal         NUMERIC(18,2)   DEFAULT 0,
    avail_bal       NUMERIC(18,2)   DEFAULT 0,
    hold_amt        NUMERIC(18,2)   DEFAULT 0,
    stat_cd         VARCHAR(10)     DEFAULT 'OPEN', -- OPEN/FROZEN/CLOSED/DORMANT
    last_txn_dt     DATE,
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 7. tbl_txn_tp - Transaction type reference
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_txn_tp (
    txn_tp_cd       VARCHAR(10)     PRIMARY KEY,
    txn_tp_nm       VARCHAR(80)     NOT NULL,
    txn_tp_desc     VARCHAR(200),
    dr_cr_ind       CHAR(1)         NOT NULL,       -- 'D'=debit, 'C'=credit
    is_active       BOOLEAN         DEFAULT TRUE
);

-- -----------------------------------------------------------
-- 8. tbl_txn - Transactions (the big table)
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_txn (
    txn_id          BIGSERIAL       PRIMARY KEY,
    acct_no         VARCHAR(30)     NOT NULL,       -- logical FK to tbl_acct
    txn_tp_cd       VARCHAR(10)     NOT NULL,       -- logical FK to tbl_txn_tp
    txn_dt          DATE            NOT NULL,
    val_dt          DATE,                           -- value date (settlement)
    txn_amt         NUMERIC(18,2)   NOT NULL,
    ccy_cd          CHAR(3)         NOT NULL,
    dr_cr_ind       CHAR(1)         NOT NULL,       -- D or C
    bal_after        NUMERIC(18,2),
    ref_no          VARCHAR(50),                    -- bank reference
    cntrp_acct_no   VARCHAR(30),                    -- counterparty account
    cntrp_nm        VARCHAR(150),                   -- counterparty name
    descr           VARCHAR(500),                   -- payment description
    channel_cd      VARCHAR(10),                    -- ATM/BRANCH/MOBILE/WEB
    auth_emp_no     VARCHAR(20),                    -- logical FK to tbl_emp
    stat_cd         VARCHAR(10)     DEFAULT 'POST', -- PEND/POST/REV/FAIL
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 9. tbl_loan_prod - Loan product catalog
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_loan_prod (
    prod_cd         VARCHAR(20)     PRIMARY KEY,
    prod_nm         VARCHAR(100)    NOT NULL,
    prod_categ      VARCHAR(20),                    -- MORTGAGE/CONSUMER/AUTO/BUSINESS
    min_amt         NUMERIC(18,2),
    max_amt         NUMERIC(18,2),
    min_term_mo     INTEGER,
    max_term_mo     INTEGER,
    base_rate       NUMERIC(5,2),                   -- annual interest rate %
    is_active       BOOLEAN         DEFAULT TRUE
);

-- -----------------------------------------------------------
-- 10. tbl_loan - Active and historical loans
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_loan (
    loan_no         VARCHAR(30)     PRIMARY KEY,
    cust_no         VARCHAR(20)     NOT NULL,       -- logical FK to tbl_cust
    prod_cd         VARCHAR(20)     NOT NULL,       -- logical FK to tbl_loan_prod
    disb_acct_no    VARCHAR(30),                    -- disbursement account, logical FK
    repay_acct_no   VARCHAR(30),                    -- repayment account, logical FK
    appl_dt         DATE            NOT NULL,       -- application date
    appr_dt         DATE,                           -- approval date
    disb_dt         DATE,                           -- disbursement date
    mat_dt          DATE,                           -- maturity date
    loan_amt        NUMERIC(18,2)   NOT NULL,
    ccy_cd          CHAR(3)         NOT NULL,
    int_rate        NUMERIC(5,2)    NOT NULL,       -- actual interest rate
    term_mo         INTEGER         NOT NULL,       -- term in months
    outst_princ     NUMERIC(18,2)   DEFAULT 0,     -- outstanding principal
    outst_int       NUMERIC(18,2)   DEFAULT 0,     -- outstanding interest
    overdue_amt     NUMERIC(18,2)   DEFAULT 0,
    overdue_days    INTEGER         DEFAULT 0,
    npl_flag        CHAR(1)         DEFAULT 'N',   -- Y/N non-performing loan
    br_cd           VARCHAR(10),                    -- origination branch
    loan_off_emp_no VARCHAR(20),                    -- loan officer, logical FK
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE', -- ACTIVE/CLOSED/WRITEOFF/RESTRUCTURED
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 11. tbl_coll - Collateral / security for loans
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_coll (
    coll_id         SERIAL          PRIMARY KEY,
    loan_no         VARCHAR(30)     NOT NULL,       -- logical FK to tbl_loan
    coll_tp         VARCHAR(20)     NOT NULL,       -- REAL_ESTATE/VEHICLE/DEPOSIT/EQUIPMENT
    coll_desc       VARCHAR(300),
    appraisal_val   NUMERIC(18,2),
    appraisal_dt    DATE,
    ccy_cd          CHAR(3)         DEFAULT 'MDL',
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE',
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 12. tbl_guar - Loan guarantors
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_guar (
    guar_id         SERIAL          PRIMARY KEY,
    loan_no         VARCHAR(30)     NOT NULL,       -- logical FK to tbl_loan
    guar_cust_no    VARCHAR(20),                    -- logical FK to tbl_cust (if existing customer)
    guar_nm         VARCHAR(150)    NOT NULL,
    guar_idnp       VARCHAR(20),
    guar_tp         VARCHAR(10),                    -- 'PF' or 'PJ'
    guar_amt        NUMERIC(18,2),
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE',
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 13. tbl_card - Debit and credit cards
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_card (
    card_no_hash    VARCHAR(64)     PRIMARY KEY,    -- hashed card number
    acct_no         VARCHAR(30)     NOT NULL,       -- logical FK to tbl_acct
    cust_no         VARCHAR(20)     NOT NULL,       -- logical FK to tbl_cust
    card_tp         VARCHAR(10)     NOT NULL,       -- DEBIT/CREDIT
    card_brand      VARCHAR(20),                    -- VISA/MASTERCARD/MAESTRO
    issue_dt        DATE            NOT NULL,
    exp_dt          DATE            NOT NULL,
    lim_amt         NUMERIC(18,2),                  -- credit limit
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE', -- ACTIVE/BLOCKED/EXPIRED/CANCELLED
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 14. tbl_fx_rate - Daily FX rates
-- -----------------------------------------------------------
CREATE TABLE bank.tbl_fx_rate (
    rate_dt         DATE            NOT NULL,
    ccy_from        CHAR(3)         NOT NULL,
    ccy_to          CHAR(3)         NOT NULL,
    buy_rate        NUMERIC(12,6)   NOT NULL,
    sell_rate       NUMERIC(12,6)   NOT NULL,
    bnm_rate        NUMERIC(12,6),                  -- central bank official rate
    upd_ts          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (rate_dt, ccy_from, ccy_to)
);

-- -----------------------------------------------------------
-- Indexes (the ones a real bank DB would have)
-- -----------------------------------------------------------
CREATE INDEX idx_txn_acct_dt ON bank.tbl_txn (acct_no, txn_dt);
CREATE INDEX idx_txn_dt ON bank.tbl_txn (txn_dt);
CREATE INDEX idx_acct_cust ON bank.tbl_acct (cust_no);
CREATE INDEX idx_loan_cust ON bank.tbl_loan (cust_no);
CREATE INDEX idx_cust_addr_cust ON bank.tbl_cust_addr (cust_no);
CREATE INDEX idx_card_acct ON bank.tbl_card (acct_no);
CREATE INDEX idx_coll_loan ON bank.tbl_coll (loan_no);