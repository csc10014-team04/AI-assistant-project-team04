-- mysql schema for the SEARCH ENGINE / knowledge base (public university information)
-- This file is SEPARATE from assistant_deploy/init.sql, which holds the SCHEDULING tables
-- (users, tasks, proposals, events, reminders, logs ...).
--
--   init.sql                    -> private, per-student data, filtered by owner_id, soft deleted
--   search_engine_schema.sql    -> public facts about faculties, lecturers, courses, achievements
--                                  (no user data, no owner_id, every table name starts with kb_)
--
-- Rules for this file
--   * every table name starts with kb_ so it can never collide with a scheduling table
--     (scheduling already has `courses`; the search engine has `kb_courses`)
--   * no foreign key points into a scheduling table and no scheduling table points here
--   * idempotent: CREATE ... IF NOT EXISTS and INSERT IGNORE, so it can be re-run on an existing database
--   * names are stored twice: `name` (as published) and `name_folded` (lower case, no Vietnamese accents,
--     filled by the loader) so "thay nguyen van a" finds "Nguyễn Văn A"
--   * every fact keeps `source_id` -> kb_sources (the page it came from) so answers can cite their source
--   * extracted rows start as review_status = 'PENDING' and are shown to users only when 'APPROVED'
--   * datetime columns store UTC by convention, like the rest of the project
--
-- Apply:
--   fresh database : mounted automatically by docker-compose (see assistant_deploy/docker-compose.yml)
--   existing volume: docker exec -i schedule_db mysql -u<DB_USER> -p university_assistant < sourceCode/Database/knowledgebase/search_engine_schema.sql

CREATE DATABASE IF NOT EXISTS university_assistant
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE university_assistant;

-- 1. WHERE THE DATA CAME FROM

CREATE TABLE IF NOT EXISTS kb_sources (
    id INT AUTO_INCREMENT PRIMARY KEY,
    site_id VARCHAR(30) NOT NULL COMMENT 'hcmus, fit, fbb, chemistry, math (same ids as knowledgebase/sources.json)',
    url VARCHAR(1000) NOT NULL,
    url_hash CHAR(64) NOT NULL COMMENT 'sha256 of url; lets a unique index cover long urls',
    title VARCHAR(500) NULL,
    content_sha256 CHAR(64) NULL COMMENT 'hash of the extracted text; changes when the page changes',
    markdown_file VARCHAR(255) NULL COMMENT 'path under knowledgebase/data/',
    fetched_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kb_source_url UNIQUE (url_hash),
    INDEX idx_kb_source_site (site_id, fetched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. ORGANISATION

CREATE TABLE IF NOT EXISTS kb_faculties (
    id INT AUTO_INCREMENT PRIMARY KEY,
    site_id VARCHAR(30) NOT NULL,
    name VARCHAR(255) NOT NULL,
    name_folded VARCHAR(255) NOT NULL,
    short_name VARCHAR(50) NULL COMMENT 'e.g. FIT, FBB',
    home_url VARCHAR(500) NULL,
    description TEXT NULL,
    source_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uq_kb_faculty_site UNIQUE (site_id),
    CONSTRAINT fk_kb_faculty_source FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL,
    INDEX idx_kb_faculty_name (name_folded)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kb_departments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    faculty_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    name_folded VARCHAR(255) NOT NULL,
    description TEXT NULL,
    source_id INT NULL,
    review_status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_kb_dept_faculty FOREIGN KEY (faculty_id) REFERENCES kb_faculties(id) ON DELETE CASCADE,
    CONSTRAINT fk_kb_dept_source FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL,
    CONSTRAINT uq_kb_dept UNIQUE (faculty_id, name_folded),
    INDEX idx_kb_dept_name (name_folded)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. PEOPLE

CREATE TABLE IF NOT EXISTS kb_lecturers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    faculty_id INT NOT NULL,
    department_id INT NULL,
    full_name VARCHAR(255) NOT NULL COMMENT 'without the academic title, as published',
    name_folded VARCHAR(255) NOT NULL,
    academic_title VARCHAR(50) NULL COMMENT 'GS.TS., PGS.TS., TS., ThS. ...',
    position VARCHAR(255) NULL COMMENT 'e.g. Head of department',
    bio TEXT NULL COMMENT 'professional summary published by the faculty; no private contact data',
    profile_url VARCHAR(500) NULL,
    source_id INT NULL,
    review_status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'false = hidden (left the faculty, asked to be removed)',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_kb_lecturer_faculty FOREIGN KEY (faculty_id) REFERENCES kb_faculties(id) ON DELETE CASCADE,
    CONSTRAINT fk_kb_lecturer_dept FOREIGN KEY (department_id) REFERENCES kb_departments(id) ON DELETE SET NULL,
    CONSTRAINT fk_kb_lecturer_source FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL,
    CONSTRAINT uq_kb_lecturer UNIQUE (faculty_id, name_folded),
    INDEX idx_kb_lecturer_name (name_folded),
    INDEX idx_kb_lecturer_visible (review_status, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. TEACHING

CREATE TABLE IF NOT EXISTS kb_programs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    faculty_id INT NOT NULL,
    name VARCHAR(255) NOT NULL COMMENT 'e.g. Chuong trinh chuan, Chuong trinh tien tien',
    name_folded VARCHAR(255) NOT NULL,
    level VARCHAR(50) NULL COMMENT 'undergraduate, master, doctorate',
    description TEXT NULL,
    source_id INT NULL,
    review_status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_kb_program_faculty FOREIGN KEY (faculty_id) REFERENCES kb_faculties(id) ON DELETE CASCADE,
    CONSTRAINT fk_kb_program_source FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL,
    CONSTRAINT uq_kb_program UNIQUE (faculty_id, name_folded),
    INDEX idx_kb_program_name (name_folded)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kb_courses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    faculty_id INT NOT NULL,
    program_id INT NULL,
    course_code VARCHAR(50) NULL COMMENT 'e.g. CSC10004; NULL when the page lists only the name',
    name VARCHAR(255) NOT NULL,
    name_folded VARCHAR(255) NOT NULL,
    credits DECIMAL(3, 1) NULL,
    description TEXT NULL,
    source_id INT NULL,
    review_status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT chk_kb_course_credits CHECK (credits IS NULL OR credits >= 0),
    CONSTRAINT fk_kb_course_faculty FOREIGN KEY (faculty_id) REFERENCES kb_faculties(id) ON DELETE CASCADE,
    CONSTRAINT fk_kb_course_program FOREIGN KEY (program_id) REFERENCES kb_programs(id) ON DELETE SET NULL,
    CONSTRAINT fk_kb_course_source FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL,
    CONSTRAINT uq_kb_course UNIQUE (faculty_id, name_folded, course_code),
    INDEX idx_kb_course_name (name_folded),
    INDEX idx_kb_course_code (course_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS kb_course_lecturers (
    course_id INT NOT NULL,
    lecturer_id INT NOT NULL,
    semester VARCHAR(20) NOT NULL DEFAULT '' COMMENT 'e.g. 2026-1; empty = not stated',
    source_id INT NULL,
    review_status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    PRIMARY KEY (course_id, lecturer_id, semester),
    CONSTRAINT fk_kb_cl_course FOREIGN KEY (course_id) REFERENCES kb_courses(id) ON DELETE CASCADE,
    CONSTRAINT fk_kb_cl_lecturer FOREIGN KEY (lecturer_id) REFERENCES kb_lecturers(id) ON DELETE CASCADE,
    CONSTRAINT fk_kb_cl_source FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL,
    INDEX idx_kb_cl_lecturer (lecturer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. ACHIEVEMENTS (a person's or a faculty's)

CREATE TABLE IF NOT EXISTS kb_achievements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lecturer_id INT NULL,
    faculty_id INT NULL,
    kind ENUM('AWARD', 'PUBLICATION', 'RESEARCH', 'OTHER') NOT NULL DEFAULT 'OTHER',
    year SMALLINT NULL,
    title VARCHAR(500) NOT NULL,
    details TEXT NULL,
    source_id INT NULL,
    review_status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_kb_ach_owner CHECK (lecturer_id IS NOT NULL OR faculty_id IS NOT NULL),
    CONSTRAINT chk_kb_ach_year CHECK (year IS NULL OR year BETWEEN 1900 AND 2100),
    CONSTRAINT fk_kb_ach_lecturer FOREIGN KEY (lecturer_id) REFERENCES kb_lecturers(id) ON DELETE CASCADE,
    CONSTRAINT fk_kb_ach_faculty FOREIGN KEY (faculty_id) REFERENCES kb_faculties(id) ON DELETE CASCADE,
    CONSTRAINT fk_kb_ach_source FOREIGN KEY (source_id) REFERENCES kb_sources(id) ON DELETE SET NULL,
    INDEX idx_kb_ach_lecturer (lecturer_id, year),
    INDEX idx_kb_ach_faculty (faculty_id, year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. SEED: the four faculties whose websites are crawled (hcmus.edu.vn itself is the university, not a faculty)

INSERT IGNORE INTO kb_faculties (site_id, name, name_folded, short_name, home_url) VALUES
    ('fit',       'Khoa Công nghệ Thông tin',            'khoa cong nghe thong tin',            'FIT',  'https://www.fit.hcmus.edu.vn/'),
    ('fbb',       'Khoa Sinh học - Công nghệ Sinh học',  'khoa sinh hoc - cong nghe sinh hoc',  'FBB',  'https://fbb.hcmus.edu.vn/'),
    ('chemistry', 'Khoa Hóa học',                        'khoa hoa hoc',                        NULL,   'https://chemistry.hcmus.edu.vn/'),
    ('math',      'Khoa Toán - Tin học',                 'khoa toan - tin hoc',                 NULL,   'https://www.math.hcmus.edu.vn/');
