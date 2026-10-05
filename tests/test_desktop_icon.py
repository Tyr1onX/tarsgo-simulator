from pathlib import Path
import importlib
import struct
import sys

import pytest


@pytest.fixture(scope="module", autouse=True)
def _cleanup_icon_imports():
    yield
    pygame = sys.modules.get("pygame")
    if pygame is not None:
        pygame.quit()
    sys.modules.pop("tarsgo_simulator.desktop.icon", None)
    for module_name in list(sys.modules):
        if module_name == "pygame" or module_name.startswith("pygame."):
            sys.modules.pop(module_name, None)


def test_shared_app_icon_is_packaged_for_windows_and_macos(tmp_path: Path) -> None:
    pygame = importlib.import_module("pygame")
    icon_module = importlib.import_module("tarsgo_simulator.desktop.icon")
    icon = icon_module.render_app_icon(32)
    assert icon.get_size() == (32, 32)

    files = icon_module.write_app_icons(tmp_path)
    assert {path.suffix for path in files.values()} == {".png", ".ico", ".icns"}

    master = pygame.image.load(str(files["png"]))
    assert master.get_size() == (512, 512)

    ico = files["ico"].read_bytes()
    assert struct.unpack("<HHH", ico[:6]) == (0, 1, 7)
    assert ico[6:8] == b"\x10\x10"
    for index, expected_size in enumerate((16, 24, 32, 48, 64, 128, 256)):
        entry = 6 + index * 16
        width, height = ico[entry], ico[entry + 1]
        image_size, offset = struct.unpack("<II", ico[entry + 8 : entry + 16])
        assert (width or 256, height or 256) == (expected_size, expected_size)
        assert ico[offset : offset + 4] == struct.pack("<I", 40)
        assert image_size > 40

    icns = files["icns"].read_bytes()
    assert icns[:4] == b"icns"
    assert struct.unpack(">I", icns[4:8])[0] == len(icns)
    assert all(chunk_type in icns for chunk_type in (b"icp4", b"icp5", b"ic07", b"ic10"))
