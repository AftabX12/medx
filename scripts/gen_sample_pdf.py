"""Generate a sample cardiology lab report PDF for testing upload + extraction.

Usage: .venv/bin/python -m scripts.gen_sample_pdf [output_path]
"""

from __future__ import annotations

import sys
from pathlib import Path

LINES = [
    "CARDIOLOGY CLINIC - LIPID PANEL REPORT",
    "",
    "Patient: Aftab Testpatient          MRN: CARD-2026-0042",
    "DOB: 1978-03-14                     Collected: 2026-04-10",
    "Ordering Provider: Dr. A. Khan      Reported: 2026-04-11",
    "",
    "RESULTS (fasting, serum):",
    "  Total Cholesterol      218 mg/dL   (desirable < 200)  HIGH",
    "  LDL Cholesterol        142 mg/dL   (optimal    < 100) HIGH",
    "  HDL Cholesterol         38 mg/dL   (low        < 40)  LOW",
    "  Triglycerides          189 mg/dL   (normal    < 150)  HIGH",
    "  Non-HDL Cholesterol    180 mg/dL   (goal       < 130) HIGH",
    "  Lp(a)                   46 nmol/L  (normal     < 75)",
    "",
    "INTERPRETATION:",
    "  Mixed dyslipidemia with elevated LDL-C and triglycerides and",
    "  low HDL-C. ASCVD 10-year risk estimated at 9.4% (intermediate).",
    "  Recommend high-intensity statin + lifestyle modification.",
    "",
    "Next lipid panel in 12 weeks.",
]


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_content_stream(lines: list[str]) -> bytes:
    parts = ["BT", "/F1 11 Tf", "14 TL", "72 740 Td"]
    for i, line in enumerate(lines):
        if i == 0:
            parts.append(f"({_escape(line)}) Tj")
        else:
            parts.append("T*")
            if line:
                parts.append(f"({_escape(line)}) Tj")
    parts.append("ET")
    return ("\n".join(parts)).encode("latin-1")


def build_pdf(lines: list[str]) -> bytes:
    content_stream = _build_content_stream(lines)
    content_obj = (
        b"<</Length " + str(len(content_stream)).encode()
        + b">>\nstream\n" + content_stream + b"\nendstream"
    )
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        content_obj,
        b"<</Type/Font/Subtype/Type1/BaseFont/Courier>>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (
        f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return pdf


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_lipid_panel.pdf")
    out.write_bytes(build_pdf(LINES))
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
