"""Programmatically draw and package the shared TARS-Go application icon."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import struct

import pygame


_MASTER_SIZE = 512
_ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
_ICNS_TYPES = {
    16: b"icp4",
    32: b"icp5",
    64: b"icp6",
    128: b"ic07",
    256: b"ic08",
    512: b"ic09",
    1024: b"ic10",
}


def _master_icon() -> pygame.Surface:
    """Return a high-resolution, text-free tactical robot mark."""
    size = _MASTER_SIZE
    scale = size / 128

    def p(value: float) -> int:
        return round(value * scale)

    def points(values: tuple[tuple[float, float], ...]) -> list[tuple[int, int]]:
        return [(p(x), p(y)) for x, y in values]

    surface = pygame.Surface((size, size), pygame.SRCALPHA)
    surface.fill((10, 18, 27, 0))
    pygame.draw.rect(
        surface,
        (13, 23, 34),
        (p(3), p(3), p(122), p(122)),
        border_radius=p(25),
    )
    pygame.draw.rect(
        surface,
        (69, 91, 104),
        (p(5), p(5), p(118), p(118)),
        width=p(2),
        border_radius=p(23),
    )

    # Four short corner marks frame the central top-down robot silhouette.
    corner_color = (69, 175, 188)
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        x = 20 if sx < 0 else 108
        y = 20 if sy < 0 else 108
        end_x = x + sx * 8
        end_y = y + sy * 8
        pygame.draw.line(surface, corner_color, (p(x), p(y)), (p(end_x), p(y)), p(2))
        pygame.draw.line(surface, corner_color, (p(x), p(y)), (p(x), p(end_y)), p(2))

    # Side armor and a broad, forward-facing chassis remain legible at dock size.
    for x in (31, 97):
        pygame.draw.rect(
            surface,
            (25, 41, 52),
            (p(x - 5), p(42), p(10), p(43)),
            border_radius=p(4),
        )
        pygame.draw.line(
            surface,
            (69, 175, 188),
            (p(x), p(49)),
            (p(x), p(78)),
            p(2),
        )

    chassis = points(
        ((64, 14), (82, 27), (91, 45), (87, 86), (64, 108),
         (41, 86), (37, 45), (46, 27))
    )
    pygame.draw.polygon(surface, (7, 14, 21), chassis)
    pygame.draw.polygon(surface, (32, 53, 65), chassis, width=p(3))
    pygame.draw.polygon(
        surface,
        (46, 96, 108),
        points(((64, 19), (77, 30), (84, 46), (80, 81), (64, 98),
                (48, 81), (44, 46), (51, 30))),
    )
    pygame.draw.polygon(
        surface,
        (23, 40, 51),
        points(((64, 24), (75, 34), (79, 47), (76, 78), (64, 91),
                (52, 78), (49, 47), (53, 34))),
        width=p(2),
    )

    # A thick cannon and rotating turret identify the mark without lettering.
    pygame.draw.line(surface, (6, 13, 19), (p(64), p(30)), (p(64), p(57)), p(17))
    pygame.draw.line(surface, (183, 207, 211), (p(64), p(31)), (p(64), p(54)), p(9))
    pygame.draw.line(surface, (69, 175, 188), (p(64), p(33)), (p(64), p(51)), p(3))
    pygame.draw.circle(surface, (7, 14, 21), (p(64), p(62)), p(18))
    pygame.draw.circle(surface, (87, 121, 133), (p(64), p(62)), p(15))
    pygame.draw.circle(surface, (35, 60, 72), (p(64), p(62)), p(11))
    pygame.draw.circle(surface, (74, 197, 202), (p(64), p(62)), p(5))
    pygame.draw.circle(surface, (241, 194, 112), (p(64), p(62)), p(2))

    # Rear power pack and paired status lamps finish the symmetric outline.
    pygame.draw.polygon(
        surface,
        (16, 29, 39),
        points(((50, 82), (78, 82), (73, 96), (64, 102), (55, 96))),
    )
    pygame.draw.line(surface, (69, 175, 188), (p(56), p(87)), (p(72), p(87)), p(3))
    pygame.draw.circle(surface, (241, 194, 112), (p(53), p(75)), p(2))
    pygame.draw.circle(surface, (241, 194, 112), (p(75), p(75)), p(2))
    return surface


def render_app_icon(size: int = 128) -> pygame.Surface:
    """Render the shared app icon at the requested square size."""
    if size < 1:
        raise ValueError("Icon size must be positive")
    master = _master_icon()
    if size == _MASTER_SIZE:
        return master
    return pygame.transform.smoothscale(master, (size, size))


def _png_bytes(surface: pygame.Surface, size: int) -> bytes:
    image = pygame.transform.smoothscale(surface, (size, size))
    stream = BytesIO()
    pygame.image.save(image, stream, "tarsgo-icon.png")
    return stream.getvalue()


def _ico_bytes(master: pygame.Surface) -> bytes:
    images = [(size, _dib_icon(master, size)) for size in _ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    payloads = bytearray()
    for size, payload in images:
        dimension = 0 if size == 256 else size
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        payloads.extend(payload)
        offset += len(payload)
    return header + entries + payloads


def _dib_icon(master: pygame.Surface, size: int) -> bytes:
    image = pygame.transform.smoothscale(master, (size, size))
    pixels = pygame.image.tostring(image, "BGRA", True)
    mask_row_bytes = ((size + 31) // 32) * 4
    and_mask = bytes(mask_row_bytes * size)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(pixels),
        0,
        0,
        0,
        0,
    )
    return header + pixels + and_mask


def _icns_bytes(master: pygame.Surface) -> bytes:
    chunks = bytearray()
    for size, chunk_type in _ICNS_TYPES.items():
        payload = _png_bytes(master, size)
        chunks.extend(chunk_type)
        chunks.extend(struct.pack(">I", len(payload) + 8))
        chunks.extend(payload)
    return b"icns" + struct.pack(">I", len(chunks) + 8) + chunks


def write_app_icons(output_dir: Path) -> dict[str, Path]:
    """Write a shared PNG master plus Windows ICO and macOS ICNS variants."""
    output_dir.mkdir(parents=True, exist_ok=True)
    master = _master_icon()
    master_path = output_dir / "tarsgo-master.png"
    pygame.image.save(master, master_path)

    ico_path = output_dir / "tarsgo.ico"
    ico_path.write_bytes(_ico_bytes(master))
    icns_path = output_dir / "tarsgo.icns"
    icns_path.write_bytes(_icns_bytes(master))
    return {"png": master_path, "ico": ico_path, "icns": icns_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate TARS-Go app icons.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/app-icons"),
        help="Directory for the generated shared PNG, ICO and ICNS files.",
    )
    arguments = parser.parse_args()
    write_app_icons(arguments.output_dir)


if __name__ == "__main__":
    main()
