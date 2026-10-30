-- =====================================================
-- 1. QUOTE PRICE
-- Calculates the booking price in 30-minute blocks.
-- =====================================================

CREATE FUNCTION quote_price(
    p_start TIMESTAMP,
    p_end   TIMESTAMP
)
RETURNS NUMERIC
LANGUAGE sql
STABLE
AS $$
    SELECT ROUND(COALESCE(SUM(pr.hourly_rate / 2), 0), 2)
    FROM generate_series(
        p_start,
        p_end - INTERVAL '30 minutes',
        INTERVAL '30 minutes'
    ) AS b(block_start)
    JOIN pricing pr
      ON b.block_start::time >= pr.start_time
     AND b.block_start::time < pr.end_time;
$$;


-- =====================================================
-- 2. FREE SPACE COUNT
-- Returns the number of spaces without overlapping
-- active reservations for the requested period.
-- =====================================================

CREATE FUNCTION free_space_count(
    p_start TIMESTAMP,
    p_end   TIMESTAMP
)
RETURNS INT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT COUNT(*)::INT
    FROM spaces s
    WHERE s.is_active
      AND NOT EXISTS (
          SELECT 1
          FROM reservations r
          WHERE r.space_id = s.space_id
            AND r.status = 'active'
            AND r.period && tsrange(p_start, p_end, '[)')
      );
$$;


-- =====================================================
-- 3. MAKE BOOKING
-- Validates the booking, creates the customer record,
-- and assigns the first available parking space.
-- =====================================================

CREATE FUNCTION make_booking(
    p_first       TEXT,
    p_last        TEXT,
    p_car         TEXT,
    p_start       TIMESTAMP,
    p_end         TIMESTAMP,
    p_conversation UUID
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_wh       working_hours%ROWTYPE;
    v_customer BIGINT;
    v_space    INT;
    v_ref      UUID;
    v_price    NUMERIC;
BEGIN

    -- Validate booking period.
    IF p_end <= p_start THEN
        RAISE EXCEPTION
            'INVALID_PERIOD: end must be after start';
    END IF;


    -- Reject past bookings.
    IF p_start < LOCALTIMESTAMP THEN
        RAISE EXCEPTION
            'PAST_START: start is in the past';
    END IF;


    -- Booking must be within the next 14 days.
    IF p_start::date > CURRENT_DATE + 14 THEN
        RAISE EXCEPTION
            'TOO_FAR: more than 14 days ahead';
    END IF;


    -- Overnight and multi-day bookings are not allowed.
    IF p_start::date <> p_end::date THEN
        RAISE EXCEPTION
            'MULTI_DAY: booking must end on the same day';
    END IF;


    -- Booking times must follow a 30-minute grid.
    IF (EXTRACT(EPOCH FROM p_start)::BIGINT % 1800) <> 0
       OR (EXTRACT(EPOCH FROM p_end)::BIGINT % 1800) <> 0 THEN

        RAISE EXCEPTION
            'NOT_ON_GRID: times must be on a 30-minute grid';
    END IF;


    -- Minimum duration: 1 hour.
    -- Maximum duration: 12 hours.
    IF p_end - p_start < INTERVAL '1 hour'
       OR p_end - p_start > INTERVAL '12 hours' THEN

        RAISE EXCEPTION
            'BAD_DURATION: duration must be 1 to 12 hours';
    END IF;


    -- Check the facility's working hours.
    SELECT *
    INTO v_wh
    FROM working_hours
    WHERE weekday = EXTRACT(DOW FROM p_start)::INT;


    IF NOT FOUND
       OR v_wh.is_closed
       OR p_start::time < v_wh.open_time
       OR p_end::time > v_wh.close_time THEN

        RAISE EXCEPTION
            'OUTSIDE_HOURS: outside working hours';
    END IF;


    -- Calculate the booking price.
    v_price := quote_price(p_start, p_end);


    -- Store customer information.
    INSERT INTO customers (
        first_name,
        last_name,
        car_number
    )
    VALUES (
        p_first,
        p_last,
        p_car
    )
    RETURNING customer_id INTO v_customer;


    -- Try available parking spaces in code order.
    FOR v_space IN
        SELECT space_id
        FROM spaces
        WHERE is_active
        ORDER BY space_code
    LOOP

        BEGIN

            INSERT INTO reservations (
                space_id,
                customer_id,
                period,
                total_price,
                conversation_id
            )
            VALUES (
                v_space,
                v_customer,
                tsrange(p_start, p_end, '[)'),
                v_price,
                p_conversation
            )
            RETURNING booking_ref INTO v_ref;

            -- Return the booking reference.
            RETURN v_ref;

        EXCEPTION
            WHEN exclusion_violation THEN
                -- This space is already booked.
                -- Try the next space.
                CONTINUE;
        END;

    END LOOP;


    -- No space was available.
    RAISE EXCEPTION
        'NO_SPACE_AVAILABLE: no free space for that period';

END;
$$;


-- =====================================================
-- 4. CANCEL BOOKING
-- Requires booking reference and matching car number.
-- Only future active bookings can be cancelled.
-- =====================================================

CREATE FUNCTION cancel_booking(
    p_ref UUID,
    p_car TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    n INT;
BEGIN

    UPDATE reservations r
    SET status = 'cancelled'
    FROM customers c
    WHERE r.customer_id = c.customer_id
      AND r.booking_ref = p_ref
      AND c.car_number = p_car
      AND r.status = 'active'
      AND lower(r.period) > LOCALTIMESTAMP;


    GET DIAGNOSTICS n = ROW_COUNT;

    RETURN n = 1;

END;
$$;