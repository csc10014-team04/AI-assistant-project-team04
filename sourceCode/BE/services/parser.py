# owner: Lam (P1-4 first half: multi-format timetable parser & staging error isolation)
from models import ParseBatchResult, ParsedCsvRow


def parse_timetable_content(raw_content: str, filename: str = "") -> ParseBatchResult:
    """parse raw text/markdown/csv timetable into valid_rows and invalid_rows"""
    raise NotImplementedError


def export_valid_rows_to_csv(rows: list[ParsedCsvRow]) -> str:
    """serialize validated rows into the standardized intermediate csv format"""
    raise NotImplementedError
