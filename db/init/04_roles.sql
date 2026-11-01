-- =====================================================
-- 1. CREATE RESTRICTED AGENT ROLE
-- =====================================================

CREATE ROLE agent_role
LOGIN
PASSWORD 'iuqh49t710tg9h3g';


-- =====================================================
-- 2. REMOVE DEFAULT PUBLIC PERMISSIONS
-- =====================================================

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;


-- =====================================================
-- 3. ALLOW ACCESS TO THE PUBLIC SCHEMA
-- =====================================================

GRANT USAGE ON SCHEMA public TO agent_role;


-- =====================================================
-- 4. ALLOW READ ACCESS TO NON-PRIVATE TABLES
-- =====================================================

GRANT SELECT ON
    spaces,
    working_hours,
    pricing
TO agent_role;


-- =====================================================
-- 5. ALLOW INSERT INTO REDACTED CONVERSATION LOG
-- =====================================================

GRANT INSERT ON TABLE conversation_log TO agent_role;
GRANT UPDATE ON TABLE conversation_log TO agent_role;

GRANT USAGE ON SCHEMA public TO agent_role;


-- =====================================================
-- 6. ALLOW EXECUTION OF APPROVED DATABASE FUNCTIONS
-- =====================================================

GRANT EXECUTE ON FUNCTION
    quote_price(TIMESTAMP, TIMESTAMP)
TO agent_role;


GRANT EXECUTE ON FUNCTION
    free_space_count(TIMESTAMP, TIMESTAMP)
TO agent_role;


GRANT EXECUTE ON FUNCTION
    make_booking(TEXT, TEXT, TEXT, TIMESTAMP, TIMESTAMP, UUID)
TO agent_role;


GRANT EXECUTE ON FUNCTION
    cancel_booking(UUID, TEXT)
TO agent_role;