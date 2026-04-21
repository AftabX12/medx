"""Document type taxonomy shared across classify + router."""

from __future__ import annotations

from enum import StrEnum


class DocType(StrEnum):
    LAB_PANEL = "lab_panel"
    IMAGING_REPORT = "imaging_report"
    DISCHARGE_SUMMARY = "discharge_summary"
    MED_LIST = "med_list"
    HISTORY_PHYSICAL = "history_physical"
    OTHER = "other"
