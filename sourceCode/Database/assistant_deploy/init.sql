-- mysql schema for university life assistant
-- character set: utf8mb4 for full vietnamese diacritics support
-- all datetime columns store utc timestamps by convention

CREATE DATABASE IF NOT EXISTS university_assistant
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE university_assistant;

-- 1. USERS & AUTHENTICATION TABLES

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE auth_identities (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    provider ENUM('password', 'google', 'github') NOT NULL,
    provider_user_id VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_auth_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT uq_provider_identity UNIQUE (provider, provider_user_id),
    INDEX idx_auth_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE user_preferences (
    user_id INT PRIMARY KEY,
    sleep_start TIME NOT NULL DEFAULT '23:30:00',
    sleep_end TIME NOT NULL DEFAULT '06:30:00',
    min_break_minutes INT NOT NULL DEFAULT 15,
    max_block_minutes INT NOT NULL DEFAULT 180,
    slot_step_minutes INT NOT NULL DEFAULT 15,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_pref_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. COURSES & TASKS TABLES

CREATE TABLE courses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    course_code VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    default_room VARCHAR(100) NULL,
    import_batch_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME NULL DEFAULT NULL,
    CONSTRAINT fk_course_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_course_owner_active (owner_id, deleted_at),
    INDEX idx_course_batch (owner_id, import_batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    duration_minutes INT NOT NULL,
    priority TINYINT NOT NULL DEFAULT 3,
    priority_source ENUM('USER', 'AI', 'DEFAULT') NOT NULL DEFAULT 'DEFAULT',
    status ENUM('PENDING', 'SCHEDULED', 'COMPLETED') NOT NULL DEFAULT 'PENDING',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME NULL DEFAULT NULL,
    CONSTRAINT fk_task_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT chk_task_priority CHECK (priority BETWEEN 1 AND 3),
    CONSTRAINT chk_task_duration CHECK (duration_minutes > 0),
    INDEX idx_task_owner_active (owner_id, deleted_at, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. PROPOSALS TABLE

CREATE TABLE proposals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    task_id INT NOT NULL,
    parent_id INT NULL DEFAULT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    extra_slots_json JSON NULL DEFAULT NULL,
    rationale TEXT NULL,
    source_prompt TEXT NULL,
    status ENUM('PROPOSED', 'CONFIRMED', 'REJECTED', 'RESCHEDULED', 'ABANDONED') NOT NULL DEFAULT 'PROPOSED',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_proposal_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_proposal_task FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    CONSTRAINT fk_proposal_parent FOREIGN KEY (parent_id) REFERENCES proposals(id) ON DELETE SET NULL,
    INDEX idx_proposal_owner_status (owner_id, status),
    INDEX idx_proposal_task (task_id),
    INDEX idx_proposal_parent (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. EVENTS & REMINDERS TABLES

CREATE TABLE events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    owner_id INT NOT NULL,
    course_id INT NULL DEFAULT NULL,
    task_id INT NULL DEFAULT NULL,
    proposal_id INT NULL DEFAULT NULL,
    title VARCHAR(255) NOT NULL,
    room VARCHAR(100) NULL DEFAULT NULL,
    kind ENUM('CLASS', 'EXAM', 'DEADLINE', 'EVENT', 'TASK') NOT NULL,
    source ENUM('IMPORTED', 'AI_CREATED', 'MANUAL') NOT NULL,
    import_batch_id VARCHAR(64) NULL DEFAULT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    is_hard BOOLEAN NOT NULL DEFAULT FALSE,
    priority TINYINT NOT NULL DEFAULT 3,
    is_important BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME NULL DEFAULT NULL,
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
    owner_id INT NOT NULL,
    event_id INT NOT NULL UNIQUE,
    offset_minutes INT NOT NULL DEFAULT 30,
    scheduled_on_device_at DATETIME NULL DEFAULT NULL,
    delivered_at DATETIME NULL DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_reminder_owner FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_reminder_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. OPERATIONAL & TELEMETRY LOG TABLES

CREATE TABLE telemetry_metric_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    recorded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metric_name VARCHAR(64) NOT NULL,
    metric_value DOUBLE NOT NULL,
    metadata_json JSON NULL DEFAULT NULL,
    INDEX idx_telemetry_name_time (metric_name, recorded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE ai_error_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INT NULL DEFAULT NULL,
    prompt_text TEXT NOT NULL,
    raw_output TEXT NULL,
    error_type ENUM('TIMEOUT', 'INFRA_CRASH', 'SCHEMA_VALIDATION', 'SEMANTIC_FAILURE') NOT NULL,
    retry_count TINYINT NOT NULL DEFAULT 0,
    triggered_fallback BOOLEAN NOT NULL DEFAULT TRUE,
    INDEX idx_ai_error_type_time (error_type, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE inference_queue_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    user_id INT NULL DEFAULT NULL,
    enqueued_at DATETIME(3) NOT NULL,
    started_at DATETIME(3) NULL DEFAULT NULL,
    completed_at DATETIME(3) NULL DEFAULT NULL,
    status ENUM('QUEUED', 'PROCESSING', 'COMPLETED', 'TIMEOUT', 'FAILED') NOT NULL DEFAULT 'QUEUED',
    INDEX idx_queue_status_time (status, enqueued_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;