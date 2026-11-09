# [pic: khoi] academic knowledge base orm tables kb_* (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
"""
SQLAlchemy models for the SEARCH-ENGINE schema. They live on their OWN declarative base, separate from
`models.Base` (the scheduling schema), so the two schemas can never be mixed by accident.
The SQL file is the authority for the real MySQL tables; a test checks that these models list the same columns.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class KbBase(DeclarativeBase):
    pass


REVIEW = ("PENDING", "APPROVED", "REJECTED")


def _review() -> Mapped[str]:
    return mapped_column(Enum(*REVIEW, name="kb_review_status"), nullable=False, default="PENDING", server_default="PENDING")


class KbSource(KbBase):
    __tablename__ = "kb_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(String(30), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String(500))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    markdown_file: Mapped[str | None] = mapped_column(String(255))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class KbFaculty(KbBase):
    __tablename__ = "kb_faculties"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_folded: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(50))
    home_url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("kb_sources.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class KbDepartment(KbBase):
    __tablename__ = "kb_departments"
    __table_args__ = (UniqueConstraint("faculty_id", "name_folded", name="uq_kb_dept"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("kb_faculties.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_folded: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("kb_sources.id", ondelete="SET NULL"))
    review_status: Mapped[str] = _review()
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class KbLecturer(KbBase):
    __tablename__ = "kb_lecturers"
    __table_args__ = (UniqueConstraint("faculty_id", "name_folded", name="uq_kb_lecturer"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("kb_faculties.id", ondelete="CASCADE"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("kb_departments.id", ondelete="SET NULL"))
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_folded: Mapped[str] = mapped_column(String(255), nullable=False)
    academic_title: Mapped[str | None] = mapped_column(String(50))
    position: Mapped[str | None] = mapped_column(String(255))
    bio: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(String(500))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("kb_sources.id", ondelete="SET NULL"))
    review_status: Mapped[str] = _review()
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class KbProgram(KbBase):
    __tablename__ = "kb_programs"
    __table_args__ = (UniqueConstraint("faculty_id", "name_folded", name="uq_kb_program"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("kb_faculties.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_folded: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("kb_sources.id", ondelete="SET NULL"))
    review_status: Mapped[str] = _review()
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class KbCourse(KbBase):
    __tablename__ = "kb_courses"
    __table_args__ = (UniqueConstraint("faculty_id", "name_folded", "course_code", name="uq_kb_course"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("kb_faculties.id", ondelete="CASCADE"), nullable=False)
    program_id: Mapped[int | None] = mapped_column(ForeignKey("kb_programs.id", ondelete="SET NULL"))
    course_code: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_folded: Mapped[str] = mapped_column(String(255), nullable=False)
    credits: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    description: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("kb_sources.id", ondelete="SET NULL"))
    review_status: Mapped[str] = _review()
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class KbCourseLecturer(KbBase):
    __tablename__ = "kb_course_lecturers"
    course_id: Mapped[int] = mapped_column(ForeignKey("kb_courses.id", ondelete="CASCADE"), primary_key=True)
    lecturer_id: Mapped[int] = mapped_column(ForeignKey("kb_lecturers.id", ondelete="CASCADE"), primary_key=True)
    semester: Mapped[str] = mapped_column(String(20), primary_key=True, default="", server_default="")
    source_id: Mapped[int | None] = mapped_column(ForeignKey("kb_sources.id", ondelete="SET NULL"))
    review_status: Mapped[str] = _review()


class KbAchievement(KbBase):
    __tablename__ = "kb_achievements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lecturer_id: Mapped[int | None] = mapped_column(ForeignKey("kb_lecturers.id", ondelete="CASCADE"))
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("kb_faculties.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Enum("AWARD", "PUBLICATION", "RESEARCH", "OTHER", name="kb_achievement_kind"), nullable=False, default="OTHER")
    year: Mapped[int | None] = mapped_column(SmallInteger)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("kb_sources.id", ondelete="SET NULL"))
    review_status: Mapped[str] = _review()
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
