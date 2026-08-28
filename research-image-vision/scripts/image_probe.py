#!/usr/bin/env python3
"""Read-only, low-token image inspection helper for research-image-vision."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib


PNG_SIG = b"\x89PNG\r\n\x1a\n"


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def capabilities() -> dict:
    return {
        "pure_python": {
            "probe": True,
            "png_preview": True,
            "png_crop": True,
            "formats_probe": ["png", "jpeg", "gif", "bmp", "tiff", "webp"],
        },
        "modules": {
            "PIL": has_module("PIL"),
            "cv2": has_module("cv2"),
            "pytesseract": has_module("pytesseract"),
            "easyocr": has_module("easyocr"),
        },
        "executables": {
            "tesseract": shutil.which("tesseract"),
        },
    }


def ensure_out_dir(path: str | None) -> Path:
    out = Path(path or ".research-image-vision").resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def safe_stem(path: Path) -> str:
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in path.stem)
    return stem or "image"


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sniff_format(header: bytes) -> str | None:
    if header.startswith(PNG_SIG):
        return "png"
    if header.startswith(b"\xff\xd8"):
        return "jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"BM"):
        return "bmp"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    return None


def png_dimensions(data: bytes) -> dict:
    if not data.startswith(PNG_SIG):
        raise ValueError("not a PNG")
    if data[12:16] != b"IHDR":
        raise ValueError("PNG IHDR chunk not found")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", data[16:29]
    )
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "channels": channels,
        "compression": compression,
        "filter": filter_method,
        "interlace": interlace,
    }


def jpeg_dimensions(data: bytes) -> dict:
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0xD9):
            continue
        if marker == 0xDA:
            break
        if i + 2 > len(data):
            break
        length = struct.unpack(">H", data[i : i + 2])[0]
        if length < 2 or i + length > len(data):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            precision = data[i + 2]
            height, width = struct.unpack(">HH", data[i + 3 : i + 7])
            channels = data[i + 7]
            return {
                "width": width,
                "height": height,
                "bit_depth": precision,
                "channels": channels,
                "sof_marker": hex(marker),
            }
        i += length
    raise ValueError("JPEG size marker not found")


def gif_dimensions(data: bytes) -> dict:
    width, height = struct.unpack("<HH", data[6:10])
    return {"width": width, "height": height}


def bmp_dimensions(data: bytes) -> dict:
    width = struct.unpack("<i", data[18:22])[0]
    height = abs(struct.unpack("<i", data[22:26])[0])
    bit_depth = struct.unpack("<H", data[28:30])[0]
    return {"width": width, "height": height, "bit_depth": bit_depth}


def tiff_dimensions(data: bytes) -> dict:
    endian = "<" if data[:2] == b"II" else ">"
    offset = struct.unpack(endian + "I", data[4:8])[0]
    if offset + 2 > len(data):
        raise ValueError("TIFF IFD offset outside file")
    count = struct.unpack(endian + "H", data[offset : offset + 2])[0]
    pos = offset + 2
    width = height = None
    for _ in range(count):
        if pos + 12 > len(data):
            break
        tag, field_type, num_values, value = struct.unpack(endian + "HHII", data[pos : pos + 12])
        if tag in (256, 257) and num_values == 1:
            val = value if field_type in (3, 4) else None
            if tag == 256:
                width = val
            else:
                height = val
        pos += 12
    if not width or not height:
        raise ValueError("TIFF width/height tags not found")
    return {"width": width, "height": height}


def webp_dimensions(data: bytes) -> dict:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return {"width": width, "height": height, "variant": "VP8X"}
    if chunk == b"VP8L" and len(data) >= 25:
        b0, b1, b2, b3 = data[21:25]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return {"width": width, "height": height, "variant": "VP8L"}
    if chunk == b"VP8 " and len(data) >= 30:
        idx = data.find(b"\x9d\x01\x2a")
        if idx >= 0 and idx + 7 <= len(data):
            width, height = struct.unpack("<HH", data[idx + 3 : idx + 7])
            return {"width": width & 0x3FFF, "height": height & 0x3FFF, "variant": "VP8"}
    raise ValueError("WEBP dimensions not found")


def basic_metadata(path: Path) -> dict:
    data = path.read_bytes()
    header = data[:64]
    fmt = sniff_format(header)
    meta: dict = {
        "path": str(path.resolve()),
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "format": fmt,
    }
    try:
        if fmt == "png":
            meta.update(png_dimensions(data))
        elif fmt == "jpeg":
            meta.update(jpeg_dimensions(data))
        elif fmt == "gif":
            meta.update(gif_dimensions(data))
        elif fmt == "bmp":
            meta.update(bmp_dimensions(data))
        elif fmt == "tiff":
            meta.update(tiff_dimensions(data))
        elif fmt == "webp":
            meta.update(webp_dimensions(data))
    except Exception as exc:
        meta["dimension_error"] = str(exc)

    if has_module("PIL"):
        try:
            from PIL import Image

            with Image.open(path) as im:
                meta["pil"] = {
                    "format": im.format,
                    "mode": im.mode,
                    "width": im.width,
                    "height": im.height,
                    "n_frames": getattr(im, "n_frames", 1),
                    "exif_keys": len(getattr(im, "getexif", lambda: {})()),
                }
        except Exception as exc:
            meta["pil_error"] = str(exc)
    return meta


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def iter_png_chunks(data: bytes):
    if not data.startswith(PNG_SIG):
        raise ValueError("not a PNG")
    pos = len(PNG_SIG)
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        yield ctype, chunk_data
        pos += 12 + length
        if ctype == b"IEND":
            break


def read_png_rgba(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    info = png_dimensions(data)
    width = info["width"]
    height = info["height"]
    bit_depth = info["bit_depth"]
    color_type = info["color_type"]
    interlace = info["interlace"]
    if bit_depth != 8 or interlace != 0 or color_type not in (0, 2, 4, 6):
        raise ValueError("pure Python PNG preview supports only 8-bit non-interlaced grayscale/RGB/RGBA PNG")
    bpp = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    raw = zlib.decompress(b"".join(chunk for ctype, chunk in iter_png_chunks(data) if ctype == b"IDAT"))
    stride = width * bpp
    pos = 0
    prev = bytearray(stride)
    rgba = bytearray(width * height * 4)
    out_pos = 0
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        scan = bytearray(raw[pos : pos + stride])
        pos += stride
        for i in range(stride):
            left = scan[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            if filter_type == 1:
                scan[i] = (scan[i] + left) & 0xFF
            elif filter_type == 2:
                scan[i] = (scan[i] + up) & 0xFF
            elif filter_type == 3:
                scan[i] = (scan[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                scan[i] = (scan[i] + paeth(left, up, up_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError(f"unsupported PNG filter {filter_type}")
        for x in range(width):
            p = x * bpp
            if color_type == 0:
                r = g = b = scan[p]
                a = 255
            elif color_type == 2:
                r, g, b = scan[p], scan[p + 1], scan[p + 2]
                a = 255
            elif color_type == 4:
                r = g = b = scan[p]
                a = scan[p + 1]
            else:
                r, g, b, a = scan[p], scan[p + 1], scan[p + 2], scan[p + 3]
            rgba[out_pos : out_pos + 4] = bytes((r, g, b, a))
            out_pos += 4
        prev = scan
    return width, height, bytes(rgba)


def png_chunk(ctype: bytes, data: bytes) -> bytes:
    crc = binascii.crc32(ctype + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)


def write_png_rgba(path: Path, width: int, height: int, rgba: bytes) -> None:
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)
        start = y * stride
        rows.extend(rgba[start : start + stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = PNG_SIG + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", zlib.compress(bytes(rows))) + png_chunk(b"IEND", b"")
    path.write_bytes(data)


def resize_nearest(width: int, height: int, rgba: bytes, max_size: int) -> tuple[int, int, bytes]:
    if max(width, height) <= max_size:
        return width, height, rgba
    scale = max_size / max(width, height)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    out = bytearray(new_w * new_h * 4)
    for y in range(new_h):
        sy = min(height - 1, int(y / scale))
        for x in range(new_w):
            sx = min(width - 1, int(x / scale))
            src = (sy * width + sx) * 4
            dst = (y * new_w + x) * 4
            out[dst : dst + 4] = rgba[src : src + 4]
    return new_w, new_h, bytes(out)


def crop_rgba(width: int, height: int, rgba: bytes, roi: tuple[int, int, int, int]) -> tuple[int, int, bytes, tuple[int, int, int, int]]:
    x, y, w, h = roi
    if w <= 0 or h <= 0:
        raise ValueError("ROI width and height must be positive")
    x0 = max(0, min(width, x))
    y0 = max(0, min(height, y))
    x1 = max(x0, min(width, x + w))
    y1 = max(y0, min(height, y + h))
    out_w = x1 - x0
    out_h = y1 - y0
    if out_w <= 0 or out_h <= 0:
        raise ValueError("ROI does not overlap image")
    out = bytearray(out_w * out_h * 4)
    for row in range(out_h):
        src = ((y0 + row) * width + x0) * 4
        dst = row * out_w * 4
        out[dst : dst + out_w * 4] = rgba[src : src + out_w * 4]
    return out_w, out_h, bytes(out), (x0, y0, out_w, out_h)


def try_pillow_preview(path: Path, out_path: Path, max_size: int) -> bool:
    if not has_module("PIL"):
        return False
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((max_size, max_size))
        im.convert("RGBA").save(out_path, "PNG")
    return True


def try_pillow_crop(path: Path, out_path: Path, roi: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    if not has_module("PIL"):
        return None
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        x, y, w, h = roi
        x0 = max(0, min(im.width, x))
        y0 = max(0, min(im.height, y))
        x1 = max(x0, min(im.width, x + w))
        y1 = max(y0, min(im.height, y + h))
        if x1 <= x0 or y1 <= y0:
            raise ValueError("ROI does not overlap image")
        im.crop((x0, y0, x1, y1)).convert("RGBA").save(out_path, "PNG")
        return (x0, y0, x1 - x0, y1 - y0)


def make_preview(path: Path, out_dir: Path, max_size: int) -> dict:
    out_path = out_dir / f"{safe_stem(path)}_preview.png"
    method = None
    error = None
    try:
        if try_pillow_preview(path, out_path, max_size):
            method = "pillow"
    except Exception as exc:
        error = str(exc)
    if method is None:
        try:
            width, height, rgba = read_png_rgba(path)
            new_w, new_h, resized = resize_nearest(width, height, rgba, max_size)
            write_png_rgba(out_path, new_w, new_h, resized)
            method = "pure_png"
        except Exception as exc:
            return {
                "status": "unavailable",
                "reason": str(exc),
                "pillow_error": error,
                "requires": "Pillow for non-PNG or unsupported PNG variants",
            }
    return {"status": "ok", "path": str(out_path), "method": method, "max_size": max_size}


def parse_roi(value: str) -> tuple[int, int, int, int]:
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be x,y,w,h")
    try:
        return tuple(int(float(p)) for p in parts)  # type: ignore[return-value]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ROI values must be numeric") from exc


def make_crop(path: Path, out_dir: Path, roi: tuple[int, int, int, int]) -> dict:
    out_path = out_dir / f"{safe_stem(path)}_crop_{roi[0]}_{roi[1]}_{roi[2]}_{roi[3]}.png"
    method = None
    roi_used = None
    error = None
    try:
        roi_used = try_pillow_crop(path, out_path, roi)
        if roi_used is not None:
            method = "pillow"
    except Exception as exc:
        error = str(exc)
    if method is None:
        try:
            width, height, rgba = read_png_rgba(path)
            crop_w, crop_h, cropped, roi_used = crop_rgba(width, height, rgba, roi)
            write_png_rgba(out_path, crop_w, crop_h, cropped)
            method = "pure_png"
        except Exception as exc:
            return {
                "status": "unavailable",
                "reason": str(exc),
                "pillow_error": error,
                "requires": "Pillow for non-PNG or unsupported PNG variants",
            }
    return {"status": "ok", "path": str(out_path), "method": method, "roi_requested": roi, "roi_used": roi_used}


def run_ocr(path: Path, out_dir: Path) -> dict:
    text = ""
    method = None
    errors = []
    if shutil.which("tesseract"):
        try:
            proc = subprocess.run(
                ["tesseract", str(path), "stdout"],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0:
                text = proc.stdout
                method = "tesseract_executable"
            else:
                errors.append(proc.stderr.strip())
        except Exception as exc:
            errors.append(str(exc))
    if method is None and has_module("pytesseract") and has_module("PIL"):
        try:
            from PIL import Image
            import pytesseract

            with Image.open(path) as im:
                text = pytesseract.image_to_string(im)
            method = "pytesseract"
        except Exception as exc:
            errors.append(str(exc))
    if method is None and has_module("easyocr"):
        try:
            import easyocr

            reader = easyocr.Reader(["en"], gpu=False)
            results = reader.readtext(str(path), detail=0)
            text = "\n".join(results)
            method = "easyocr"
        except Exception as exc:
            errors.append(str(exc))
    if method is None:
        return {
            "status": "unavailable",
            "reason": "No local OCR tool found",
            "checked": ["tesseract executable", "pytesseract", "easyocr"],
            "errors": [e for e in errors if e],
        }
    txt_path = out_dir / f"{safe_stem(path)}_ocr.txt"
    txt_path.write_text(text, encoding="utf-8")
    return {"status": "ok", "method": method, "path": str(txt_path), "chars": len(text), "preview": text[:1000]}


def command_probe(args: argparse.Namespace) -> dict:
    image = Path(args.image).resolve()
    out_dir = ensure_out_dir(args.out_dir)
    result = {"command": "probe", "image": basic_metadata(image), "capabilities": capabilities()}
    out_path = out_dir / f"{safe_stem(image)}_probe.json"
    result["output_json"] = str(out_path)
    write_json(out_path, result)
    return result


def command_preview(args: argparse.Namespace) -> dict:
    image = Path(args.image).resolve()
    out_dir = ensure_out_dir(args.out_dir)
    result = {"command": "preview", "image": str(image), "preview": make_preview(image, out_dir, args.max_size)}
    out_path = out_dir / f"{safe_stem(image)}_preview.json"
    result["output_json"] = str(out_path)
    write_json(out_path, result)
    return result


def command_crop(args: argparse.Namespace) -> dict:
    image = Path(args.image).resolve()
    out_dir = ensure_out_dir(args.out_dir)
    result = {"command": "crop", "image": str(image), "crop": make_crop(image, out_dir, args.roi)}
    out_path = out_dir / f"{safe_stem(image)}_crop.json"
    result["output_json"] = str(out_path)
    write_json(out_path, result)
    return result


def command_ocr(args: argparse.Namespace) -> dict:
    image = Path(args.image).resolve()
    out_dir = ensure_out_dir(args.out_dir)
    result = {"command": "ocr", "image": str(image), "ocr": run_ocr(image, out_dir)}
    out_path = out_dir / f"{safe_stem(image)}_ocr.json"
    result["output_json"] = str(out_path)
    write_json(out_path, result)
    return result


def command_all(args: argparse.Namespace) -> dict:
    image = Path(args.image).resolve()
    out_dir = ensure_out_dir(args.out_dir)
    result = {
        "command": "all",
        "image": basic_metadata(image),
        "capabilities": capabilities(),
        "preview": make_preview(image, out_dir, args.max_size),
    }
    if args.roi:
        result["crop"] = make_crop(image, out_dir, args.roi)
    if args.ocr:
        result["ocr"] = run_ocr(image, out_dir)
    out_path = out_dir / f"{safe_stem(image)}_manifest.json"
    result["output_json"] = str(out_path)
    write_json(out_path, result)
    return result


def make_test_png(path: Path) -> None:
    width, height = 16, 12
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels.extend((x * 16 % 256, y * 20 % 256, 120, 255))
    write_png_rgba(path, width, height, bytes(pixels))


def command_self_test(args: argparse.Namespace) -> dict:
    out_dir = ensure_out_dir(args.out_dir)
    image = out_dir / "_self_test_input.png"
    make_test_png(image)
    probe = {"command": "probe", "image": basic_metadata(image), "capabilities": capabilities()}
    preview = make_preview(image, out_dir, 8)
    crop = make_crop(image, out_dir, (2, 2, 8, 6))
    result = {"command": "self-test", "test_image": str(image), "probe": probe, "preview": preview, "crop": crop}
    out_path = out_dir / "_self_test_manifest.json"
    result["output_json"] = str(out_path)
    write_json(out_path, result)
    if preview.get("status") != "ok" or crop.get("status") != "ok":
        result["status"] = "failed"
    else:
        result["status"] = "ok"
    return result


def print_result(result: dict) -> int:
    print(json.dumps(result, indent=2, ensure_ascii=False))
    status = result.get("status")
    if status == "failed":
        return 1
    for key in ("preview", "crop", "ocr"):
        value = result.get(key)
        if isinstance(value, dict) and value.get("status") == "unavailable":
            return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only image probe for low-token scientific image inspection.")
    parser.add_argument("--out-dir", default=".research-image-vision", help="Directory for derived outputs.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe", help="Read basic metadata and capabilities.")
    p.add_argument("image")
    p.set_defaults(func=command_probe)

    p = sub.add_parser("preview", help="Create a compact PNG preview.")
    p.add_argument("image")
    p.add_argument("--max-size", type=int, default=1200)
    p.set_defaults(func=command_preview)

    p = sub.add_parser("crop", help="Create a PNG crop from ROI x,y,w,h.")
    p.add_argument("image")
    p.add_argument("--roi", required=True, type=parse_roi)
    p.set_defaults(func=command_crop)

    p = sub.add_parser("ocr", help="Run local OCR if available.")
    p.add_argument("image")
    p.set_defaults(func=command_ocr)

    p = sub.add_parser("all", help="Run metadata, preview, optional crop, and optional OCR.")
    p.add_argument("image")
    p.add_argument("--max-size", type=int, default=1200)
    p.add_argument("--roi", type=parse_roi)
    p.add_argument("--ocr", action="store_true")
    p.set_defaults(func=command_all)

    p = sub.add_parser("self-test", help="Verify standard-library PNG probe/preview/crop.")
    p.set_defaults(func=command_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except FileNotFoundError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return print_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
