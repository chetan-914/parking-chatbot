-- =====================================================
-- 1. LOG RESERVATION CHANGES
-- Automatically records reservation creation
-- and cancellation in reservation_history.
-- =====================================================

CREATE FUNCTION log_reservation_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN

    -- Record newly created reservations.
    IF TG_OP = 'INSERT' THEN

        INSERT INTO reservation_history (
            reservation_id,
            space_id,
            period,
            total_price,
            action,
            old_status,
            new_status
        )
        VALUES (
            NEW.reservation_id,
            NEW.space_id,
            NEW.period,
            NEW.total_price,
            'created',
            NULL,
            NEW.status
        );


    -- Record active -> cancelled transitions.
    ELSIF TG_OP = 'UPDATE'
          AND OLD.status = 'active'
          AND NEW.status = 'cancelled' THEN

        INSERT INTO reservation_history (
            reservation_id,
            space_id,
            period,
            total_price,
            action,
            old_status,
            new_status
        )
        VALUES (
            NEW.reservation_id,
            NEW.space_id,
            NEW.period,
            NEW.total_price,
            'cancelled',
            OLD.status,
            NEW.status
        );

    END IF;

    RETURN NEW;

END;
$$;


-- Trigger for reservation creation.
CREATE TRIGGER trg_reservation_insert
AFTER INSERT ON reservations
FOR EACH ROW
EXECUTE FUNCTION log_reservation_change();


-- Trigger for reservation cancellation.
CREATE TRIGGER trg_reservation_status
AFTER UPDATE OF status ON reservations
FOR EACH ROW
EXECUTE FUNCTION log_reservation_change();


-- =====================================================
-- 2. PREVENT UNAUTHORIZED RESERVATION MODIFICATIONS
-- Space, customer, period and price cannot be changed.
-- Cancelled reservations cannot be reactivated.
-- =====================================================

CREATE FUNCTION forbid_reservation_edits()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN

    -- Prevent modification of booking details.
    IF NEW.space_id <> OLD.space_id
       OR NEW.customer_id <> OLD.customer_id
       OR NEW.period <> OLD.period
       OR NEW.total_price <> OLD.total_price THEN

        RAISE EXCEPTION
            'IMMUTABLE: only the status of a reservation may change';

    END IF;


    -- Prevent reactivation of cancelled bookings.
    IF OLD.status = 'cancelled'
       AND NEW.status <> 'cancelled' THEN

        RAISE EXCEPTION
            'IMMUTABLE: a cancelled reservation cannot be reactivated';

    END IF;

    RETURN NEW;

END;
$$;


-- Run before every reservation update.
CREATE TRIGGER trg_reservation_guard
BEFORE UPDATE ON reservations
FOR EACH ROW
EXECUTE FUNCTION forbid_reservation_edits();