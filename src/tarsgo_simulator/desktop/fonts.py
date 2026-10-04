"""Desktop UI font discovery with explicit CJK glyph validation."""

from pathlib import Path
import os
import sys

import pygame


_CJK_PROBE = "中文测试"


def _system_cjk_font_paths(
    platform_name=None,
    windows_dir=None,
):
    platform_name = platform_name or sys.platform
    if platform_name == "darwin":
        return (
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
            Path("/System/Library/Fonts/STHeiti Medium.ttc"),
            Path("/System/Library/Fonts/STHeiti Light.ttc"),
            Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
            Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
            Path("/Library/Fonts/Arial Unicode.ttf"),
        )
    if platform_name.startswith("win"):
        root = Path(
            windows_dir
            or os.environ.get("WINDIR")
            or os.environ.get("SystemRoot")
            or r"C:\Windows"
        )
        fonts = root / "Fonts"
        return (
            fonts / "msyh.ttc",
            fonts / "msyhbd.ttc",
            fonts / "msyhl.ttc",
            fonts / "simhei.ttf",
            fonts / "simsun.ttc",
        )
    return ()


def _match_font_names(platform_name=None):
    platform_name = platform_name or sys.platform
    if platform_name == "darwin":
        preferred = (
            "PingFang SC",
            "Hiragino Sans GB",
            "Heiti SC",
            "Songti SC",
        )
    elif platform_name.startswith("win"):
        preferred = (
            "Microsoft YaHei",
            "Microsoft YaHei UI",
            "SimHei",
            "SimSun",
        )
    else:
        preferred = ()
    return preferred + (
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Arial Unicode MS",
    )


def _font_supports_chinese(font):
    try:
        metrics = font.metrics(_CJK_PROBE)
        if not metrics or any(item is None for item in metrics):
            return False
        surface = font.render(_CJK_PROBE, True, (255, 255, 255))
    except (TypeError, ValueError, pygame.error):
        return False
    return surface.get_width() > 0 and surface.get_height() > 0


def _load_cjk_font(path, size):
    try:
        font = pygame.font.Font(str(path), size)
    except (OSError, pygame.error):
        return None
    return font if _font_supports_chinese(font) else None


def _resolve_ui_font(
    size,
    *,
    platform_name=None,
    windows_dir=None,
):
    if not pygame.font.get_init():
        pygame.font.init()

    attempted = []
    seen = set()

    for path in _system_cjk_font_paths(platform_name, windows_dir):
        path_text = str(path)
        if path_text in seen or not path.is_file():
            continue
        seen.add(path_text)
        attempted.append(path_text)
        font = _load_cjk_font(path, size)
        if font is not None:
            return font, path_text

    for name in _match_font_names(platform_name):
        path = pygame.font.match_font(name)
        if path is None or path in seen:
            continue
        seen.add(path)
        attempted.append(path)
        font = _load_cjk_font(path, size)
        if font is not None:
            return font, path

    default_font = pygame.font.Font(None, size)
    if _font_supports_chinese(default_font):
        return default_font, "<pygame-default>"

    attempted_text = ", ".join(attempted) if attempted else "none"
    raise RuntimeError(
        "No installed font can render Chinese UI text. "
        f"Checked: {attempted_text}"
    )


def ui_font(
    size,
    *,
    platform_name=None,
    windows_dir=None,
):
    font, _source = _resolve_ui_font(
        size,
        platform_name=platform_name,
        windows_dir=windows_dir,
    )
    return font