"""Indian mobile numbers: normalisation, validation, and safe spoken or masked forms."""
import re

_SEPARATORS = re.compile(r"[\s\-().]")
_MOBILE = re.compile(r"[6-9]\d{9}")


class InvalidPhone(ValueError):
    pass


def normalize_indian_mobile(raw: str | None) -> str:
    """The 10-digit mobile number, ignoring spaces, dashes and one leading +91 or 0."""
    number = _SEPARATORS.sub("", raw or "")
    if number.startswith("+91"):
        number = number[3:]
    elif number.startswith("0"):
        number = number[1:]
    if not _MOBILE.fullmatch(number):
        raise InvalidPhone("Please give a 10-digit Indian mobile number starting with 6, 7, 8 or 9.")
    return number


def is_valid_indian_mobile(raw: str | None) -> bool:
    try:
        normalize_indian_mobile(raw)
    except InvalidPhone:
        return False
    return True


def spoken_digits(number: str) -> str:
    """Digits read one at a time in two groups of five, e.g. '9 8 7 6 5, 4 3 2 1 0'."""
    digits = re.sub(r"\D", "", number)
    groups = [digits[i:i + 5] for i in range(0, len(digits), 5)]
    return ", ".join(" ".join(group) for group in groups)


def masked(number: str | None) -> str:
    """For logs and debugging only: never the whole number."""
    if not number:
        return "none"
    return "X" * (len(number) - 4) + number[-4:]
