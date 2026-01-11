# 10x15 Photo Formatter

A simple Python GUI tool to batch-convert images to print-ready 10×15 cm (4x6 inch) JPEGs without cropping. It auto-orients, resizes to fit, and adds white borders so the entire photo is preserved.

## Features

- **Zero-Crop Resizing:** Resizes images to fit inside 10×15 cm canvas; adds white borders ("letterboxing") so no part of the photo is cut off.
- **Smart Orientation:** Auto-detects landscape vs portrait logic based on image dimensions and EXIF data.
- **Wide Format Support:** Recursively scans folders for JPG/JPEG, PNG, WEBP, and **HEIC/HEIF** (iPhone photos).
- **Print Ready:** Exports high-quality JPEGs with embedded DPI (default 300, adjustable).
- **Cross-Platform:** Works on Windows, macOS (with window focus fixes), and Linux.

## Demo

![GUI](GUI.png)

## Quick Start (No manual setup)

This tool is packaged to run instantly using [pipx](https://pipx.pypa.io/). You do not need to manually install dependencies like Pillow.

### Prerequisites
You need Python installed. If you don't have `pipx` yet, install it once:
```bash
python -m pip install --user pipx
python -m pipx ensurepath
```

### Option 1: Run instantly (One-time use)
Use this if you just want to run the tool once without installing anything permanently on your computer.

```bash
pipx run --spec https://github.com/borelg/10x15cm-Photo-Formatter/archive/main.zip photo-formatter
```
*Note: This downloads the tool to a temporary cache, sets up the environment, runs it, and cleans up afterwards.*

### Option 2: Install permanently
Use this if you plan to use the tool frequently. This installs it as a command on your system.

**1. Install:**
```bash
pipx install https://github.com/borelg/10x15cm-Photo-Formatter/archive/main.zip
```

**2. Run:**
Now you can open the tool anytime from any terminal window by typing:
```bash
photo-formatter
```

---

## How it works

1.  **Scanning:** The app looks for images in your selected folder (recursive).
2.  **Orientation:** 
    - Landscape images → placed on a **15 cm × 10 cm** canvas.
    - Portrait images → placed on a **10 cm × 15 cm** canvas.
3.  **Scaling:** The image is resized to fit *inside* the canvas bounds using high-quality Lanczos resampling. White borders are added to fill empty space.
4.  **Output:** Saved as JPEG (Quality 95, Optimized, Progressive) with correct DPI metadata.
    - *Math:* 10×15 cm at 300 DPI ≈ 1181×1772 pixels.

## For Developers (Manual Setup)

If you want to contribute or modify the code:

```bash
# Clone the repository
git clone https://github.com/borelg/10x15cm-Photo-Formatter.git
cd 10x15cm-Photo-Formatter

# Install in editable mode (requires pip)
pip install -e .

# Run
photo-formatter
```