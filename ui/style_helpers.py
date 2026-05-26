"""
Shared widget styles — color/weight only.
Font size is controlled globally via Settings → app.setFont().
"""
from core.app_settings import get_settings


def text_style(color: str, *, bold: bool = False, extra: str = "") -> str:
    weight = "font-weight:bold;" if bold else ""
    suffix = f" {extra}" if extra else ""
    return f"color:{color}; background:transparent; {weight}{suffix}"


def muted(extra: str = "") -> str:
    return text_style("#6c7086", extra=extra)


def accent(extra: str = "") -> str:
    return text_style("#89b4fa", extra=extra)


def title(extra: str = "") -> str:
    return text_style("#cdd6f4", bold=True, extra=extra)


def hint(extra: str = "") -> str:
    return text_style("#585b70", extra=extra)


def warning(extra: str = "") -> str:
    return text_style("#f9e2af", extra=extra)


def error(extra: str = "") -> str:
    return text_style("#f38ba8", extra=extra)


def success(extra: str = "") -> str:
    return text_style("#a6e3a1", extra=extra)


def checkbox_emphasis(color: str) -> str:
    return f"font-weight:bold; color:{color}; background:transparent;"


def mpl_font_size(offset: int = 0) -> int:
    """Matplotlib font size derived from app settings."""
    return max(6, int(get_settings().font_size()) + offset)
