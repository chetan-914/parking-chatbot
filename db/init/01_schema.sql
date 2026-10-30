-- Enable GiST support for equality comparisons on space_id.
-- Required by the reservation exclusion constraint.
CREATE EXTENSION IF NOT EXISTS btree_gist;


-- =====================================================
-- 1. SPACES
-- Stores the physical parking spaces available.
-- =====================================================

CREATE TABLE spaces (
    space_id   SERIAL PRIMARY KEY,
    space_code TEXT NOT NULL UNIQUE,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE
);


-- =====================================================
-- 2. WORKING HOURS
-- Stores opening and closing times for each weekday.
-- PostgreSQL DOW: 0 = Sunday, 6 = Saturday.
-- =====================================================

CREATE TABLE working_hours (
    weekday    SMALLINT PRIMARY KEY
               CHECK (weekday BETWEEN 0 AND 6),

    open_time  TIME NOT NULL,
    close_time TIME NOT NULL,

    is_closed  BOOLEAN NOT NULL DEFAULT FALSE,

    CHECK (close_time > open_time)
);


-- =====================================================
-- 3. PRICING
-- Stores hourly rates for different time bands.
-- =====================================================

CREATE TABLE pricing (
    price_id    SERIAL PRIMARY KEY,
    band_name   TEXT NOT NULL,

    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL,

    hourly_rate NUMERIC(8,2) NOT NULL
                CHECK (hourly_rate >= 0),

    CHECK (end_time > start_time)
);


-- =====================================================
-- 4. CUSTOMERS
-- Stores private customer information.
-- The agent database role will not have access.
-- =====================================================

CREATE TABLE customers (
    customer_id BIGSERIAL PRIMARY KEY,

    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,

    car_number  TEXT NOT NULL CHECK (
        car_number ~
        '^([A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$'
    ),

    created_at  TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);


-- =====================================================
-- 5. RESERVATIONS
-- Stores parking reservations.
-- Uses a time range to prevent overlapping bookings.
-- =====================================================

CREATE TABLE reservations (
    reservation_id BIGSERIAL PRIMARY KEY,

    booking_ref    UUID NOT NULL UNIQUE
                   DEFAULT gen_random_uuid(),

    space_id       INT NOT NULL
                   REFERENCES spaces(space_id),

    customer_id    BIGINT NOT NULL
                   REFERENCES customers(customer_id),

    period         TSRANGE NOT NULL,

    total_price    NUMERIC(10,2) NOT NULL,

    status         TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'cancelled')),

    conversation_id UUID,

    created_at     TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP,

    -- Prevent overlapping active reservations
    -- for the same parking space.
    EXCLUDE USING gist (
        space_id WITH =,
        period WITH &&
    )
    WHERE (status = 'active')
);


-- =====================================================
-- 6. RESERVATION HISTORY
-- Audit log maintained by database triggers.
-- Does not store customer names or car numbers.
-- =====================================================

CREATE TABLE reservation_history (
    history_id     BIGSERIAL PRIMARY KEY,

    reservation_id BIGINT NOT NULL,
    space_id       INT NOT NULL,

    period         TSRANGE NOT NULL,

    total_price    NUMERIC(10,2) NOT NULL,

    action         TEXT NOT NULL
                   CHECK (action IN ('created', 'cancelled')),

    old_status     TEXT,
    new_status     TEXT NOT NULL,

    changed_at     TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);


-- =====================================================
-- 7. CONVERSATION LOG
-- Stores redacted conversation transcripts.
-- =====================================================

CREATE TABLE conversation_log (
    conversation_id UUID PRIMARY KEY,

    transcript      TEXT NOT NULL,

    end_reason      TEXT NOT NULL,

    turn_count      INT NOT NULL,

    started_at      TIMESTAMP NOT NULL,

    ended_at        TIMESTAMP NOT NULL DEFAULT LOCALTIMESTAMP
);