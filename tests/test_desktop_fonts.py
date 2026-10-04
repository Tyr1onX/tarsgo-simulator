from pathlib import Path
import sys

import pytest

from tarsgo_simulator.desktop import fonts


class _Surface:
    def __init__(self, width=40, height=18):
        self._size = (width, height)

    def get_width(self):
        return self._size[0]

    def get_height(self):
        return self._size[1]


class _Font:
    def __init__(self, *, supported=True):
        self.supported = supported
        self.rendered = []

    def metrics(self, text):
        if not self.supported:
            return [None for _char in text]
        return [(0, 10, 0, 12, 10) for _char in text]

    def render(self, text, antialias, color):
        self.rendered.append((text, antialias, color))
        return _Surface()


def test_font_support_check_requires_real_chinese_glyphs_and_render():
    supported = _Font(supported=True)
    unsupported = _Font(supported=False)

    assert fonts._font_supports_chinese(supported)
    assert supported.rendered[0][0] == "中文测试"
    assert not fonts._font_supports_chinese(unsupported)


def test_macos_system_font_paths_precede_generic_discovery():
    paths = fonts._system_cjk_font_paths("darwin")

    assert paths[0] == Path("/System/Library/Fonts/PingFang.ttc")
    assert Path("/System/Library/Fonts/Hiragino Sans GB.ttc") in paths
    assert Path("/System/Library/Fonts/STHeiti Medium.ttc") in paths


def test_windows_system_font_paths_use_windows_fonts_directory():
    paths = fonts._system_cjk_font_paths(
        "win32",
        windows_dir=r"D:\Windows",
    )
    rendered = tuple(str(path).replace("\\", "/") for path in paths)

    assert rendered[0].endswith("D:/Windows/Fonts/msyh.ttc")
    assert rendered[1].endswith("D:/Windows/Fonts/msyhbd.ttc")
    assert rendered[3].endswith("D:/Windows/Fonts/simhei.ttf")


def test_resolver_prefers_existing_system_path(monkeypatch):
    selected = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
    fake_font = _Font()

    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: path == selected,
    )
    monkeypatch.setattr(
        fonts,
        "_load_cjk_font",
        lambda path, size: fake_font if path == selected and size == 18 else None,
    )
    monkeypatch.setattr(
        fonts.pygame.font,
        "match_font",
        lambda name: pytest.fail(f"match_font should not run: {name}"),
    )

    result, source = fonts._resolve_ui_font(18, platform_name="darwin")

    assert result is fake_font
    assert source == str(selected)


def test_resolver_uses_match_font_after_system_paths(monkeypatch):
    fake_font = _Font()
    matched = "/tmp/NotoSansCJK-Regular.ttc"
    calls = []

    monkeypatch.setattr(Path, "is_file", lambda path: False)
    monkeypatch.setattr(
        fonts.pygame.font,
        "match_font",
        lambda name: calls.append(name) or (
            matched if name == "Noto Sans CJK SC" else None
        ),
    )
    monkeypatch.setattr(
        fonts,
        "_load_cjk_font",
        lambda path, size: fake_font if str(path) == matched else None,
    )

    result, source = fonts._resolve_ui_font(18, platform_name="linux")

    assert result is fake_font
    assert source == matched
    assert calls[0] == "Noto Sans CJK SC"


def test_resolver_rejects_unsupported_pygame_default(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda path: False)
    monkeypatch.setattr(fonts.pygame.font, "match_font", lambda name: None)
    monkeypatch.setattr(
        fonts.pygame.font,
        "Font",
        lambda path, size: _Font(supported=False),
    )

    with pytest.raises(RuntimeError, match="No installed font can render Chinese"):
        fonts._resolve_ui_font(18, platform_name="linux")


@pytest.mark.skipif(sys.platform != "darwin", reason="real macOS system font check")
def test_real_macos_font_loader_renders_chinese():
    font, source = fonts._resolve_ui_font(18, platform_name="darwin")

    assert source.startswith(("/System/Library/Fonts/", "/Library/Fonts/"))
    assert fonts._font_supports_chinese(font)
    surface = font.render("中文测试", True, (255, 255, 255))
    assert surface.get_width() > 0
    assert surface.get_height() > 0