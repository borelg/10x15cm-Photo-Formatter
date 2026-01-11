import os
import sys
import threading
import platform
from pathlib import Path
from math import floor
from tkinter import Tk, StringVar, END, N, S, E, W
from tkinter import filedialog, messagebox
from tkinter import ttk

# --- Dependency Handling ---
try:
    from PIL import Image, ImageOps
except ImportError:
    # This fallback is mostly for manual runs; pipx handles this automatically via pyproject.toml
    messagebox.showerror("Missing dependency", "Pillow is required.\nInstall with: pip install pillow")
    raise

# HEIC/HEIF support
heif_ok = True
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    heif_ok = False

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}

def fix_resolution_scaling():
    """Enables High-DPI scaling on Windows so the GUI isn't blurry."""
    if platform.system() == "Windows":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

def cm_to_px(cm, dpi):
    inches = cm / 2.54
    return int(round(inches * dpi))

def compute_target_canvas(img_w, img_h, dpi):
    """
    Landscape images -> 15cm x 10cm canvas
    Portrait images  -> 10cm x 15cm canvas
    """
    if img_w >= img_h:
        return cm_to_px(15, dpi), cm_to_px(10, dpi)
    else:
        return cm_to_px(10, dpi), cm_to_px(15, dpi)

def fit_with_letterbox(img, target_w, target_h, bg_color=(255, 255, 255)):
    """
    Resizes image to fit inside target canvas without cropping.
    Adds white borders. Returns RGB PIL.Image.
    """
    img = ImageOps.exif_transpose(img)
    
    # Handle transparency
    has_alpha = img.mode in ("RGBA", "LA") or ("transparency" in img.info)
    if has_alpha:
        img = img.convert("RGBA")
    else:
        img = img.convert("RGB")

    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(floor(src_w * scale)))
    new_h = max(1, int(floor(src_h * scale)))

    # High-quality resize
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    off_x = (target_w - new_w) // 2
    off_y = (target_h - new_h) // 2

    if resized.mode == "RGBA":
        canvas.paste(resized, (off_x, off_y), resized)
    else:
        canvas.paste(resized, (off_x, off_y))

    return canvas

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("10x15 Photo Formatter")
        self.root.geometry("760x550")
        self.root.minsize(720, 480)

        # MacOS Focus Fix: Force window to front
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after_idle(self.root.attributes, '-topmost', False)

        self.input_dir = StringVar(value="")
        self.output_dir = StringVar(value="")
        self.dpi_var = StringVar(value="300")
        self.status_var = StringVar(value="Select an input folder to begin.")
        self.heif_status = "(HEIC supported)" if heif_ok else "(HEIC not available)"

        self._build_ui()

        # Threading
        self.worker = None
        self.stop_flag = False

    def _build_ui(self):
        style = ttk.Style()
        if platform.system() == "Windows":
            style.theme_use('vista')
        elif platform.system() == "Darwin":
            style.theme_use('clam') # Often looks cleaner on Mac Tkinter

        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(self.root)
        frm.grid(row=0, column=0, sticky=N + S + E + W)
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        for i in range(4):
            frm.rowconfigure(i, weight=0)
        frm.rowconfigure(4, weight=0) # Progress
        frm.rowconfigure(6, weight=1) # Log expands
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

        # DPI + Info
        dpi_row = ttk.Frame(frm)
        dpi_row.grid(row=2, column=0, columnspan=3, sticky=E + W, **pad)
        ttk.Label(dpi_row, text="Print DPI:").pack(side="left")
        ttk.Spinbox(dpi_row, from_=72, to=600, increment=1, textvariable=self.dpi_var, width=6).pack(side="left", padx=8)
        ttk.Label(dpi_row, text="Output: 10x15cm (4x6in)", font=("Arial", 9, "italic")).pack(side="left", padx=12)
        ttk.Label(dpi_row, text=self.heif_status, foreground=("green" if heif_ok else "red")).pack(side="right")

        # Buttons
        btn_row = ttk.Frame(frm)
        btn_row.grid(row=3, column=0, columnspan=3, sticky=E + W, **pad)
        self.start_btn = ttk.Button(btn_row, text="Start Processing", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btn_row, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        self.open_btn = ttk.Button(btn_row, text="Open Output Folder", command=self.open_output, state="disabled")
        self.open_btn.pack(side="right")

        # Progress Bar
        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=4, column=0, columnspan=3, sticky=E + W, **pad)

        # Status Label
        self.status = ttk.Label(frm, textvariable=self.status_var, relief="sunken", anchor="w")
        self.status.grid(row=5, column=0, columnspan=3, sticky=E + W, padx=10, pady=(0, 6))

        # Log View
        self.log = ttk.Treeview(frm, columns=("msg",), show="headings", selectmode="none")
        self.log.heading("msg", text="Process Log")
        self.log.column("msg", anchor="w")
        
        # Scrollbar for log
        scroll = ttk.Scrollbar(frm, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        
        self.log.grid(row=6, column=0, columnspan=2, sticky=N + S + E + W, padx=(10, 0), pady=(0, 10))
        scroll.grid(row=6, column=2, sticky=N + S + W, pady=(0, 10), padx=(0, 10))

    def choose_input(self):
        d = filedialog.askdirectory(title="Select input folder")
        if not d: return
        self.input_dir.set(d)
        out = Path(d) / "output_10x15_jpg"
        self.output_dir.set(str(out))

    def choose_output(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d: self.output_dir.set(d)

    def start(self):
        if self.worker and self.worker.is_alive(): return
        
        in_dir = Path(self.input_dir.get().strip())
        out_dir = Path(self.output_dir.get().strip())
        
        if not in_dir.exists() or not self.input_dir.get().strip():
            messagebox.showerror("Error", "Please select a valid input folder.")
            return

        try:
            dpi = int(self.dpi_var.get().strip())
            if not (72 <= dpi <= 1200): raise ValueError
        except:
            messagebox.showerror("Error", "DPI must be between 72 and 1200.")
            return

        out_dir.mkdir(parents=True, exist_ok=True)
        self.stop_flag = False
        self.toggle_controls(processing=True)
        self.clear_log()
        self.status_var.set("Initializing...")

        self.worker = threading.Thread(target=self.process_all, args=(in_dir, out_dir, dpi), daemon=True)
        self.worker.start()
        self.root.after(200, self.poll_worker)

    def toggle_controls(self, processing):
        state_start = "disabled" if processing else "normal"
        state_stop = "normal" if processing else "disabled"
        self.start_btn.config(state=state_start)
        self.stop_btn.config(state=state_stop)
        self.open_btn.config(state="disabled" if processing else "normal")

    def stop(self):
        self.stop_flag = True
        self.status_var.set("Stopping...")

    def open_output(self):
        path = Path(self.output_dir.get().strip())
        if not path.exists(): return
        
        if platform.system() == "Windows":
            os.startfile(str(path))
        elif platform.system() == "Darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')

    def poll_worker(self):
        if self.worker and self.worker.is_alive():
            self.root.after(250, self.poll_worker)
        else:
            self.toggle_controls(processing=False)

    def clear_log(self):
        self.log.delete(*self.log.get_children())

    def log_msg(self, msg, color=None):
        iid = self.log.insert("", END, values=(msg,))
        self.log.yview_moveto(1.0)

    def process_all(self, in_dir, out_dir, dpi):
        files = [p for p in in_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]
        
        total = len(files)
        if total == 0:
            self.status_var.set("No supported images found.")
            return

        self.progress.config(maximum=total, value=0)
        self.status_var.set(f"Found {total} images...")
        
        stats = {'ok': 0, 'skip': 0, 'err': 0}

        for idx, f in enumerate(files, 1):
            if self.stop_flag: break

            if f.suffix.lower() in (".heic", ".heif") and not heif_ok:
                self.log_msg(f"SKIP (HEIC missing): {f.name}")
                stats['skip'] += 1
                self.progress.config(value=idx)
                continue

            try:
                with Image.open(f) as im:
                    # Orientation & Sizing
                    im = ImageOps.exif_transpose(im)
                    w, h = im.size
                    tw, th = compute_target_canvas(w, h, dpi)
                    
                    canvas = fit_with_letterbox(im, tw, th)

                    # Unique Filename
                    base = f.stem
                    out_name = f"{base}_10x15.jpg"
                    dest = out_dir / out_name
                    counter = 1
                    while dest.exists():
                        dest = out_dir / f"{base}_10x15_{counter}.jpg"
                        counter += 1

                    # Save
                    exif = im.info.get("exif")
                    save_args = {"format": "JPEG", "quality": 95, "subsampling": 0, "dpi": (dpi, dpi)}
                    if exif: save_args["exif"] = exif
                    
                    canvas.save(dest, **save_args)
                    self.log_msg(f"OK: {f.name}")
                    stats['ok'] += 1

            except Exception as e:
                stats['err'] += 1
                self.log_msg(f"ERR: {f.name} - {str(e)}")

            self.progress.config(value=idx)
            self.status_var.set(f"Processing: {idx}/{total} (Errors: {stats['err']})")

        final_msg = "Done." if not self.stop_flag else "Stopped."
        self.status_var.set(f"{final_msg} Processed: {stats['ok']}, Skipped: {stats['skip']}, Errors: {stats['err']}")

def main():
    fix_resolution_scaling()
    root = Tk()
    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()