-- =========================================
-- Sample parking spaces
-- =========================================

INSERT INTO spaces (space_code)
SELECT 'A-' || lpad(g::text, 2, '0')
FROM generate_series(1, 10) AS g
UNION ALL
SELECT 'B-' || lpad(g::text, 2, '0')
FROM generate_series(1, 10) AS g
ON CONFLICT (space_code) DO NOTHING;


-- =========================================
-- Facility working hours
-- PostgreSQL DOW: 0 = Sunday, 6 = Saturday
-- =========================================

INSERT INTO working_hours (
    weekday,
    open_time,
    close_time
)
VALUES
    (0, '08:00', '20:00'),
    (1, '06:00', '22:00'),
    (2, '06:00', '22:00'),
    (3, '06:00', '22:00'),
    (4, '06:00', '22:00'),
    (5, '06:00', '22:00'),
    (6, '06:00', '22:00')
ON CONFLICT (weekday)
DO UPDATE SET
    open_time = EXCLUDED.open_time,
    close_time = EXCLUDED.close_time;


-- =========================================
-- Sample pricing
-- Standard: ₹40/hour, 06:00–18:00
-- Evening:  ₹30/hour, 18:00–22:00
-- =========================================

INSERT INTO pricing (
    band_name,
    start_time,
    end_time,
    hourly_rate
)
SELECT
    'Standard',
    '06:00',
    '18:00',
    40.00
WHERE NOT EXISTS (
    SELECT 1
    FROM pricing
    WHERE band_name = 'Standard'
      AND start_time = '06:00'
      AND end_time = '18:00'
      AND hourly_rate = 40.00
);

INSERT INTO pricing (
    band_name,
    start_time,
    end_time,
    hourly_rate
)
SELECT
    'Evening',
    '18:00',
    '22:00',
    30.00
WHERE NOT EXISTS (
    SELECT 1
    FROM pricing
    WHERE band_name = 'Evening'
      AND start_time = '18:00'
      AND end_time = '22:00'
      AND hourly_rate = 30.00
);