-- =====================================================================
-- users_table.sql
-- database_manager.py reads/writes a Users table (get_user, create_user,
-- approve_user, get_pending_users) but no DDL script for it existed
-- anywhere in the shipped project (Phase 6, item 6 of the audit).
-- =====================================================================
use inspection_db;
GO
IF OBJECT_ID('Users', 'U') IS NOT NULL
    DROP TABLE Users;
GO
CREATE TABLE Users (
    user_id INT IDENTITY(1,1) PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'USER',       -- 'ADMIN' or 'USER'
    location VARCHAR(100),
    allowed_ip VARCHAR(100),
    is_active BIT NOT NULL DEFAULT 0,                -- new users require admin approval (R3)
    created_at DATETIME NOT NULL DEFAULT GETDATE()
);
GO

CREATE INDEX IX_Users_is_active ON Users (is_active);
GO

-- Seed one initial ADMIN account so there is a way to log in on a fresh
-- database (replace 'CHANGE_ME_NOW' with a real password immediately,
-- e.g. via the create_user()/approve_user() helpers or a one-off script
-- calling werkzeug.security.generate_password_hash).
-- Example (run from Python, NOT here, since password must be hashed):
--   from database_manager import db_manager
--   db_manager.create_user("admin", "CHANGE_ME_NOW", "ADMIN", "ALL", "")
--   db_manager.approve_user("admin")
