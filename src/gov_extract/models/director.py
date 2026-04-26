"""Director and sub-models for board governance data."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CommitteeAttendance(BaseModel):
    """Attendance record for a single committee."""

    model_config = ConfigDict(extra="forbid")

    committee_name: str
    meetings_attended: int
    meetings_scheduled: int
    attendance_pct: float
    is_chair: bool = False


class BiographicalDetails(BaseModel):
    """Biographical and professional background of a director."""

    model_config = ConfigDict(extra="forbid")

    full_name: str
    post_nominals: str | None = None
    age: int | None = None
    age_band: str | None = None
    nationality: str | None = None
    qualifications: list[str] = []
    expertise_areas: list[str] = []
    career_summary: str | None = None
    other_directorships: list[str] = []


class BoardRoleDetails(BaseModel):
    """Board role, independence, tenure, and committee information."""

    model_config = ConfigDict(extra="forbid")

    designation: Literal["Executive Director", "Non-Executive Director", "Chair"]
    board_role: str
    independence_status: Literal[
        "Independent",
        "Not Independent",
        "Chair (independent on appointment)",
        "N/A (Executive)",
    ]
    year_joined_board: int | None = None
    date_joined_board: str | None = None
    tenure_years: float | None = None
    year_end_status: str
    committee_memberships: list[str] = []
    committee_chair_of: list[str] = []
    special_roles: list[str] = []


class AttendanceDetails(BaseModel):
    """Board and committee meeting attendance."""

    model_config = ConfigDict(extra="forbid")

    board_meetings_attended: int | None = None
    board_meetings_scheduled: int | None = None
    board_attendance_pct: float | None = None
    committee_attendance: list[CommitteeAttendance] = []
    attendance_notes: str | None = None


class Director(BaseModel):
    """Complete director record combining all sub-models."""

    model_config = ConfigDict(extra="forbid")

    biographical: BiographicalDetails
    board_role: BoardRoleDetails
    attendance: AttendanceDetails
