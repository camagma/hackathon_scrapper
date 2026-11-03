"""Parse Devpost submission periods into calendar dates without locale state."""

from datetime import date
import re


MONTHS = {name: number for number, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}
SINGLE = re.compile(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})")
PERIOD = re.compile(
    r"([A-Z][a-z]{2})\s+(\d{1,2})(?:,\s*(\d{4}))?"
    r"\s+[-–—]\s+(?:([A-Z][a-z]{2})\s+)?(\d{1,2}),\s*(\d{4})"
)


def parse_submission_period(value: str) -> tuple[date, date]:
    """Return start and deadline; reject unknown formats and invalid dates."""
    text = " ".join(value.split())
    single = SINGLE.fullmatch(text)
    period = PERIOD.fullmatch(text)
    try:
        if single:
            month, day, year = single.groups()
            result = date(int(year), MONTHS[month], int(day))
            return result, result
        if not period:
            raise ValueError("unrecognized date format")
        start_month, start_day, start_year, end_month, end_day, end_year = period.groups()
        first_month = MONTHS[start_month]
        last_month = MONTHS[end_month] if end_month else first_month
        last_year = int(end_year)
        first_year = int(start_year) if start_year else last_year - (first_month > last_month)
        start = date(first_year, first_month, int(start_day))
        deadline = date(last_year, last_month, int(end_day))
        if start > deadline:
            raise ValueError("start date is after deadline")
        return start, deadline
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid submission period {value!r}: {exc}") from exc
