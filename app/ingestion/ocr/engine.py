"""OCR engine protocol and result types shared across engine implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

OCRStatus = Literal["ok", "no_text", "failed", "unsupported"]


@dataclass
class OCRPage:
    page_num: int
    text: str
    confidence: float | None = None


@dataclass
class OCRResult:
    text: str
    pages: list[OCRPage] = field(default_factory=list)
    engine: str = ""
    status: OCRStatus = "ok"
    error: str | None = None


class OCREngine(Protocol):
    name: str

    def supports(self, mime: str) -> bool: ...

    async def extract(self, data: bytes, mime: str) -> OCRResult: ...
