-- schema.sql
-- Fintech ML Project Database Schema
-- Author: Hisham Barakat (hishambarakat16@gmail.com)

-- ================================
-- Core schema + extensions
-- ================================
CREATE SCHEMA IF NOT EXISTS core;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;


CREATE TABLE core.customers (
    customer_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name     VARCHAR(255) NOT NULL,
    email         CITEXT UNIQUE NOT NULL,
    phone         VARCHAR(50),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);


-- ================================
-- Accounts
-- ================================
DO $$ BEGIN
    CREATE TYPE core.account_type_enum AS ENUM ('checking', 'savings', 'credit', 'loan');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE core.currency_enum AS ENUM ('BHD', 'USD', 'EUR', 'SAR', 'AED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE core.accounts (
    account_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id   UUID NOT NULL REFERENCES core.customers(customer_id) ON DELETE CASCADE,
    account_type  core.account_type_enum NOT NULL,
    currency      core.currency_enum NOT NULL,
    credit_limit  NUMERIC(18,2) DEFAULT 0 CHECK (credit_limit >= 0),
    is_active     BOOLEAN DEFAULT TRUE,
    opened_at     TIMESTAMPTZ DEFAULT NOW(),
    closed_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS core.app_users (
  user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email citext UNIQUE NOT NULL,
  password_hash text NOT NULL,
  customer_id uuid NOT NULL REFERENCES core.customers(customer_id) ON DELETE CASCADE,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_app_users_customer_id ON core.app_users(customer_id);


-- ================================
-- Transactions (upgraded)
-- ================================
DO $$ BEGIN
    CREATE TYPE core.transaction_type_enum AS ENUM ('deposit', 'withdrawal', 'purchase', 'refund', 'transfer');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE core.tx_direction_enum AS ENUM ('debit', 'credit');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE core.tx_status_enum AS ENUM ('pending', 'posted', 'reversed', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE core.tx_channel_enum AS ENUM ('card', 'transfer', 'atm', 'fee', 'internal', 'other');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE core.transactions (
    tx_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id   UUID NOT NULL REFERENCES core.accounts(account_id) ON DELETE CASCADE,

    tx_type      core.transaction_type_enum NOT NULL,

    -- New: richer transaction state
    direction    core.tx_direction_enum,
    status       core.tx_status_enum DEFAULT 'posted',
    channel      core.tx_channel_enum DEFAULT 'other',

    amount       NUMERIC(18,2) NOT NULL,
    currency     core.currency_enum NOT NULL,

    -- New: merchant/counterparty fields for realistic analytics
    merchant_name      VARCHAR(255),
    merchant_category  VARCHAR(100),
    mcc                VARCHAR(10),

    counterparty_name     VARCHAR(255),
    counterparty_account  VARCHAR(64),

    description  TEXT,

    occurred_at  TIMESTAMPTZ NOT NULL,
    posted_at    TIMESTAMPTZ,
    settled_at   TIMESTAMPTZ,

    -- New: accounting helpers
    balance_after NUMERIC(18,2),
    reference     VARCHAR(128),
    tags          JSONB,

    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_occurred
ON core.transactions (account_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_status
ON core.transactions (status);

CREATE INDEX IF NOT EXISTS idx_transactions_merchant
ON core.transactions (merchant_name);

-- ================================
-- Products
-- ================================
CREATE TABLE core.products (
    product_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(255) NOT NULL,
    category     VARCHAR(100),
    price        NUMERIC(18,2) NOT NULL CHECK (price >= 0),
    currency     core.currency_enum NOT NULL,
    description  TEXT,
    is_active    BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ================================
-- Recommendation Logs
-- ================================
CREATE TABLE core.recommendation_logs (
    rec_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id   UUID NOT NULL REFERENCES core.customers(customer_id) ON DELETE CASCADE,
    product_id    UUID REFERENCES core.products(product_id),
    reason        TEXT,
    features_json JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ================================
-- Events
-- ================================
DO $$ BEGIN
    CREATE TYPE core.event_type_enum AS ENUM ('salary_deposit', 'large_purchase', 'inactivity', 'credit_due', 'promotion');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE core.events (
    event_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  UUID NOT NULL REFERENCES core.customers(customer_id) ON DELETE CASCADE,
    account_id   UUID REFERENCES core.accounts(account_id),
    event_type   core.event_type_enum NOT NULL,
    payload      JSONB,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
