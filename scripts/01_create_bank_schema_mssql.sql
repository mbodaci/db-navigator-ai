-- DB-Navigator AI: Synthetic Bank Database Schema (MS SQL Server)
-- Converted from PostgreSQL. Creates 14 tables in [bank] schema.
-- NO foreign key constraints (deliberate - mimics undocumented MAIB database).

IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = 'bank')
    EXEC('CREATE SCHEMA bank');
GO

CREATE TABLE bank.tbl_br (
    br_cd           VARCHAR(10)     PRIMARY KEY,
    br_nm           VARCHAR(100)    NOT NULL,
    br_addr         VARCHAR(200),
    br_city         VARCHAR(50),
    br_region       VARCHAR(50),
    br_mgr_emp_no   VARCHAR(20),
    open_dt         DATE,
    stat_cd         INT             DEFAULT 1,
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_emp (
    emp_no          VARCHAR(20)     PRIMARY KEY,
    emp_nm          VARCHAR(100)    NOT NULL,
    emp_surnm       VARCHAR(100)    NOT NULL,
    emp_pos         VARCHAR(80),
    br_cd           VARCHAR(10),
    dept_cd         VARCHAR(20),
    hire_dt         DATE,
    term_dt         DATE,
    mgr_emp_no      VARCHAR(20),
    sal_amt         NUMERIC(12,2),
    stat_cd         INT             DEFAULT 1,
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_cust (
    cust_no         VARCHAR(20)     PRIMARY KEY,
    cust_tp         VARCHAR(5)      NOT NULL,
    cust_nm         VARCHAR(150)    NOT NULL,
    idnp            VARCHAR(20),
    idno            VARCHAR(20),
    birth_dt        DATE,
    gender_cd       CHAR(1),
    phone_no        VARCHAR(20),
    email_addr      VARCHAR(100),
    reg_dt          DATE            NOT NULL,
    br_cd           VARCHAR(10),
    risk_categ      VARCHAR(10),
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE',
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_cust_addr (
    addr_id         INT IDENTITY(1,1) PRIMARY KEY,
    cust_no         VARCHAR(20)     NOT NULL,
    addr_tp         VARCHAR(10)     NOT NULL,
    addr_line1      VARCHAR(200),
    addr_line2      VARCHAR(200),
    city            VARCHAR(50),
    region          VARCHAR(50),
    postal_cd       VARCHAR(10),
    country_cd      CHAR(3)         DEFAULT 'MDA',
    is_primary      BIT             DEFAULT 0,
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_acct_tp (
    acct_tp_cd      VARCHAR(10)     PRIMARY KEY,
    acct_tp_nm      VARCHAR(80)     NOT NULL,
    acct_tp_desc    VARCHAR(200),
    ccy_cd          CHAR(3),
    is_active       BIT             DEFAULT 1
);

CREATE TABLE bank.tbl_acct (
    acct_no         VARCHAR(30)     PRIMARY KEY,
    cust_no         VARCHAR(20)     NOT NULL,
    acct_tp_cd      VARCHAR(10)     NOT NULL,
    ccy_cd          CHAR(3)         NOT NULL,
    br_cd           VARCHAR(10),
    open_dt         DATE            NOT NULL,
    close_dt        DATE,
    cur_bal         NUMERIC(18,2)   DEFAULT 0,
    avail_bal       NUMERIC(18,2)   DEFAULT 0,
    hold_amt        NUMERIC(18,2)   DEFAULT 0,
    stat_cd         VARCHAR(10)     DEFAULT 'OPEN',
    last_txn_dt     DATE,
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_txn_tp (
    txn_tp_cd       VARCHAR(10)     PRIMARY KEY,
    txn_tp_nm       VARCHAR(80)     NOT NULL,
    txn_tp_desc     VARCHAR(200),
    dr_cr_ind       CHAR(1)         NOT NULL,
    is_active       BIT             DEFAULT 1
);

CREATE TABLE bank.tbl_txn (
    txn_id          BIGINT IDENTITY(1,1) PRIMARY KEY,
    acct_no         VARCHAR(30)     NOT NULL,
    txn_tp_cd       VARCHAR(10)     NOT NULL,
    txn_dt          DATE            NOT NULL,
    val_dt          DATE,
    txn_amt         NUMERIC(18,2)   NOT NULL,
    ccy_cd          CHAR(3)         NOT NULL,
    dr_cr_ind       CHAR(1)         NOT NULL,
    bal_after        NUMERIC(18,2),
    ref_no          VARCHAR(50),
    cntrp_acct_no   VARCHAR(30),
    cntrp_nm        VARCHAR(150),
    descr           VARCHAR(500),
    channel_cd      VARCHAR(10),
    auth_emp_no     VARCHAR(20),
    stat_cd         VARCHAR(10)     DEFAULT 'POST',
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_loan_prod (
    prod_cd         VARCHAR(20)     PRIMARY KEY,
    prod_nm         VARCHAR(100)    NOT NULL,
    prod_categ      VARCHAR(20),
    min_amt         NUMERIC(18,2),
    max_amt         NUMERIC(18,2),
    min_term_mo     INT,
    max_term_mo     INT,
    base_rate       NUMERIC(5,2),
    is_active       BIT             DEFAULT 1
);

CREATE TABLE bank.tbl_loan (
    loan_no         VARCHAR(30)     PRIMARY KEY,
    cust_no         VARCHAR(20)     NOT NULL,
    prod_cd         VARCHAR(20)     NOT NULL,
    disb_acct_no    VARCHAR(30),
    repay_acct_no   VARCHAR(30),
    appl_dt         DATE            NOT NULL,
    appr_dt         DATE,
    disb_dt         DATE,
    mat_dt          DATE,
    loan_amt        NUMERIC(18,2)   NOT NULL,
    ccy_cd          CHAR(3)         NOT NULL,
    int_rate        NUMERIC(5,2)    NOT NULL,
    term_mo         INT             NOT NULL,
    outst_princ     NUMERIC(18,2)   DEFAULT 0,
    outst_int       NUMERIC(18,2)   DEFAULT 0,
    overdue_amt     NUMERIC(18,2)   DEFAULT 0,
    overdue_days    INT             DEFAULT 0,
    npl_flag        CHAR(1)         DEFAULT 'N',
    br_cd           VARCHAR(10),
    loan_off_emp_no VARCHAR(20),
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE',
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_coll (
    coll_id         INT IDENTITY(1,1) PRIMARY KEY,
    loan_no         VARCHAR(30)     NOT NULL,
    coll_tp         VARCHAR(20)     NOT NULL,
    coll_desc       VARCHAR(300),
    appraisal_val   NUMERIC(18,2),
    appraisal_dt    DATE,
    ccy_cd          CHAR(3)         DEFAULT 'MDL',
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE',
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_guar (
    guar_id         INT IDENTITY(1,1) PRIMARY KEY,
    loan_no         VARCHAR(30)     NOT NULL,
    guar_cust_no    VARCHAR(20),
    guar_nm         VARCHAR(150)    NOT NULL,
    guar_idnp       VARCHAR(20),
    guar_tp         VARCHAR(10),
    guar_amt        NUMERIC(18,2),
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE',
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_card (
    card_no_hash    VARCHAR(64)     PRIMARY KEY,
    acct_no         VARCHAR(30)     NOT NULL,
    cust_no         VARCHAR(20)     NOT NULL,
    card_tp         VARCHAR(10)     NOT NULL,
    card_brand      VARCHAR(20),
    issue_dt        DATE            NOT NULL,
    exp_dt          DATE            NOT NULL,
    lim_amt         NUMERIC(18,2),
    stat_cd         VARCHAR(10)     DEFAULT 'ACTIVE',
    upd_ts          DATETIME2       DEFAULT GETDATE()
);

CREATE TABLE bank.tbl_fx_rate (
    rate_dt         DATE            NOT NULL,
    ccy_from        CHAR(3)         NOT NULL,
    ccy_to          CHAR(3)         NOT NULL,
    buy_rate        NUMERIC(12,6)   NOT NULL,
    sell_rate       NUMERIC(12,6)   NOT NULL,
    bnm_rate        NUMERIC(12,6),
    upd_ts          DATETIME2       DEFAULT GETDATE(),
    CONSTRAINT pk_fx_rate PRIMARY KEY (rate_dt, ccy_from, ccy_to)
);

-- Indexes
CREATE INDEX idx_txn_acct_dt ON bank.tbl_txn (acct_no, txn_dt);
CREATE INDEX idx_txn_dt ON bank.tbl_txn (txn_dt);
CREATE INDEX idx_acct_cust ON bank.tbl_acct (cust_no);
CREATE INDEX idx_loan_cust ON bank.tbl_loan (cust_no);
CREATE INDEX idx_cust_addr_cust ON bank.tbl_cust_addr (cust_no);
CREATE INDEX idx_card_acct ON bank.tbl_card (acct_no);
CREATE INDEX idx_coll_loan ON bank.tbl_coll (loan_no);
GO
