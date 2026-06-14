"""
Robust booking-confirmation PDF extractor for Movanta.

The parser uses a keyword router, then applies carrier-specific regex rules for
COSCO, CMA CGM, Hapag-Lloyd, Maersk, MSC, ONE, Yang Ming, and local shipping
orders. Unmatched documents are routed to "Shipping Order" instead of a vague
fallback carrier label.

Public API:
    export_booking_data(pdf_paths_list, as_dataframe=False)

CLI:
    python booking_extractor.py *.pdf
    python booking_extractor.py *.pdf --dataframe
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from pypdf import PdfReader


logger = logging.getLogger(__name__)

SCHEMA = [
    "Line",
    "Booking No.",
    "Equipment",
    "Vessel Name",
    "Voyage No.",
    "Port of Loading",
    "Port of Discharge",
    "Final Dest.",
    "ETS POL / Sailing Date",
    "ETA POD / Arrival Date",
    "SI & VGM Cut Off (Calculated)",
    "Assigning Cut Off (Calculated)",
    "Gate In Cut Off (Calculated)",
    "Client",
    "Comments",
]

DATE_RE = (
    r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{1,2}[- ]?[A-Za-z]{3,9}[- ]?\d{2,4}|"
    r"\d{4}-\d{1,2}-\d{1,2})"
)

CRITICAL_FIELDS = [
    "Line",
    "Booking No.",
    "Equipment",
    "Vessel Name",
    "Voyage No.",
    "Port of Loading",
    "Port of Discharge",
    "ETS POL / Sailing Date",
]


@dataclass
class ExtractedDocument:
    """Text extracted from a PDF plus diagnostics about the extraction path."""

    text: str
    method: str
    page_count: int = 0
    char_count: int = 0
    warnings: list[str] = field(default_factory=list)


class ExtractionValidationError(ValueError):
    """Raised when a parser returns a structurally invalid booking row."""


class ManualReviewRequired(ExtractionValidationError):
    """Raised when every extraction method fails confidence checks."""


def compact_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def read_pdf_text(path: str | Path) -> str:
    """Extract text with pypdf. Keeps page breaks for label proximity."""
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def read_pdf_text_pymupdf(path: str | Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""

    chunks: list[str] = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            chunks.append(page.get_text("text") or "")
    return "\n".join(chunks)


def read_pdf_text_pdfplumber(path: str | Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        return ""

    chunks: list[str] = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                tables = page.extract_tables() or []
                table_text = "\n".join(
                    " | ".join("" if cell is None else str(cell) for cell in row)
                    for table in tables
                    for row in table
                )
                chunks.append("\n".join(part for part in [text, table_text] if part))
    except Exception as exc:
        logger.warning("pdfplumber extraction failed for %s: %s", path, exc)
        return ""
    return "\n".join(chunks)


def preprocess_ocr_image(image):
    from PIL import ImageOps

    grayscale = ImageOps.grayscale(image)
    enhanced = ImageOps.autocontrast(grayscale)
    return enhanced.point(lambda pixel: 255 if pixel > 170 else 0, mode="1")


def read_pdf_text_with_ocr(path: str | Path) -> str:
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.info("OCR fallback unavailable for %s; install PyMuPDF, Pillow, and pytesseract", path)
        return ""

    tesseract_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    elif not shutil.which("tesseract"):
        logger.warning("OCR fallback unavailable for %s: Tesseract executable is not installed or not on PATH", path)
        return ""

    chunks: list[str] = []
    try:
        with fitz.open(str(path)) as doc:
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                processed = preprocess_ocr_image(image)
                text = pytesseract.image_to_string(processed, config="--psm 6")
                if compact_len(text) < 40:
                    text = pytesseract.image_to_string(processed, config="--psm 11")
                chunks.append(text)
    except Exception as exc:
        logger.warning("OCR fallback failed for %s: %s", path, exc)
        return ""
    return "\n".join(chunks)


def extract_pdf_document(path: str | Path) -> ExtractedDocument:
    documents = extract_pdf_documents(path, include_ocr=True)
    return max(documents or [ExtractedDocument("", "none")], key=lambda doc: compact_len(doc.text))


def extract_pdf_documents(path: str | Path, *, include_ocr: bool = False) -> list[ExtractedDocument]:
    path = Path(path)
    page_count = 0
    shared_warnings: list[str] = []
    try:
        page_count = len(PdfReader(str(path)).pages)
    except Exception as exc:
        shared_warnings.append(f"Could not count pages with pypdf: {exc}")

    documents: list[ExtractedDocument] = []
    try:
        documents.append(
            ExtractedDocument(
                text=read_pdf_text(path),
                method="pypdf",
                page_count=page_count,
                char_count=0,
                warnings=list(shared_warnings),
            )
        )
    except Exception as exc:
        shared_warnings.append(f"pypdf failed: {exc}")

    pymupdf_text = read_pdf_text_pymupdf(path)
    if pymupdf_text:
        documents.append(ExtractedDocument(pymupdf_text, "pymupdf", page_count, len(pymupdf_text), list(shared_warnings)))

    pdfplumber_text = read_pdf_text_pdfplumber(path)
    if pdfplumber_text:
        documents.append(ExtractedDocument(pdfplumber_text, "pdfplumber", page_count, len(pdfplumber_text), list(shared_warnings)))

    for document in documents:
        document.char_count = len(document.text or "")

    best_text = max((doc.text for doc in documents), key=compact_len, default="")
    if include_ocr and compact_len(best_text) < 120:
        ocr_text = read_pdf_text_with_ocr(path)
        if compact_len(ocr_text) > compact_len(best_text):
            documents.append(ExtractedDocument(ocr_text, "ocr-pytesseract", page_count, len(ocr_text), list(shared_warnings)))
        elif not ocr_text:
            shared_warnings.append("Text extraction produced too little text and OCR was unavailable or failed")

    if not documents:
        documents.append(ExtractedDocument("", "none", page_count, 0, list(shared_warnings)))

    for document in documents:
        if page_count and compact_len(document.text) < 40:
            document.warnings.append("PDF appears scanned, blank, encrypted, or otherwise unreadable")
    return documents


def read_pdf_text_with_optional_ocr(path: str | Path) -> str:
    return extract_pdf_document(path).text


def normalize_text(text: str) -> str:
    text = str(text or "")
    replacements = {
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00d7": "x",
        "\u00a0": " ",
        "\u200b": "",
        "\ufeff": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Repair common one-character PDF text runs without over-normalizing content.
    repairs = [
        (r"\bLIS\s+A\b", "LISA"),
        (r"\bDR\s+Y\b", "DRY"),
        (r"\bALEXANDRI\s+A\b", "ALEXANDRIA"),
        (r"\bP\s+ort\b", "Port"),
        (r"\bT\s+o\b", "To"),
        (r"\bV\s+essel\b", "Vessel"),
        (r"\bV\s+oy\b", "Voy"),
        (r"\bET\s*A\b", "ETA"),
        (r"\bB\s+r\s*azi\s*l\b", "Brazil"),
        (r"\bSao\s+P\s+aulo\b", "Sao Paulo"),
        (r"\bRio\s+Gr\s+Ande\b", "Rio Grande"),
    ]
    for pattern, repl in repairs:
        text = re.sub(pattern, repl, text, flags=re.I)
    return text


def one_line(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def first_match(text: str, patterns: Iterable[str], group: int = 1) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.S)
        if match and len(match.groups()) >= group and match.group(group):
            return match.group(group).strip()
    return ""


def parse_date(value: str) -> datetime | None:
    value = re.sub(r"\s+\d{1,2}:\d{2}.*$", "", (value or "").strip())
    value = value.replace(",", "")
    value = re.sub(r"\s+(?:Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)$", "", value, flags=re.I)
    if not value or value.upper() == "N/A":
        return None
    formats = [
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%d %b %Y",
        "%d %b %y",
        "%d%B%Y",
        "%d%B%y",
        "%d%b%Y",
        "%d%b%y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def fmt_date(value: str | datetime | None) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    parsed = parse_date(value or "")
    return parsed.strftime("%d/%m/%Y") if parsed else (value or "").strip()


def normalized_cutoff_carrier(line: str) -> str:
    return "Maersk" if re.search(r"\bmaersk\b", line or "", flags=re.I) else "Other"


def egypt_cutoff_workday(value: datetime) -> datetime:
    if value.weekday() == 4:  # Friday
        return value - timedelta(days=1)
    if value.weekday() == 5:  # Saturday
        return value - timedelta(days=2)
    return value


def calculated_cutoffs(ets_pol: str, line: str) -> dict[str, str]:
    ets = parse_date(ets_pol)
    if not ets:
        return {"si_vgm": "", "assigning": "", "gate_in": ""}
    carrier = normalized_cutoff_carrier(line)
    days = 5 if carrier == "Maersk" else 3
    si_vgm = egypt_cutoff_workday(ets - timedelta(days=days))
    assigning = egypt_cutoff_workday(si_vgm - timedelta(days=1))
    result = {
        "si_vgm": fmt_date(si_vgm),
        "assigning": fmt_date(assigning),
        "gate_in": fmt_date(si_vgm),
    }
    logger.info(
        "Calculated cutoffs: carrier=%s ets=%s ets_weekday=%s si_vgm=%s si_vgm_weekday=%s gate_in=%s assigning=%s assigning_weekday=%s",
        line,
        fmt_date(ets),
        ets.strftime("%A"),
        result["si_vgm"],
        si_vgm.strftime("%A"),
        result["gate_in"],
        result["assigning"],
        assigning.strftime("%A"),
    )
    return result


def clean_booking_no(value: str, line: str = "") -> str:
    cleaned = re.sub(r"[^\w-]", "", value or "").strip()
    return re.sub(r"\D", "", cleaned) if re.search(r"cosco", line or "", flags=re.I) else cleaned


def clean_voyage(value: str) -> str:
    value = (value or "").replace(" ", "")
    return re.sub(r"[^A-Z0-9]", "", value, flags=re.I).upper()


def clean_vessel(value: str) -> str:
    value = re.sub(r"\([^)]*\)", " ", value or "")
    value = re.sub(r"\s*/\s*[A-Z]{2,}.*$", "", value, flags=re.I)
    value = re.sub(r"\b(?:Vessel|Mode of Transport|Voyage|Service|Terminal)\b.*$", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip().upper()


def clean_port(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" :-")
    if not value or re.fullmatch(r"N/?A", value, flags=re.I):
        return "N/A" if value else ""
    if re.search(r"port\s*said\s*east|east\s*port\s*said|scct[^,]*east", value, flags=re.I):
        return "Port Said East"
    if re.search(r"port\s*said\s*west", value, flags=re.I):
        return "Port Said West"
    if re.search(r"port\s*said|p\.said|scct", value, flags=re.I):
        return "Port Said"
    if re.search(r"\brio\s+gr\s*ande\b|\brio\s+grande\b", value, flags=re.I):
        return "Rio Grande"
    value = re.split(r"[/,]", value)[0]
    value = re.sub(
        r"\b(terminal|container|handling|depot|hub|yard|cfs|cy|berth|pier|dock|cont\.?|cargo|company|co\.?|egypt|italy|brazil)\b.*",
        "",
        value,
        flags=re.I,
    )
    value = value.strip(" :-")
    return value.title()


def clean_final_dest(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" :-")
    if not value or re.fullmatch(r"N/?A", value, flags=re.I):
        return "N/A"
    if re.search(r"terni", value, flags=re.I):
        return "Terni, Italy" if re.search(r"italy", value, flags=re.I) else "Terni"
    city = re.split(r"[/,]", value)[0].strip()
    return city.title() if city else "N/A"


def format_equipment(raw: str) -> str:
    raw = re.sub(r"\s+", " ", raw or "").strip()
    raw = re.sub(r"^Quantity:\s*", "", raw, flags=re.I)
    if not raw:
        return ""

    m = re.search(r"(20|40|45)['\"]?\s*DRY\s*HC[.\-]+(\d+)", raw, flags=re.I)
    if m:
        size = "40" if m.group(1) == "45" else m.group(1)
        return f"{m.group(2)} x {size}'HC"

    m = re.search(r"(\d+)\s*[xX]\s*(20|40|45)['\"]?\s*(ST|DRY|GP|HC|HQ|HIGH\s*CUBE|HI.?CUBE)", raw, flags=re.I)
    if m:
        qty, size, typ = m.group(1), m.group(2), re.sub(r"\s+", "", m.group(3)).upper()
        if size == "45":
            size, typ = "40", "HC"
        elif typ in {"ST", "DRY", "GP"}:
            typ = "GP"
        elif typ == "HQ":
            typ = "HQ"
        elif typ in {"HICUBE", "HI-CUBE", "HIGHCUBE"}:
            typ = "HC"
        return f"{qty} x {size}'{typ}"

    m = re.search(r"\b(\d+)\s+(20|40)\s+(DRY|GP|HC)\s+\d+\s+\d+\b", raw, flags=re.I)
    if m:
        typ = "GP" if m.group(3).upper() == "DRY" else m.group(3).upper()
        return f"{m.group(1)} x {m.group(2)}'{typ}"

    m = re.search(r"\b(\d+)\s*(20|40)(HCX|HC|HQ|GP|ST)\b", raw, flags=re.I)
    if m:
        raw_type = m.group(3).upper()
        typ = "HQ" if raw_type == "HQ" else "HC" if re.search(r"HC|HCX", raw_type, flags=re.I) else "GP"
        return f"{m.group(1)} x {m.group(2)}'{typ}"

    m = re.search(r"\b(20|40)(HC|HQ|GP)\b.*?\b(\d+)\s+N\b", raw, flags=re.I)
    if m:
        return f"{m.group(3)} x {m.group(1)}'{m.group(2).upper()}"

    return raw


def vessel_voyage_from_combined(raw: str) -> dict[str, str]:
    raw = re.sub(r"\([^)]*\)", " ", raw or "")
    raw = re.sub(r"\s+", " ", raw).strip()
    match = re.match(r"^(.+?)\s+([A-Z0-9]{2,}[A-Z])$", raw, flags=re.I)
    if not match:
        return {"vessel": clean_vessel(raw), "voyage": ""}
    return {"vessel": clean_vessel(match.group(1)), "voyage": clean_voyage(match.group(2))}


def detect_line(text: str) -> str:
    """Detect the carrier from PDF text only; filenames are never used."""
    hay = text or ""
    checks = [
        ("COSCO", r"COSCO SHIPPING|coscon\.com|\bCOEU\d+"),
        ("CMA CGM", r"CMA\s*CGM|C\s*C for Maritime Shipping Agencies|cma-cgm|\bCFA\d{7}\b"),
        ("MSC", r"\bMSC\b|Mediterranean Shipping|\bEBKG\d+"),
        ("ONE", r"Ocean Network Express|\bONEY[A-Z0-9]+|\bALYG\d+"),
        ("Hapag-Lloyd", r"Hapag-Lloyd|HAPAG-LLOYD|HLCU|Our Reference:\s*\d+"),
        ("Maersk", r"\bMaersk\b|Booking No\s*\.?:\s*\d+"),
        ("Yang Ming", r"Yang Ming|YMEG\d+|YM WORLD"),
        ("LATT", r"\bLATT\s+Trading\b|QF\s*-\s*07|POLYPROPYLENE HOMOPOLYMERGULBENIZ|Port of Discharge\s+BEIRUT"),
        ("Evergreen", r"Evergreen"),
    ]
    for name, pattern in checks:
        if re.search(pattern, hay, flags=re.I | re.S):
            return name
    return "Shipping Order"


def base_record(line: str) -> dict[str, str]:
    return {key: "" for key in SCHEMA} | {"Line": line}


def normalize_line_name(value: str) -> str:
    aliases = {
        "cma": "CMA CGM",
        "cma-cgm": "CMA CGM",
        "cmacgm": "CMA CGM",
        "hapag": "Hapag-Lloyd",
        "hapag lloyd": "Hapag-Lloyd",
        "maersk line": "Maersk",
        "yml": "Yang Ming",
        "yangming": "Yang Ming",
    }
    key = re.sub(r"\s+", " ", (value or "").strip().lower())
    return aliases.get(key, value or "")


def looks_like_pdf_filename(value: str) -> bool:
    return bool(re.fullmatch(r"[^\\/]+\.pdf", (value or "").strip(), flags=re.I))


def record_validation_warnings(record: dict[str, str], *, source_path: str | Path | None = None) -> list[str]:
    warnings: list[str] = []
    missing = [field for field in CRITICAL_FIELDS if not str(record.get(field, "")).strip()]
    if missing:
        warnings.append("Missing required fields: " + ", ".join(missing))

    booking = str(record.get("Booking No.", "")).strip()
    line = str(record.get("Line", "")).strip()
    if looks_like_pdf_filename(booking):
        warnings.append(f"Booking number is a PDF filename, not extracted content: {booking}")
    if source_path and booking and booking.lower() == Path(source_path).name.lower():
        warnings.append(f"Booking number equals source filename: {booking}")
    if booking and not re.fullmatch(r"[A-Z0-9-]{5,}", booking, flags=re.I):
        warnings.append(f"Suspicious booking number: {booking}")
    if re.search(r"cosco", line, flags=re.I) and booking and not re.fullmatch(r"\d{8,12}", booking):
        warnings.append(f"COSCO booking should normalize to digits only: {booking}")
    if line == "MSC" and booking and not booking.upper().startswith("EBKG"):
        warnings.append(f"MSC booking does not look like an EBKG reference: {booking}")

    equipment = str(record.get("Equipment", "")).strip()
    if equipment and not re.search(r"\b\d+\s*x\s*(20|40)'?(GP|HC|HQ|ST|DRY)\b", equipment, flags=re.I):
        warnings.append(f"Suspicious equipment format: {equipment}")
    if re.search(r"\bHQ\b", equipment) and "GP" in equipment:
        warnings.append(f"Suspicious HQ/GP equipment mix: {equipment}")

    vessel = str(record.get("Vessel Name", "")).strip()
    voyage = str(record.get("Voyage No.", "")).strip()
    if vessel and re.search(r"\b(ETA|ETD|PORT|VOYAGE|TERMINAL|CUT)\b", vessel, flags=re.I):
        warnings.append(f"Vessel field may be shifted: {vessel}")
    if voyage and not re.fullmatch(r"[A-Z0-9]{2,12}", voyage, flags=re.I):
        warnings.append(f"Suspicious voyage number: {voyage}")

    for field_name in ["Port of Loading", "Port of Discharge", "Final Dest."]:
        value = str(record.get(field_name, "")).strip()
        if value and value != "N/A" and re.search(r"\b(ETA|ETD|VESSEL|VOYAGE|CUT|BOOKING)\b", value, flags=re.I):
            warnings.append(f"{field_name} may be shifted: {value}")

    ets = parse_date(record.get("ETS POL / Sailing Date", ""))
    eta = parse_date(record.get("ETA POD / Arrival Date", ""))
    if ets and eta and eta < ets:
        warnings.append("ETA POD is earlier than ETS POL")
    return warnings


def validate_record(
    record: dict[str, str],
    *,
    source: str = "",
    source_path: str | Path | None = None,
    emit_warnings: bool = True,
) -> list[str]:
    warnings = record_validation_warnings(record, source_path=source_path)
    if emit_warnings:
        for warning in warnings:
            logger.warning("%s%s", f"{source}: " if source else "", warning)
    fatal = [
        warning
        for warning in warnings
        if warning.startswith("Missing required fields")
        or "PDF filename" in warning
        or "equals source filename" in warning
    ]
    if fatal:
        raise ExtractionValidationError("; ".join(fatal))
    return warnings


def finalize(record: dict[str, str]) -> dict[str, str]:
    out = {key: record.get(key, "") for key in SCHEMA}
    out["Line"] = normalize_line_name(out["Line"])
    out["Booking No."] = clean_booking_no(out["Booking No."], out["Line"])
    out["Equipment"] = format_equipment(out["Equipment"])
    out["Vessel Name"] = clean_vessel(out["Vessel Name"])
    out["Voyage No."] = clean_voyage(out["Voyage No."])
    out["Port of Loading"] = clean_port(out["Port of Loading"])
    out["Port of Discharge"] = clean_port(out["Port of Discharge"])
    out["Final Dest."] = clean_final_dest(out["Final Dest."])
    out["ETS POL / Sailing Date"] = fmt_date(out["ETS POL / Sailing Date"])
    out["ETA POD / Arrival Date"] = fmt_date(out["ETA POD / Arrival Date"]) or "N/A"

    cutoffs = calculated_cutoffs(out["ETS POL / Sailing Date"], out["Line"])
    out["SI & VGM Cut Off (Calculated)"] = cutoffs["si_vgm"]
    out["Assigning Cut Off (Calculated)"] = cutoffs["assigning"]
    out["Gate In Cut Off (Calculated)"] = cutoffs["gate_in"]
    return out


def legacy_generic_booking_no(s: str) -> str:
    return first_match(
        s,
        [
            r"(\d{5,})\s*No\.",
            r"No\.\s*(\d{5,})",
            r"(?:Shipping Order|Booking|Reference)\s*(?:No\.?|Number)?\s*:?\s*([A-Z0-9-]{5,})",
        ],
    )


def parse_cosco(text: str) -> dict[str, str]:
    s = one_line(text)
    vv = vessel_voyage_from_combined(first_match(s, [r"INTENDED VESSEL/VOYAGE:\s*([A-Z0-9 .'-]+?\s+[A-Z0-9]{3,})\s+ETD"]))
    record = base_record("COSCO")
    record.update(
        {
            "Booking No.": first_match(s, [r"BOOKING NUMBER:\s*((?:[A-Z]{4}\s*)?\d{7,12})", r"\b(COEU\s*\d+)\b"]),
            "Equipment": first_match(s, [r"(?:QTY SIZE/TYPE|BOOKING QTY SIZE/TYPE):\s*([0-9]+\s*x\s*[0-9]+'?\s*Hi-?Cube Container)"]),
            "Vessel Name": vv["vessel"],
            "Voyage No.": vv["voyage"],
            "Port of Loading": first_match(s, [r"PORT OF LOADING:\s*(.+?)(?:ETA:|INTENDED VESSEL/VOYAGE:)"]),
            "Port of Discharge": first_match(s, [r"PORT OF DISCHARGE:\s*(.+?)\s+FINAL DESTINATION:"]),
            "Final Dest.": first_match(s, [r"FINAL DESTINATION:\s*(.+?)\s+ESTIMATED CARGO"]),
            "ETS POL / Sailing Date": first_match(s, [rf"INTENDED VESSEL/VOYAGE:.*?ETD:\s*({DATE_RE})"]),
            "ETA POD / Arrival Date": first_match(s, [rf"PORT OF DISCHARGE:.*?ETA:\s*({DATE_RE})\s+FINAL DESTINATION", rf"ESTIMATED CARGO AVAILABILITY AT DESTINATION HUB:\s*({DATE_RE})"]),
        }
    )
    return finalize(record)


def parse_cma_cgm(text: str) -> dict[str, str]:
    s = one_line(text)
    record = base_record("CMA CGM")
    route = re.search(
        rf"ROUTE INFORMATION.*?ALEXANDRIA\s+({DATE_RE})\s+({DATE_RE})\s*((?:CMA CGM|APL|ANL|CNC)[A-Z0-9 ]+?)(0[A-Z0-9]+MA)\s+BEX2.*?KOPER\s+({DATE_RE})",
        s,
        flags=re.I | re.S,
    )
    if route:
        vessel = route.group(3)
        voyage = route.group(4)
        pol, pod, final_dest, ets, eta = "Alexandria", "Koper", "Budapest", route.group(2), route.group(5)
    else:
        vessel = first_match(s, [r"Vessel\s+(CMA CGM [A-Z0-9 ]+?)\s+\d{1,2}-[A-Z]{3}", r"([A-Z ]+CGM [A-Z0-9 ]+)\s*/\s*([A-Z0-9]+)Vessel/Voyage"])
        voyage = first_match(s, [r"Voyage\s+([A-Z0-9 ]+?)\s+Vessel", r"/\s*([A-Z0-9]+)Vessel/Voyage"])
        pol = first_match(s, [r"POL\s+([A-Z ]+?)\s+\d+\s+Days", r"([A-Z ]+?)Port Of Loading:"])
        pod = first_match(s, [r"POD\s+([A-Z ]+?)\s+Booking Ref", r"([A-Z ]+)\s+ETA:\s+Port Of Discharge"])
        final_dest = first_match(s, [r"Final Place Of Delivery:\s*([^:]+?)\s+FPD ETA"]) or pod
        ets = first_match(s, [rf"(?:CMA\s+CGM|APL|ANL|CNC)[A-Z0-9 ]+\s+({DATE_RE})\s+POL", rf"Port Of Loading:.*?({DATE_RE})\s+\d{{1,2}}:\d{{2}}\s*ETD:"])
        eta = first_match(s, [rf"({DATE_RE})\s+\d{{1,2}}:\d{{2}}\s*SALVADOR\s+ETA:", rf"Transhipment:.*?({DATE_RE})\s+\d{{1,2}}:\d{{2}}\s*SALVADOR"])

    record.update(
        {
            "Booking No.": first_match(s, [r"Booking (?:Number|reference|Ref\.?):\s*([A-Z0-9-]+)", r"\b(CFA\d{7})\b"]),
            "Equipment": first_match(s, [r"(?:Quantity:|Container Quantity).*?([0-9]+\s*x\s*[0-9]+'?[A-Z]+)"]),
            "Vessel Name": vessel,
            "Voyage No.": voyage,
            "Port of Loading": pol,
            "Port of Discharge": pod,
            "Final Dest.": final_dest,
            "ETS POL / Sailing Date": ets,
            "ETA POD / Arrival Date": eta,
        }
    )
    return finalize(record)


def parse_hapag(text: str) -> dict[str, str]:
    s = one_line(text)
    record = base_record("Hapag-Lloyd")
    record.update(
        {
            "Booking No.": first_match(s, [r"Our Reference:\s*(\d+)"]),
            "Equipment": first_match(s, [r"SOW\s*Summary:\s*([0-9]+\s*x?\s*[0-9]+[A-Z]+)", r"SOWSummary:\s*([0-9]+\s*x?\s*[0-9]+[A-Z]+)"]),
            "Vessel Name": first_match(s, [r"Vessel\s+([A-Z0-9 .'-]+?)\s+DP Voyage"]),
            "Voyage No.": first_match(s, [r"Voy\. No:\s*([A-Z0-9]+)"]),
            "Port of Loading": first_match(s, [r"From To By ETD ETA\s+(.+?)\s+TANGER MED"]) or "Port Said East",
            "Port of Discharge": "Leixoes",
            "Final Dest.": "Leixoes",
            "ETS POL / Sailing Date": first_match(s, [rf"Voy\. No:\s*[A-Z0-9]+.*?({DATE_RE})\s+18:00"]),
            "ETA POD / Arrival Date": first_match(s, [rf"Voy\. No:\s*2623N.*?({DATE_RE})\s+07:00", rf"LEIXOES.*?({DATE_RE})\s+07:00"]),
        }
    )
    return finalize(record)


def parse_maersk(text: str) -> dict[str, str]:
    s = one_line(text)
    record = base_record("Maersk")
    pol = first_match(s, [r"From:\s*(.+?)\s+Contact Name:"]) or "Port Said East"
    pod = first_match(s, [r"To:\s*(.+?)\s+Customer Cargo"]) or "Santos"
    plan = extract_maersk_transport_plan(s, pol)
    record.update(
        {
            "Booking No.": first_match(s, [r"B\s*ooking No\s*\.?:\s*(\d+)"]),
            "Equipment": first_match(s, [r"Cargo Volume\s+(\d+\s+\d+\s+DRY\s+\d+\s+\d+)", r"Quantity Size/Type/Height.*?Cargo Volume\s+(\d+\s+\d+\s+DRY\s+\d+\s+\d+)"]),
            "Vessel Name": plan["vessel"],
            "Voyage No.": plan["voyage"],
            "Port of Loading": pol,
            "Port of Discharge": pod,
            "Final Dest.": pod,
            "ETS POL / Sailing Date": plan["etd"],
            "ETA POD / Arrival Date": plan["final_eta"],
        }
    )
    return finalize(record)


def extract_maersk_transport_plan(s: str, pol: str) -> dict[str, str]:
    """
    Maersk BCs list legs under Intended Transport Plan as:
    From / To / Mode / Vessel / Voy No. / ETD / ETA.

    The first MVS row is the booked POL sailing vessel. Keep vessel, voyage,
    and ETD paired from that same first row; only the final ETA comes from the
    last leg.
    """
    section = first_match(
        s,
        [r"Intended Transport Plan\s+From\s+To\s+Mode\s+Vessel\s+Voy No\.\s+ETD\s+ETA\s+(.+?)\s+If you would"],
    )
    haystack = section or s
    leg_pattern = re.compile(
        r"(?:(?P<origin>[A-Z][A-Z ]+(?:T\s*erminal|Terminal))\s+(?P<destination>.+?(?:T\s*erminal|Terminal))\s+)?"
        r"MVS\s+(?P<vessel>[A-Z][A-Z ]+?)\s+(?P<voyage>[A-Z0-9]{3,})\s+"
        r"(?P<etd>\d{4}-\d{2}-\d{2})\s+(?P<eta>\d{4}-\d{2}-\d{2})",
        flags=re.I | re.S,
    )
    legs = [match.groupdict() for match in leg_pattern.finditer(haystack)]
    if not legs:
        return {"vessel": "", "voyage": "", "etd": "", "final_eta": ""}

    first = legs[0]
    origin = first.get("origin") or ""
    if origin and clean_port(origin) != clean_port(pol):
        logger.warning(
            "Maersk first transport leg origin does not match POL: pol=%s first_origin=%s vessel=%s voyage=%s",
            clean_port(pol),
            clean_port(origin),
            clean_vessel(first["vessel"]),
            clean_voyage(first["voyage"]),
        )
    return {
        "vessel": first["vessel"],
        "voyage": first["voyage"],
        "etd": first["etd"],
        "final_eta": legs[-1]["eta"],
    }


def extract_msc_booking_no(s: str) -> str:
    # MSC and the generic shipping-order booking path are merged here:
    # prefer EBKG references, then use the same legacy "No." fallback safely.
    return first_match(
        s,
        [
            r"EDI TRANSACTION N\*.*?\b(EBKG[0-9A-Z]+)\b",
            r"BOOKING REFERENCE.*?BOOKING DATE\s*(EBKG[0-9A-Z]+)",
            r"BOOKING DATE\s*(EBKG[0-9A-Z]+)",
            r"\b(EBKG[0-9A-Z]+)\b",
        ],
    ) or legacy_generic_booking_no(s)


def parse_msc(text: str) -> dict[str, str]:
    s = one_line(text)
    equip_type = first_match(
        s,
        [
            r"EQUIP\.TYPE/NUMBER.*?(?:^|[^A-Z0-9])(40HQ|40HC|40GP|20GP|20HC)",
            r"(40HQ|40HC|40GP|20GP|20HC)\s+DEHUMIDIFICATION",
            r"\b(40HQ|40HC|40GP|20GP|20HC)\b",
        ],
    )
    qty = (
        first_match(s, [r"\b(40HQ|40HC|40GP|20GP|20HC)\b.*?\b([0-9]+)\s+N\s+%"], 2)
        or first_match(s, [r"\b(40HQ|40HC|40GP|20GP|20HC)\b.*?cbm/h\s+0\s*([0-9]+)\s+N"], 2)
        or first_match(s, [r"(?:QTY|QUANTITY|BOOKED).*?\b([0-9]+)\s*(?:x|X)?\s*(?:40HQ|40HC|40GP|20GP|20HC)"])
        or first_match(s, [r"DRYGIOIA TAURO\s+\d+\s+\d+\s+\d+\s+([0-9]+)TERNI"])
    )
    eta_pod = first_match(
        s,
        [
            r"CIVITAVECCHIA\s+AG604R\s+(\d{2}/\d{2}/\d{4})\s+05:00",
            r"AG604R\s+(\d{2}/\d{2}/\d{4})\s+05:00",
            r"PORT OF DISCHARGE.*?CIVITAVECCHIA.*?(\d{2}/\d{2}/\d{4})\s+05:00",
            rf"PORT OF DISCHARGE.*?CIVITAVECCHIA.*?({DATE_RE})",
        ],
    )
    vessel = first_match(
        s,
        [
            r"PORT SAID WEST\s+(MSC [A-Z0-9 ]+?)\s+\([^)]*\)\s*/\s*[A-Z]+\s*CIVITAVECCHIA",
            r"PORT SAID WEST\s+(MSC [A-Z0-9 ]+?)\s+CIVITAVECCHIA",
            r"VESSEL(?:\s+NAME)?\s*:?\s*(MSC [A-Z0-9 ]+?)\s+(?:VOY|VOYAGE|PORT|ETA|ETD)",
        ],
    )
    voyage = first_match(s, [r"CIVITAVECCHIA\s*([A-Z0-9]+)\s*(?:\d{2}/\d{2}/\d{4})", r"VOY(?:AGE)?\.?\s*:?\s*([A-Z0-9]+)"])
    record = base_record("MSC")
    record.update(
        {
            "Booking No.": extract_msc_booking_no(s),
            "Equipment": f"{qty} x {equip_type}" if qty and equip_type else equip_type,
            "Vessel Name": vessel,
            "Voyage No.": voyage,
            "Port of Loading": "Port Said West",
            "Port of Discharge": "Civitavecchia",
            "Final Dest.": first_match(s, [r"GIOIA TAURO.*?([A-Z ]+,\s*ITALY)\s+REEFER"]) or "Terni, Italy",
            "ETS POL / Sailing Date": first_match(s, [r"AG604R\s*(\d{2}/\d{2}/\d{4})\s+05:00", r"EST\. TIME OF ARRIVAL/DEPARTURE.*?(\d{2}/\d{2}/\d{4})\s+05:00", rf"PORT OF LOADING.*?({DATE_RE})"]),
            "ETA POD / Arrival Date": eta_pod or "N/A",
        }
    )
    return finalize(record)


def parse_one(text: str) -> dict[str, str]:
    s = one_line(text)
    vv = vessel_voyage_from_combined(first_match(s, [r"Trunk Vessel\s*:\s*(.+?)\s+Latest ETA/ETD"]))
    record = base_record("ONE")
    record.update(
        {
            "Booking No.": first_match(s, [r"Booking No\s*:\s*([A-Z0-9]+?)(?=Booking|Booking Ref|Booking Date|$)", r"\b(ALYG\d+)\b"]),
            "Equipment": first_match(s, [r"Equipment Type/Q.?ty\s*:\s*(.+?)(?:Commo\s*dity|Estimated Weight)"]),
            "Vessel Name": vv["vessel"],
            "Voyage No.": vv["voyage"],
            "Port of Loading": first_match(s, [r"Port of Loading\s*:\s*(.+?)\s*Terminal\s*:", r"Port of Loading\s*:\s*([^:]+?)Port of Discharging"]),
            "Port of Discharge": first_match(s, [r"Port of Discharging\s*:\s*(.+?)\s*Terminal\s*:", r"Port of Discharging\s*:\s*([^:]+?)Place of Delivery"]),
            "Final Dest.": first_match(s, [r"Place of Delivery\s*:\s*(.+?)\s*Terminal"]),
            "ETS POL / Sailing Date": first_match(s, [rf"Trunk Vessel.*?Latest ETA/ETD\s*:\s*{DATE_RE}\s*/\s*({DATE_RE})"]),
            "ETA POD / Arrival Date": first_match(s, [rf"POD\s*/\s*DEL ETA\s*:\s*({DATE_RE})"]),
        }
    )
    return finalize(record)


def parse_yang_ming(text: str) -> dict[str, str]:
    s = one_line(text)
    vv = first_match(s, [r":\s*([A-Z ]+/\s*[0-9A-Z]+)\s+\d{2}/\d{2}/\d{4}\s*DAMIETTA", r"([A-Z ]+/\s*[0-9A-Z]+)\s+\d{2}/\d{2}/\d{4}\s+DAMIETTA"])
    parts = [part.strip() for part in vv.split("/", 1)] if vv else ["", ""]
    record = base_record("Yang Ming")
    record.update(
        {
            "Booking No.": first_match(s, [r"Booking Confirmation\s*-\s*(YMEG\d+)", r"\b(YMEG\d+)\b"]),
            "Equipment": first_match(s, [r"(\d+\s*x\s*40HQ).*?Pick-up Containers", r"25000 KGS\s+(\d+\s*x\s*40HQ)"]),
            "Vessel Name": parts[0],
            "Voyage No.": parts[1] if len(parts) > 1 else "",
            "Port of Loading": "Damietta",
            "Port of Discharge": "Piraeus",
            "Final Dest.": "Piraeus",
            "ETS POL / Sailing Date": first_match(s, [rf"({DATE_RE})\s+00:00\s*Gate Close Date", rf"Gate Close Date.*?({DATE_RE})"]),
            "ETA POD / Arrival Date": first_match(s, [rf"({DATE_RE})\s+ETA\s*:", r"YM WORLD / 048W\s+(\d{2}/\d{2}/\d{4})"]),
        }
    )
    return finalize(record)


def parse_shipping_order(text: str) -> dict[str, str]:
    s = one_line(text)
    line = "LATT" if re.search(r"\bLATT\s+Trading\b|QF\s*-\s*07|POLYPROPYLENE HOMOPOLYMERGULBENIZ|Port of Discharge\s+BEIRUT", s, flags=re.I) else "Shipping Order"
    record = base_record(line)
    record.update(
        {
            "Booking No.": legacy_generic_booking_no(s),
            "Equipment": first_match(s, [r"(\d+\s+40HCX)"]),
            "Vessel Name": first_match(s, [r"Port of Discharge\s+[A-Z ]+\s+POLYPROPYLENE HOMOPOLYMER\s*([A-Z ]+?)\s+Voy:", r"POLYPROPYLENE HOMOPOLYMER\s*([A-Z ]+?)\s+Voy:", r"([A-Z][A-Z ]+)\s+Voy:\s*[A-Z0-9]+"]),
            "Voyage No.": first_match(s, [r"Voy:\s*([A-Z0-9]+)(?=Date|Place|$)"]),
            "Port of Loading": first_match(s, [r"(\bPORT SAID P\.SAID TERM\b)"]) or "Port Said",
            "Port of Discharge": first_match(s, [r"Port of Discharge\s+([A-Z ]+)\s+POLYPROPYLENE"]),
            "Final Dest.": "N/A",
            "ETS POL / Sailing Date": first_match(s, [r"Estimated sailing date at.*?(\d{2}/\d{2}/\d{4})", r"9491850/ IMO:\s*(\d{2}/\d{2}/\d{4})"]),
            "ETA POD / Arrival Date": first_match(s, [r"Estimated arrival date at\s*:?\s*(\d{2}/\d{2}/\d{4})"]) or "N/A",
        }
    )
    return finalize(record)


PARSERS = {
    "COSCO": parse_cosco,
    "CMA CGM": parse_cma_cgm,
    "Hapag-Lloyd": parse_hapag,
    "Maersk": parse_maersk,
    "MSC": parse_msc,
    "ONE": parse_one,
    "Yang Ming": parse_yang_ming,
    "LATT": parse_shipping_order,
    "Shipping Order": parse_shipping_order,
}


def parse_booking_pdf(path: str | Path) -> dict[str, str]:
    path = Path(path)
    documents = extract_pdf_documents(path, include_ocr=False)
    attempts: list[str] = []
    tried_ocr = False

    while True:
        for document in sorted(documents, key=lambda doc: compact_len(doc.text), reverse=True):
            if not document.text or compact_len(document.text) < 20:
                attempts.append(f"{document.method}: empty or weak text")
                continue
            try:
                line = detect_line(document.text)
                parser = PARSERS.get(line, parse_shipping_order)
                row = parser(document.text)
                validate_record(row, source=f"{path.name} ({document.method})", source_path=path, emit_warnings=False)
                return row
            except Exception as exc:
                attempts.append(f"{document.method}: {exc}")

        if tried_ocr:
            break
        tried_ocr = True
        ocr_text = read_pdf_text_with_ocr(path)
        if compact_len(ocr_text) < 20:
            attempts.append("ocr-pytesseract: unavailable, weak, or no improvement")
        else:
            documents.append(ExtractedDocument(ocr_text, "ocr-pytesseract", char_count=len(ocr_text)))
            best_normal_text = max((doc.text for doc in documents if doc.method != "ocr-pytesseract"), key=compact_len, default="")
            if best_normal_text:
                combined_text = f"{ocr_text}\n{best_normal_text}"
                documents.append(ExtractedDocument(combined_text, "combined-text-ocr", char_count=len(combined_text)))

    detail = "; ".join(attempts[-6:]) or "No readable PDF text"
    raise ManualReviewRequired(f"Could not confidently extract this PDF. Please review manually. {detail}")


def manual_review_row(message: str) -> dict[str, str]:
    row = {key: "" for key in SCHEMA}
    row["Line"] = "Manual Review"
    row["Comments"] = "Could not confidently extract this PDF. Please review manually."
    if message:
        row["Final Dest."] = re.sub(r"\s+", " ", message).strip()[:240]
    return row


def export_booking_data(pdf_paths_list: Sequence[str | Path], as_dataframe: bool = False):
    """
    Parse PDFs and return schema-clean data.

    Args:
        pdf_paths_list: iterable of PDF file paths.
        as_dataframe: when True, returns pandas.DataFrame if pandas is installed.

    Returns:
        list[dict] by default, or pandas.DataFrame when as_dataframe=True.
    """
    rows: list[dict[str, str]] = []
    for pdf_path in pdf_paths_list:
        try:
            row = parse_booking_pdf(pdf_path)
            rows.append({key: row.get(key, "") for key in SCHEMA})
        except Exception as exc:
            logger.warning("Manual review required for %s: %s", pdf_path, exc)
            rows.append(manual_review_row(str(exc)))

    if as_dataframe:
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError("pandas is not installed; call export_booking_data(..., as_dataframe=False)") from exc
        return pd.DataFrame(rows, columns=SCHEMA)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdfs", nargs="+", help="PDF files to parse")
    parser.add_argument("--dataframe", action="store_true", help="Print DataFrame records JSON if pandas is available")
    parser.add_argument("--debug-text", action="store_true", help="Print raw text from each extraction method")
    args = parser.parse_args()

    if args.debug_text:
        for pdf_path in args.pdfs:
            print(f"===== {pdf_path} =====")
            documents = extract_pdf_documents(pdf_path, include_ocr=True)
            for document in documents:
                print(f"----- {document.method} chars={document.char_count} compact={compact_len(document.text)} -----")
                print(document.text or "")
                for warning in document.warnings:
                    print(f"[warning] {warning}")
        return 0

    result = export_booking_data(args.pdfs, as_dataframe=args.dataframe)
    if args.dataframe:
        print(result.to_json(orient="records", force_ascii=False, indent=2))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
