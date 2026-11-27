"""
QA: timetable parser beyond the 9-column CSV: aliased/Markdown/TSV tables, multi-session schedule cells, text-file
decoding, PDF (text layer and ruled tables), image OCR, and the merge of per-page results.

Why this file exists: coverage showed services/parser.py at 39% because nothing fed it a PDF, an image or an aliased
table. All inputs are generated here at run time (no binary files are committed): PDFs are written by hand, images are
drawn with Pillow. OCR tests are skipped when Tesseract (with the Vietnamese pack) is not installed.

Standard / method : ISO/IEC/IEEE 29119-4 (equivalence partitioning, error guessing), RFC 4180 for the CSV family.
Run               : python -m pytest tests/test_parser_formats.py -q
Rules checked     : AGENTS.md section 5 - never crash on a bad row, never drop a row silently, flag it instead.
"""
import io
import shutil
import sys
from pathlib import Path

import pytest

BE_ROOT = next(p / "sourceCode" / "BE" for p in Path(__file__).resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())
if str(BE_ROOT) not in sys.path:
    sys.path.insert(0, str(BE_ROOT))

from models import Weekday  # noqa: E402
from services import parser as P  # noqa: E402

DATES = ("2026-09-07", "2026-12-14")


# ====================================================================== generators
def make_pdf(content_stream: str) -> bytes:
    """a one-page PDF with the Helvetica font; content_stream holds the drawing/text operators."""
    body = content_stream.encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def text_pdf(lines: list[str]) -> bytes:
    ops = ["BT /F1 10 Tf 50 780 Td 14 TL"]
    ops += [f"({line.replace('(', '[').replace(')', ']')}) Tj T*" for line in lines]
    ops.append("ET")
    return make_pdf("\n".join(ops))


def grid_pdf(rows: list[list[str]], widths: list[int], row_h: int = 24, x0: int = 30, y0: int = 780) -> bytes:
    """a PDF with ruled lines (so pdfplumber's table detector fires) and one text cell per grid cell."""
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)
    ops = []
    for r in range(len(rows) + 1):
        ops.append(f"0.8 w {x0} {y0 - r * row_h} m {xs[-1]} {y0 - r * row_h} l S")
    for x in xs:
        ops.append(f"0.8 w {x} {y0} m {x} {y0 - len(rows) * row_h} l S")
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            ops.append(f"BT /F1 8 Tf {xs[c] + 4} {y0 - r * row_h - 15} Td ({cell}) Tj ET")
    return make_pdf("\n".join(ops))


def tesseract_ready() -> bool:
    try:
        import pytesseract
    except ImportError:
        return False
    exe = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not Path(exe).exists() and not shutil.which("tesseract"):
        return False
    try:
        pytesseract.pytesseract.tesseract_cmd = exe
        return "vie" in pytesseract.get_languages(config="")
    except Exception:
        return False


needs_ocr = pytest.mark.skipif(not tesseract_ready(), reason="Tesseract with the 'vie' language pack is not installed")
needs_pillow = pytest.mark.skipif(not P._OCR_AVAILABLE, reason="Pillow/pytesseract not installed")
needs_pdf = pytest.mark.skipif(not P._PDFPLUMBER_AVAILABLE, reason="pdfplumber not installed")


def table_image_bytes(rows: list[list[str]], widths: list[int], row_h: int = 48) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    fonts = [r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    font_path = next((f for f in fonts if Path(f).exists()), None)
    if font_path is None:
        pytest.skip("no TrueType font available to draw the test image")
    font = ImageFont.truetype(font_path, 22)
    xs = [10]
    for w in widths:
        xs.append(xs[-1] + w)
    img = Image.new("RGB", (xs[-1] + 10, row_h * len(rows) + 20), "white")
    d = ImageDraw.Draw(img)
    for r in range(len(rows) + 1):
        d.line([(10, 10 + r * row_h), (xs[-1], 10 + r * row_h)], fill="black", width=2)
    for x in xs:
        d.line([(x, 10), (x, 10 + row_h * len(rows))], fill="black", width=2)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            d.text((xs[c] + 8, 10 + r * row_h + 10), cell, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def parse(text: str, name: str = "t.csv"):
    return P.parse_timetable_content(text, name)


def codes(res) -> list[str]:
    return [r.error_code for r in res.invalid_rows]


# ====================================================================== 1. one schedule cell -> sessions
class TestScheduleCell:
    @pytest.mark.parametrize("text,expected", [
        ("T4 07:30-09:10 (C.45) T6 07:30-09:10 (I.44)", [(Weekday.WED, "07:30", "09:10", "C.45"), (Weekday.FRI, "07:30", "09:10", "I.44")]),
        ("T2 7.30-9.10", [(Weekday.MON, "07:30", "09:10", None)]),
        ("CN 08:00-10:00", [(Weekday.SUN, "08:00", "10:00", None)]),
        ("Thứ 5 13:00-15:00", [(Weekday.THU, "13:00", "15:00", None)]),
        ("Monday 08:00-10:00 (A1)", [(Weekday.MON, "08:00", "10:00", "A1")]),
        ("T7 14:00–16:00", [(Weekday.SAT, "14:00", "16:00", None)]),  # en dash
        ("T3 7:30-9:30 (B1) T3 13:00-15:00 (B2)", [(Weekday.TUE, "07:30", "09:30", "B1"), (Weekday.TUE, "13:00", "15:00", "B2")]),
    ])
    def test_sessions_are_split_and_normalised(self, text, expected):
        got = [(w, s, e, room) for w, s, e, room, err in P._schedule_entries_from_text(text)]
        assert got == expected
        assert all(err is None for *_, err in P._schedule_entries_from_text(text))

    @pytest.mark.parametrize("text", ["T3 (A1)", "chiều thứ", "tuần sau", "T2"])
    def test_unreadable_cells_return_an_error_entry_not_an_exception(self, text):
        entries = P._schedule_entries_from_text(text)
        assert entries and entries[0][4]  # an error message is present

    def test_empty_cell_gives_no_entries(self):
        assert P._schedule_entries_from_text("") == []
        assert P._schedule_entries_from_text("   ") == []

    @pytest.mark.parametrize("token,expected", [("T2", Weekday.MON), ("T 6", Weekday.FRI), ("cn", Weekday.SUN), ("Thứ 4", Weekday.WED),
                                                ("thursday", Weekday.THU), ("xyz", None), ("T8", None)])
    def test_weekday_tokens(self, token, expected):
        assert P._parse_weekday_token(token) == expected


# ====================================================================== 2. aliased tables
HDR_SPLIT = "Mã MH,Tên môn học,Thứ,Giờ bắt đầu,Giờ kết thúc,Phòng,Ngày bắt đầu,Ngày kết thúc"
ROW_SPLIT = "CSC10001,Nhập môn lập trình,T2,07:30,09:30,B11.02,2026-09-07,2026-12-14"


class TestAliasedTables:
    def test_markdown_table_with_vietnamese_headers(self):
        md = (f"| Mã MH | Tên môn học | Thứ | Giờ bắt đầu | Giờ kết thúc | Phòng | Ngày bắt đầu | Ngày kết thúc |\n|---|---|---|---|---|---|---|---|\n"
              f"| CSC10001 | Nhập môn lập trình | T2 | 07:30 | 09:30 | B11.02 | 2026-09-07 | 2026-12-14 |\n"
              f"| MTH10001 | Giải tích 1 | Thứ 4 | 09:45 | 11:45 | E101 | 2026-09-09 | 2026-12-16 |\n")
        res = parse(md, "t.md")
        assert len(res.valid_rows) == 2 and not res.invalid_rows
        assert [r.weekday for r in res.valid_rows] == [Weekday.MON, Weekday.WED]
        assert res.valid_rows[0].room == "B11.02" and res.valid_rows[1].title == "Giải tích 1"

    @pytest.mark.parametrize("sep", [",", ";", "\t"])
    def test_delimiter_is_detected(self, sep):
        text = sep.join(HDR_SPLIT.split(",")) + "\n" + sep.join(ROW_SPLIT.split(",")) + "\n"
        res = parse(text)
        assert len(res.valid_rows) == 1 and not res.invalid_rows

    def test_english_aliases(self):
        res = parse("Course Code,Course Name,Day,Start Time,End Time,Room,Start Date,End Date\nCS1,Algorithms,Friday,13:00,15:00,A2,2026-09-11,2026-12-18\n")
        assert len(res.valid_rows) == 1 and res.valid_rows[0].weekday == Weekday.FRI

    def test_schedule_cells_expand_into_one_row_per_session(self):
        text = ("Mã MH,Tên MH,Lịch LT,Lịch TH,Ngày bắt đầu,Ngày kết thúc\n"
                "CSC10001,Nhập môn,T4 07:30-09:10 (C.45) T6 07:30-09:10 (I.44),T2 13:00-15:00 (F1),2026-09-07,2026-12-14\n")
        res = parse(text)
        assert len(res.valid_rows) == 3 and not res.invalid_rows
        assert sorted(r.weekday.value for r in res.valid_rows) == ["FRI", "MON", "WED"]
        assert {r.room for r in res.valid_rows} == {"C.45", "I.44", "F1"}

    def test_line_numbers_are_unique_when_one_row_expands(self):
        text = ("Mã MH,Tên MH,Lịch LT,Ngày bắt đầu,Ngày kết thúc\n"
                "A,Toán,T2 07:30-09:30 T4 07:30-09:30 T6 07:30-09:30,2026-09-07,2026-12-14\n"
                "B,Lý,T3 07:30-09:30,2026-09-07,2026-12-14\n")
        res = parse(text)
        numbers = [r.line_number for r in res.valid_rows] + [r.line_number for r in res.invalid_rows]
        assert len(numbers) == 4 and len(set(numbers)) == 4

    def test_merged_course_cells_inherit_the_previous_course(self):
        text = ("Mã MH,Tên MH,Lịch LT,Ngày bắt đầu,Ngày kết thúc\n"
                "CSC10001,Nhập môn,T2 07:30-09:30,2026-09-07,2026-12-14\n"
                ",,T4 07:30-09:30,2026-09-07,2026-12-14\n")
        res = parse(text)
        assert len(res.valid_rows) == 2
        assert {r.course_code for r in res.valid_rows} == {"CSC10001"} and {r.title for r in res.valid_rows} == {"Nhập môn"}

    def test_repeated_header_row_in_the_middle_is_skipped(self):
        text = HDR_SPLIT + "\n" + ROW_SPLIT + "\n" + HDR_SPLIT + "\n" + ROW_SPLIT.replace("T2", "T3") + "\n"
        res = parse(text)
        assert len(res.valid_rows) == 2 and not res.invalid_rows

    def test_exam_row_without_weekday(self):
        text = "Mã MH,Tên môn học,Thứ,Giờ bắt đầu,Giờ kết thúc,Ngày bắt đầu,Ngày kết thúc,Loại\nCSC10001,Thi cuối kỳ,,08:00,10:00,2027-01-12,2027-01-12,EXAM\n"
        res = parse(text)
        assert len(res.valid_rows) == 1 and res.valid_rows[0].kind.value == "EXAM"

    def test_row_without_any_schedule_is_flagged_not_dropped(self):
        text = "Mã MH,Tên MH,Lịch LT,Ngày bắt đầu,Ngày kết thúc\nCSC10001,Nhập môn,,2026-09-07,2026-12-14\n"
        assert codes(parse(text)) == ["NO_SCHEDULE_PUBLISHED"]

    @pytest.mark.parametrize("cell,code", [("T9 07:30-09:30", "UNPARSEABLE_SCHEDULE"), ("T3", "UNPARSEABLE_SCHEDULE"), ("đang cập nhật", "UNPARSEABLE_SCHEDULE")])
    def test_bad_schedule_cells_are_flagged(self, cell, code):
        text = f"Mã MH,Tên MH,Lịch LT,Ngày bắt đầu,Ngày kết thúc\nCSC1,Toán,{cell},2026-09-07,2026-12-14\n"
        res = parse(text)
        assert not res.valid_rows and codes(res) == [code]

    def test_end_before_start_is_flagged(self):
        res = parse(HDR_SPLIT + "\n" + ROW_SPLIT.replace("07:30,09:30", "10:00,08:00") + "\n")
        assert codes(res) == ["INVALID_TIME_RANGE"]

    def test_short_ragged_row_does_not_crash(self):
        res = parse(HDR_SPLIT + "\nCSC1,Toán\n" + ROW_SPLIT + "\n")
        assert len(res.valid_rows) == 1 and len(res.invalid_rows) == 1

    def test_all_rows_are_accounted_for(self):
        text = HDR_SPLIT + "\n" + "\n".join([ROW_SPLIT, ROW_SPLIT.replace("T2", "T9"), "x", ROW_SPLIT.replace("T2", "T5")]) + "\n"
        res = parse(text)
        assert len(res.valid_rows) + len(res.invalid_rows) == 4

    def test_tables_without_dates_are_flagged_with_a_clear_message(self):
        """design: exact semester dates are mandatory; a portal export without them must be corrected row by row."""
        res = parse("Mã MH,Tên môn học,Thứ,Giờ bắt đầu,Giờ kết thúc\nCSC1,Toán,T3,08:00,10:00\n")
        assert not res.valid_rows and codes(res) == ["EMPTY_FIRST_DATE"]

    def test_semester_column_explains_why_dates_are_needed(self):
        res = parse("Mã MH,Tên môn học,Học kỳ,Thứ,Giờ bắt đầu,Giờ kết thúc\nCSC1,Toán,HK1 2026-2027,T3,08:00,10:00\n")
        assert "HK1 2026-2027" in res.invalid_rows[0].error_message

    def test_unsupported_header_falls_back_to_the_nine_column_parser_without_crashing(self):
        res = parse("name,day\nToán,Monday\n")
        assert not res.valid_rows and set(codes(res)) == {"INVALID_COLUMN_COUNT"}

    @pytest.mark.parametrize("label,expected", [("Mã MH", "course_code"), ("MÃ MÔN HỌC", "course_code"), ("Tên Môn Học", "title"), ("Giờ bắt đầu", "start_time"),
                                                ("Đến ngày", "last_date"), ("Lịch thực hành", "practice_schedule"), ("???", None)])
    def test_header_aliases(self, label, expected):
        assert P._map_table_headers([label]) == ({expected: 0} if expected else {})


# ====================================================================== 3. files and encodings
class TestFileDispatch:
    TXT = (HDR_SPLIT + "\n" + ROW_SPLIT + "\n")

    @pytest.mark.parametrize("name", ["a.csv", "a.txt", "a.md", "a.CSV", "A.TXT", "noext", ""])
    def test_plain_text_extensions_are_accepted(self, name):
        res = P.parse_timetable_file(self.TXT.encode("utf-8"), name)
        assert len(res.valid_rows) == 1

    def test_latin1_fallback_decodes_legacy_files(self):
        text = "Mã MH,Tên MH,Thu,Gio bat dau,Gio ket thuc,Ngay bat dau,Ngay ket thuc\nCSC1,Café,T3,08:00,10:00,2026-09-08,2026-12-15\n"
        raw = text.encode("latin-1")
        with pytest.raises(UnicodeDecodeError):
            raw.decode("utf-8")
        res = P.parse_timetable_file(raw, "legacy.csv")
        assert len(res.valid_rows) == 1 and res.valid_rows[0].title == "Café"

    @pytest.mark.parametrize("name", ["a.docx", "a.xlsx", "a.exe", "a.json"])
    def test_unsupported_types_are_rejected_with_a_clear_message(self, name):
        with pytest.raises(ValueError, match="Unsupported file type"):
            P.extract_raw_text_from_file(b"x", name)

    def test_empty_file(self):
        res = P.parse_timetable_file(b"", "empty.csv")
        assert res.valid_rows == [] and res.invalid_rows == []

    def test_export_round_trip(self):
        res = parse(self.TXT)
        csv_text = P.export_valid_rows_to_csv(res.valid_rows)
        again = parse(csv_text)
        assert len(again.valid_rows) == 1 and again.valid_rows[0].title == res.valid_rows[0].title


# ====================================================================== 4. PDF
@needs_pdf
class TestPdf:
    CANON = "course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind"
    ROW = "CSC10001,Intro to CS,MON,07:30,09:30,B11.02,2026-09-07,2026-12-14,CLASS"

    def test_text_layer_pdf_with_csv_lines(self):
        pdf = text_pdf([self.CANON, self.ROW, self.ROW.replace("CSC10001", "MTH10001").replace("MON", "WED")])
        res = P.parse_timetable_file(pdf, "a.pdf")
        assert len(res.valid_rows) == 2 and not res.invalid_rows

    def test_ruled_table_pdf_canonical_header(self):
        pdf = grid_pdf([self.CANON.split(","), self.ROW.split(",")], widths=[62, 62, 50, 54, 54, 54, 70, 70, 40])
        res = P.parse_timetable_file(pdf, "a.pdf")
        assert len(res.valid_rows) == 1 and res.valid_rows[0].course_code == "CSC10001"

    def test_ruled_table_pdf_with_schedule_cells(self):
        pdf = grid_pdf([["Ma MH", "Ten mon", "Lich LT", "Ngay bat dau", "Ngay ket thuc"],
                        ["CSC1", "Intro", "T4 07:30-09:10 (C.45) T6 07:30-09:10 (I.44)", "2026-09-09", "2026-12-16"]], widths=[50, 60, 250, 80, 80])
        res = P.parse_timetable_file(pdf, "a.pdf")
        assert len(res.valid_rows) == 2 and not res.invalid_rows

    def test_pdf_without_text_is_reported_not_crashed(self):
        res = P.parse_timetable_file(make_pdf(""), "blank.pdf")
        assert not res.valid_rows and codes(res) == ["NO_TIMETABLE_DETECTED"]
        with pytest.raises(ValueError, match="No readable text"):
            P.extract_raw_text_from_file(make_pdf(""), "blank.pdf")

    def test_free_text_lines_are_flagged_row_by_row(self):
        res = P.parse_timetable_file(text_pdf(["Thoi khoa bieu hoc ky 1", "CSC10001 Intro T2 07:30-09:30", "MTH10001 Calculus T4 09:45-11:45"]), "a.pdf")
        assert not res.valid_rows and len(res.invalid_rows) == 3

    @pytest.mark.parametrize("junk", [b"not a pdf", b"%PDF-1.4\ngarbage", b""])
    def test_corrupt_pdf_raises_a_clear_error(self, junk):
        with pytest.raises(ValueError, match="Failed to read PDF|No readable text"):
            P.parse_timetable_file(junk, "bad.pdf")


# ====================================================================== 5. images and OCR
@needs_pillow
class TestImages:
    @needs_ocr
    def test_blank_image_is_reported_as_no_timetable(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (400, 300), "white").save(buf, "PNG")
        res = P.parse_timetable_file(buf.getvalue(), "blank.png")
        assert not res.valid_rows and codes(res) == ["NO_TIMETABLE_DETECTED"]

    @pytest.mark.parametrize("name", ["bad.png", "bad.jpg", "bad.jpeg"])
    def test_corrupt_image_raises_a_clear_error(self, name):
        with pytest.raises(ValueError, match="Cannot read image"):
            P.parse_timetable_file(b"not an image", name)

    @needs_ocr
    def test_ocr_reads_a_ruled_table_with_dates(self):
        rows = [["Ma MH", "Ten mon", "Thu", "Gio bat dau", "Gio ket thuc", "Ngay bat dau", "Ngay ket thuc"],
                ["CSC10001", "Intro to CS", "T2", "07:30", "09:30", "2026-09-07", "2026-12-14"],
                ["MTH10001", "Calculus", "T4", "09:45", "11:45", "2026-09-09", "2026-12-16"]]
        res = P.parse_timetable_file(table_image_bytes(rows, [150, 220, 80, 180, 180, 200, 200]), "t.png")
        assert len(res.valid_rows) == 2 and not res.invalid_rows
        assert [r.weekday for r in res.valid_rows] == [Weekday.MON, Weekday.WED]
        assert [r.course_code for r in res.valid_rows] == ["CSC10001", "MTH10001"]

    @needs_ocr
    def test_ocr_table_without_dates_is_flagged_for_correction(self):
        rows = [["Ma MH", "Ten mon", "Thu", "Gio bat dau", "Gio ket thuc"], ["CSC10001", "Intro to CS", "T2", "07:30", "09:30"]]
        res = P.parse_timetable_file(table_image_bytes(rows, [150, 220, 80, 180, 180]), "t.png")
        assert not res.valid_rows and codes(res) == ["EMPTY_FIRST_DATE"]

    @needs_ocr
    def test_ocr_raw_text_contains_the_cells(self):
        rows = [["Ma MH", "Ten mon", "Thu"], ["CSC10001", "Intro to CS", "T2"]]
        raw = P.extract_raw_text_from_file(table_image_bytes(rows, [150, 220, 80]), "t.png")
        assert "CSC10001" in raw and "Intro" in raw


# ====================================================================== 6. merging page results
class TestCombine:
    def _result(self, n_valid, n_invalid):
        base = parse(HDR_SPLIT + "\n" + "\n".join([ROW_SPLIT] * n_valid + [ROW_SPLIT.replace("T2", "T9")] * n_invalid) + "\n")
        assert len(base.valid_rows) == n_valid and len(base.invalid_rows) == n_invalid
        return base

    def test_line_numbers_are_renumbered_without_duplicates(self):
        merged = P._combine_parse_results("b1", [self._result(2, 1), self._result(1, 2)])
        numbers = [r.line_number for r in merged.valid_rows + merged.invalid_rows]
        assert sorted(numbers) == list(range(1, 7))
        assert merged.import_batch_id == "b1" and len(merged.valid_rows) == 3 and len(merged.invalid_rows) == 3

    def test_empty_list(self):
        merged = P._combine_parse_results("b2", [])
        assert merged.valid_rows == [] and merged.invalid_rows == []

    def test_result_has_rows(self):
        assert P._result_has_rows(self._result(1, 0)) and not P._result_has_rows(P._combine_parse_results("b3", []))

    def test_no_timetable_result_shape(self):
        res = P._no_timetable_result("b4", "photo.png")
        assert codes(res) == ["NO_TIMETABLE_DETECTED"] and res.invalid_rows[0].raw_text == "photo.png"

    def test_table_rows_to_csv_quotes_commas(self):
        text = P._table_rows_to_csv([["a,b", 'say "hi"', ""]])
        assert text.strip() == '"a,b","say ""hi""",'
