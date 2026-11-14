"""Exact quarter arithmetic used by the B6 comparison service."""
import re


def period_shift(period: str, quarters: int) -> str:
    """Shift a YYYYQ quarter, keeping the supported year range 0001..9999."""
    if not isinstance(period, str) or not re.fullmatch(r"[0-9]{4}[1-4]", period):
        raise ValueError("기간은 YYYYQ 형식이어야 합니다. 예: 20261")
    year, quarter = int(period[:4]), int(period[4])
    if year == 0:
        raise ValueError("기간의 연도는 0001 이상이어야 합니다.")
    if type(quarters) is not int:
        raise ValueError("분기 이동 값은 정수여야 합니다.")
    shifted = (year - 1) * 4 + quarter - 1 + quarters
    if not 0 <= shifted < 9999 * 4:
        raise ValueError("이동한 기간이 지원 연도 범위를 벗어났습니다.")
    shifted_year, shifted_quarter = divmod(shifted, 4)
    return f"{shifted_year + 1:04d}{shifted_quarter + 1}"
