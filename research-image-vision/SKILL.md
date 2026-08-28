---
name: research-image-vision
description: "Low-token local inspection for scientific images, microscopy, gel/blot, fluorescence images, charts/plots, code screenshots, OCR, ROI cropping, image preprocessing, and structured visual extraction. Use for科研图像, 代码截图, 图像识别, OCR, 显微图, 凝胶图, Western blot, 荧光图, and tasks where Codex should identify image contents accurately without sending large images into context."
---

# Research Image Vision

## Overview

Use this skill to inspect research images and code screenshots with local, read-only preprocessing before asking the model to reason over pixels. Prefer metadata, previews, OCR text, and small ROI crops over repeatedly loading full-size images.

## Permission Rules

Default allowed work:
- Read user-provided or user-specified image files.
- Run local, read-only inspection in the sandbox.
- Write derived intermediate files only under the current workspace, normally `.research-image-vision/`.

Persistent permission pattern:
- For the user's outside-sandbox Python, request a narrow persistent rule only for this fixed script when needed:
  `py C:\Users\Jiach\.codex\skills\research-image-vision\scripts\image_probe.py ...`
- Do not request or imply broad persistent permission for arbitrary `python` or `py` commands.
- This rule is only for read-only image inspection and sandbox-local derived outputs.

Ask before:
- Installing dependencies such as Pillow, OpenCV, Tesseract, PaddleOCR, or EasyOCR.
- Using network services, cloud OCR, external APIs, or uploading images.
- Modifying, overwriting, deleting, or writing next to original input files.
- Writing outside the sandbox except the skill install/update path explicitly requested by the user.

## Workflow

1. Run `scripts/image_probe.py probe <image>` to capture format, size, mode, channels, available tool capabilities, and provenance.
2. Run `preview` or `all` to create a low-resolution preview in `.research-image-vision/`.
3. Crop only relevant panels, labels, code blocks, axes, scale bars, or uncertain regions with `crop --roi x,y,w,h`.
4. Run `ocr` when text, code, labels, legends, axis ticks, or annotations matter.
5. Give the model only the manifest, OCR text, and necessary crops instead of the full image whenever possible.
6. Report conclusions with uncertainty, important visual evidence, and any regions that need closer inspection.

## Script Usage

Use the script from the installed skill directory or the staged copy:

```powershell
py C:\Users\Jiach\.codex\skills\research-image-vision\scripts\image_probe.py all path\to\image.png --ocr
```

Commands:
- `probe <image>`: write and print image metadata JSON.
- `preview <image>`: create a compact PNG preview.
- `crop <image> --roi x,y,w,h`: create a PNG ROI crop.
- `ocr <image>`: use existing local OCR tools if present; otherwise return an unavailable status.
- `all <image>`: run metadata, preview, optional crop, and optional OCR.
- `self-test`: generate a small PNG and verify standard-library probe/preview/crop behavior.

The script uses Python standard library paths first. If Pillow, OpenCV, pytesseract, EasyOCR, or a `tesseract` executable already exists, it may use them; never install missing packages without asking.

## Output Discipline

Keep outputs compact:
- Prefer JSON summaries, OCR snippets, and ROI crops.
- Avoid embedding large base64 data or full-resolution image descriptions in chat.
- Name output files from the input stem plus operation, and keep them under `.research-image-vision/`.
- Preserve the original image unchanged.
