import os
import sys
import threading
from pathlib import Path
from math import floor
from tkinter import Tk, StringVar, END, N, S, E, W
from tkinter import filedialog, messagebox
from tkinter import ttk

# Image libs
try:
    from PIL import Image, ImageOps
except ImportError:
    messagebox.showerror("Missing dependency", "Pillow is required.\nInstall with: pip install pillow")
    raise

# HEIC/HEIF support
heif_ok = True
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    heif_ok = False  # We'll warn in UI and skip HEIC if missing


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def cm_to_px(cm, dpi):
    inches = cm / 2.54
    return int(round(inches * dpi))


def compute_target_canvas(img_w, img_h, dpi):
    """
    Choose canvas orientation so the longer side of the picture maps to 15 cm.
    Landscape images -> 15cm x 10cm canvas
    Portrait images  -> 10cm x 15cm canvas
    Square defaults to landscape (15x10).
    Returns (target_w_px, target_h_px)
    """
    if img_w >= img_h:
        return cm_to_px(15, dpi), cm_to_px(10, dpi)
    else:
        return cm_to_px(10, dpi), cm_to_px(15, dpi)


def fit_with_letterbox(img, target_w, target_h, bg_color=(255, 255, 255)):
    """
    Resizes an image to fit inside target canvas without cropping.
    Adds white borders (letterbox/pillarbox) and centers the image.
    Returns an RGB PIL.Image of exact (target_w, target_h).
    """
    # Handle EXIF orientation before sizing
    img = ImageOps.exif_transpose(img)

    # Convert to RGBA to preserve transparency over white when pasting
    has_alpha = img.mode in ("RGBA", "LA") or ("transparency" in img.info)
    if has_alpha:
        img = img.convert("RGBA")
    else:
        img = img.convert("RGB")

    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(floor(src_w * scale)))
    new_h = max(1, int(floor(src_h * scale)))

    resized = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    off_x = (target_w - new_w) // 2
    off_y = (target_h - new_h) // 2

    if resized.mode == "RGBA":
        # Paste with alpha onto white
        canvas.paste(resized, (off_x, off_y), resized)
    else:
        canvas.paste(resized, (off_x, off_y))

    return canvas


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("10x15 Photo Formatter")
        self.root.geometry("760x520")
        self.root.minsize(720, 480)

        self.input_dir = StringVar(value="")
        self.output_dir = StringVar(value="")
        self.dpi_var = StringVar(value="300")
        self.status_var = StringVar(value="Select an input folder to begin.")
        self.heif_status = "(HEIC supported)" if heif_ok else "(HEIC not available - install pillow-heif)"

        self._build_ui()

        # Threading
        self.worker = None
        self.stop_flag = False

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(self.root)
        frm.grid(row=0, column=0, sticky=N + S + E + W)
        for i in range(4):
            frm.rowconfigure(i, weight=0)
        frm.rowconfigure(4, weight=1)
        frm.columnconfigure(1, weight=1)

        # Input folder
        ttk.Label(frm, text="Input folder:").grid(row=0, column=0, sticky=E, **pad)
        in_entry = ttk.Entry(frm, textvariable=self.input_dir)
        in_entry.grid(row=0, column=1, sticky=E + W, **pad)
        ttk.Button(frm, text="Browse…", command=self.choose_input).grid(row=0, column=2, **pad)

        # Output folder
        ttk.Label(frm, text="Output folder:").grid(row=1, column=0, sticky=E, **pad)
        out_entry = ttk.Entry(frm, textvariable=self.output_dir)
        out_entry.grid(row=1, column=1, sticky=E + W, **pad)
        ttk.Button(frm, text="Browse…", command=self.choose_output).grid(row=1, column=2, **pad)

        # DPI + HEIC status
        dpi_row = ttk.Frame(frm)
        dpi_row.grid(row=2, column=0, columnspan=3, sticky=E + W, **pad)
        ttk.Label(dpi_row, text="Print DPI:").pack(side="left")
        dpi_entry = ttk.Spinbox(dpi_row, from_=72, to=600, increment=1, textvariable=self.dpi_var, width=6)
        dpi_entry.pack(side="left", padx=8)
        ttk.Label(dpi_row, text="Canvas size per photo: 10 cm × 15 cm, no crop, white borders").pack(side="left", padx=12)
        ttk.Label(dpi_row, text=self.heif_status, foreground=("green" if heif_ok else "red")).pack(side="right")

        # Buttons
        btn_row = ttk.Frame(frm)
        btn_row.grid(row=3, column=0, columnspan=3, sticky=E + W, **pad)
        self.start_btn = ttk.Button(btn_row, text="Start", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        self.open_btn = ttk.Button(btn_row, text="Open Output Folder", command=self.open_output, state="disabled")
        self.open_btn.pack(side="right")

        # Progress + log
        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=4, column=0, columnspan=3, sticky=E + W, **pad)

        self.status = ttk.Label(frm, textvariable=self.status_var)
        self.status.grid(row=5, column=0, columnspan=3, sticky=E + W, padx=10, pady=(0, 6))

        self.log = ttk.Treeview(frm, columns=("msg",), show="headings", height=12)
        self.log.heading("msg", text="Log")
        self.log.grid(row=6, column=0, columnspan=3, sticky=N + S + E + W, padx=10, pady=(0, 10))
        frm.rowconfigure(6, weight=1)

    def choose_input(self):
        d = filedialog.askdirectory(title="Select input folder")
        if not d:
            return
        self.input_dir.set(d)
        # Default output
        out = Path(d) / "output_10x15_jpg"
        self.output_dir.set(str(out))

    def choose_output(self):
        d = filedialog.askdirectory(title="Select output folder")
        if not d:
            return
        self.output_dir.set(d)

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        in_dir = Path(self.input_dir.get().strip())
        out_dir = Path(self.output_dir.get().strip())
        dpi_str = self.dpi_var.get().strip()

        if not in_dir.exists():
            messagebox.showerror("Error", "Please select a valid input folder.")
            return

        try:
            dpi = int(dpi_str)
            if dpi < 72 or dpi > 600:
                raise ValueError
        except Exception:
            messagebox.showerror("Error", "Please enter a valid DPI between 72 and 600.")
            return

        out_dir.mkdir(parents=True, exist_ok=True)

        self.stop_flag = False
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.open_btn.config(state="disabled")
        self.clear_log()
        self.status_var.set("Scanning for images...")

        self.worker = threading.Thread(target=self.process_all, args=(in_dir, out_dir, dpi), daemon=True)
        self.worker.start()
        self.root.after(200, self.poll_worker)

    def stop(self):
        self.stop_flag = True
        self.status_var.set("Stopping after current file...")

    def open_output(self):
        out_dir = self.output_dir.get().strip()
        if not out_dir:
            return
        path = Path(out_dir)
        if path.exists():
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')

    def poll_worker(self):
        if self.worker and self.worker.is_alive():
            self.root.after(250, self.poll_worker)
        else:
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.open_btn.config(state="normal")

    def clear_log(self):
        for row in self.log.get_children():
            self.log.delete(row)

    def log_msg(self, msg):
        self.log.insert("", END, values=(msg,))
        # Keep the last message visible
        self.log.yview_moveto(1.0)

    def process_all(self, in_dir: Path, out_dir: Path, dpi: int):
        files = []
        for p in in_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                if p.suffix.lower() in (".heic", ".heif") and not heif_ok:
                    # Will log as skipped
                    files.append(p)
                else:
                    files.append(p)

        total = len(files)
        if total == 0:
            self.status_var.set("No supported images found.")
            return

        self.progress.config(maximum=total, value=0)
        self.status_var.set(f"Found {total} image(s). Processing...")

        processed = 0
        skipped = 0
        errors = 0

        for idx, f in enumerate(files, start=1):
            if self.stop_flag:
                self.status_var.set(f"Stopped by user. Processed: {processed}, Skipped: {skipped}, Errors: {errors}")
                break

            suffix = f.suffix.lower()
            if suffix in (".heic", ".heif") and not heif_ok:
                self.log_msg(f"SKIP (HEIC not supported): {f}")
                skipped += 1
                self.progress.config(value=idx)
                continue

            try:
                with Image.open(f) as im:
                    # Determine target canvas
                    im_oriented = ImageOps.exif_transpose(im)
                    w, h = im_oriented.size
                    target_w, target_h = compute_target_canvas(w, h, dpi)

                    # Fit to canvas with white borders
                    canvas = fit_with_letterbox(im_oriented, target_w, target_h, bg_color=(255, 255, 255))

                    # Prepare output filename (avoid collisions)
                    base = f.stem
                    out_name = f"{base}_10x15.jpg"
                    out_path = out_dir / out_name
                    n = 1
                    while out_path.exists():
                        out_name = f"{base}_10x15_{n}.jpg"
                        out_path = out_dir / out_name
                        n += 1

                    # Try to carry EXIF (though orientation already applied)
                    exif_bytes = im.info.get("exif")

                    save_kwargs = {
                        "format": "JPEG",
                        "quality": 95,
                        "subsampling": "4:2:0",
                        "optimize": True,
                        "progressive": True,
                        "dpi": (dpi, dpi),
                    }
                    if exif_bytes:
                        save_kwargs["exif"] = exif_bytes

                    canvas.save(out_path, **save_kwargs)
                    processed += 1
                    self.log_msg(f"OK: {f.name} -> {out_path.name}")

            except Exception as e:
                errors += 1
                self.log_msg(f"ERROR: {f.name} ({e})")

            self.progress.config(value=idx)
            self.status_var.set(f"Processed {processed}/{total} | Skipped {skipped} | Errors {errors}")

        if not self.stop_flag:
            self.status_var.set(f"Done. Processed {processed} | Skipped {skipped} | Errors {errors}")

    def run(self):
        self.root.mainloop()


def main():
    root = Tk()
    app = App(root)
    app.run()


if __name__ == "__main__":
    main()