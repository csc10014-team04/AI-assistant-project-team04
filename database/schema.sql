-- mysql schema for university life assistant
-- character set: utf8mb4 for full vietnamese diacritics support
-- all datetime columns store utc timestamps by convention

CREATE DATABASE IF NOT EXISTS university_assistant
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE university_assistant;

-- ============================================================================
-- 1. USERS & AUTHENTICATION TABLES
-- ============================================================================

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE auth_identities (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    provider ENUM('password', 'google', 'github') NOT NULL,
    provider_user_id VARCHAR(255) NOT NULL, -- username for password provider, or oauth subject id
    hashed_password VARCHAR(255) NULL,      -- only populated when provider = 'password'
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_auth_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT uq_provider_identity UNIQUE (provider, provider_user_id),
    INDEX idx_auth_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE user_preferences (
    user_id INT PRIMARY KEY,
    sleep_start TIME NOT NULL DEFAULT '23:30:00',       -- default sleep start time
    sleep_end TIME NOT NULL DEFAULT '06:30:00',         -- default wake up time
    min_break_minutes INT NOT NULL DEFAULT 15,          -- minimum buffer between blocks
    max_block_minutes INT NOT NULL DEFAULT 180,         -- max continuous work duration
    slot_step_minutes INT NOT NULL DEFAULT 15,          -- 15-minute rounding grid
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_pref_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- 2. COURSES & TASKS TABLES
-- ============================================================================

CREATE TABLE courses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,                              -- user ownership for data isolation
    course_code VARCHAR(50) NOT NULL,                   -- e.g. 'CSC10004'
    title VARCHAR(255) NOT NULL,                        -- e.g. 'Cau truc du lieu'
    default_room VARCHAR(100) NULL,                     -- e.g. 'E201'
    import_batch_id VARCHAR(64) NULL,                   -- tracks timetable file import batch
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME NULL DEFAULT NULL,              -- soft delete timestamp
    CONSTRAINT fk_course_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_course_owner_active (owner_id, deleted_at),
    INDEX idx_course_batch (owner_id, import_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,                              -- user ownership for data isolation
    title VARCHAR(255) NOT NULL,                        -- activity name
    description TEXT NULL,                              -- optional details
    duration_minutes INT NOT NULL,                      -- required total duration
    priority TINYINT NOT NULL DEFAULT 3,                -- 1=high, 2=medium, 3=low
    priority_source ENUM('USER', 'AI', 'DEFAULT') NOT NULL DEFAULT 'DEFAULT',
    status ENUM('PENDING', 'SCHEDULED', 'COMPLETED') NOT NULL DEFAULT 'PENDING',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME NULL DEFAULT NULL,              -- soft delete timestamp
    CONSTRAINT fk_task_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT chk_task_priority CHECK (priority BETWEEN 1 AND 3),
    CONSTRAINT chk_task_duration CHECK (duration_minutes > 0),
    INDEX idx_task_owner_active (owner_id, deleted_at, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- 3. PROPOSALS TABLE
-- ============================================================================

CREATE TABLE proposals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,                              -- user ownership for data isolation
    task_id INT NOT NULL,                               -- links to tasks.id
    parent_id INT NULL DEFAULT NULL,                    -- links to previous proposal when rescheduled
    start_time DATETIME NOT NULL,                       -- primary proposed start in utc
    end_time DATETIME NOT NULL,                         -- primary proposed end in utc
    extra_slots_json JSON NULL DEFAULT NULL,            -- stores additional split slots when a task is divided
    rationale TEXT NULL,                                -- natural language explanation from ai
    source_prompt TEXT NULL,                            -- user prompt that triggered this proposal
    status ENUM('PROPOSED', 'CONFIRMED', 'REJECTED', 'RESCHEDULED', 'ABANDONED') NOT NULL DEFAULT 'PROPOSED',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    -- note: no deleted_at on proposals; lifecycle managed strictly via status
    CONSTRAINT fk_proposal_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_proposal_task FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    CONSTRAINT fk_proposal_parent FOREIGN KEY (parent_id) REFERENCES proposals(id) ON DELETE SET NULL,
    INDEX idx_proposal_owner_status (owner_id, status),
    INDEX idx_proposal_task (task_id),
    INDEX idx_proposal_parent (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- 4. EVENTS & REMINDERS TABLES
-- ============================================================================

CREATE TABLE events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,                              -- user ownership for data isolation
    course_id INT NULL DEFAULT NULL,                    -- populated for recurring CLASS events
    task_id INT NULL DEFAULT NULL,                      -- populated for scheduled TASK events
    proposal_id INT NULL DEFAULT NULL,                  -- tracks which proposal created this event
    title VARCHAR(255) NOT NULL,                        -- own title for fast querying without join
    room VARCHAR(100) NULL DEFAULT NULL,                -- own room/location column
    kind ENUM('CLASS', 'EXAM', 'DEADLINE', 'EVENT', 'TASK') NOT NULL, -- unified entity discriminator
    source ENUM('IMPORTED', 'AI_CREATED', 'MANUAL') NOT NULL,         -- provenance tracking
    import_batch_id VARCHAR(64) NULL DEFAULT NULL,      -- batch identifier for re-import replacement
    start_time DATETIME NOT NULL,                       -- utc timestamp; for DEADLINE start_time == end_time
    end_time DATETIME NOT NULL,                         -- utc timestamp
    is_hard BOOLEAN NOT NULL DEFAULT FALSE,             -- true for academic hard constraints
    priority TINYINT NOT NULL DEFAULT 3,                -- 1=high, 2=medium, 3=low
    is_important BOOLEAN NOT NULL DEFAULT FALSE,        -- marked via ui button for notification
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME NULL DEFAULT NULL,              -- soft delete timestamp
    CONSTRAINT fk_event_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_event_course FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE SET NULL,
    CONSTRAINT fk_event_task FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    CONSTRAINT fk_event_proposal FOREIGN KEY (proposal_id) REFERENCES proposals(id) ON DELETE SET NULL,
    CONSTRAINT chk_event_priority CHECK (priority BETWEEN 1 AND 3),
    CONSTRAINT chk_event_time CHECK (end_time >= start_time),
    INDEX idx_event_lookup (owner_id, deleted_at, start_time, end_time),
    INDEX idx_event_source_batch (owner_id, source, import_batch_id),
    INDEX idx_event_course (course_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE reminders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,                              -- user ownership for data isolation
    event_id INT NOT NULL UNIQUE,                       -- max 1 reminder per event or deadline
    offset_minutes INT NOT NULL DEFAULT 30,             -- minutes before event.start_time
    scheduled_on_device_at DATETIME NULL DEFAULT NULL,  -- reported back by mobile app
    delivered_at DATETIME NULL DEFAULT NULL,            -- reported back by mobile app
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_reminder_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_reminder_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- 5. OPERATIONAL & TELEMETRY LOG TABLES
-- ============================================================================

CREATE TABLE telemetry_metric_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    recorded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metric_name VARCHAR(64) NOT NULL,                   -- e.g. 'pipeline_latency_ms', 'vram_used_mb', 'queue_depth'
    metric_value DOUBLE NOT NULL,
    metadata_json JSON NULL DEFAULT NULL,
    INDEX idx_telemetry_name_time (metric_name, recorded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE ai_error_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INT NULL DEFAULT NULL,
    prompt_text TEXT NOT NULL,                          -- input prompt that caused failure
    raw_output TEXT NULL,                               -- raw malformed llm output
    error_type ENUM('TIMEOUT', 'INFRA_CRASH', 'SCHEMA_VALIDATION', 'SEMANTIC_FAILURE') NOT NULL,
    retry_count TINYINT NOT NULL DEFAULT 0,
    triggered_fallback BOOLEAN NOT NULL DEFAULT TRUE,
    INDEX idx_ai_error_type_time (error_type, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE inference_queue_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    user_id INT NULL DEFAULT NULL,
    enqueued_at DATETIME(3) NOT NULL,                   -- millisecond precision for latency tracking
    started_at DATETIME(3) NULL DEFAULT NULL,
    completed_at DATETIME(3) NULL DEFAULT NULL,
    status ENUM('QUEUED', 'PROCESSING', 'COMPLETED', 'TIMEOUT', 'FAILED') NOT NULL DEFAULT 'QUEUED',
    INDEX idx_queue_status_time (status, enqueued_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
