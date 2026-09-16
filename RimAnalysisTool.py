import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt

import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from datetime import datetime
import os
from statistics import mean, stdev


# ============================================================
# Rim Analysis Tool
# - Single-window Tkinter viewer + controls
# - Viewer-only zoom / pan / contrast enhancement
# - Measurements always use the untouched original image
# ============================================================

class RimAnalysisApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Rim Analysis Tool")
        self.root.geometry("1250x820")
        self.root.minsize(900, 650)

        # ---------- image / analysis state ----------
        self.img_path = None
        self.img_original = None          # untouched measurement source
        self.display_base = None          # viewer-only, uint8, 1/3/4 channel
        self.display_mode = "auto"        # "auto" or "original"

        self.intensity_data = None
        self.save_ready = False

        # ---------- display state ----------
        self.zoom_factor = 1.0
        self.min_zoom = 0.10
        self.max_zoom = 20.0
        self.photo_image = None

        self.brightness = 0.0
        self.contrast = 1.0

        # ---------- ROI state, ALWAYS in original image coordinates ----------
        self.ellipse_params = None        # [cx, cy, a, b, angle]
        self.bounds = None                # [left, right, top, bottom]
        self.drawing = False
        self.moving_handle = None
        self.start_point = None
        self.end_point = None

        self.shift_pressed = False
        self.alt_pressed = False

        self.base_handle_size = 5         # screen pixels; does NOT grow with zoom
        self.handle_hit_padding = 5

        # ---------- analysis options ----------
        self.color_choice = "white"
        self.thickness = 1
        self.smooth_enabled = False
        self.plot_color = "blue"

        # ---------- canvas item IDs ----------
        self.canvas_image_id = None
        self.roi_item_id = None
        self.handle_item_ids = []

        self._build_gui()
        self._bind_events()
        self._set_save_buttons(False)
        self.process_button.config(state=tk.DISABLED)

    # ========================================================
    # GUI
    # ========================================================

    def _build_gui(self):
        # Left: scrollable controls. Right: viewer.
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        # ---------------- Scrollable control panel (LEFT) ----------------
        controls_shell = ttk.Frame(self.root)
        controls_shell.grid(row=0, column=0, sticky="ns")
        controls_shell.rowconfigure(0, weight=1)
        controls_shell.columnconfigure(0, weight=1)

        self.control_canvas = tk.Canvas(
            controls_shell,
            width=310,
            highlightthickness=0,
            borderwidth=0
        )
        self.control_canvas.grid(row=0, column=0, sticky="ns")

        control_scroll = ttk.Scrollbar(
            controls_shell,
            orient="vertical",
            command=self.control_canvas.yview
        )
        control_scroll.grid(row=0, column=1, sticky="ns")
        self.control_canvas.configure(yscrollcommand=control_scroll.set)

        controls_outer = ttk.Frame(self.control_canvas, padding=10)
        self.controls_window_id = self.control_canvas.create_window(
            (0, 0),
            window=controls_outer,
            anchor="nw"
        )

        def _update_control_scrollregion(event=None):
            self.control_canvas.configure(
                scrollregion=self.control_canvas.bbox("all")
            )

        def _match_control_width(event):
            self.control_canvas.itemconfigure(
                self.controls_window_id,
                width=event.width
            )

        controls_outer.bind("<Configure>", _update_control_scrollregion)
        self.control_canvas.bind("<Configure>", _match_control_width)

        # Mouse wheel scrolls the control panel only while the pointer is over it.
        def _control_wheel(event):
            if event.delta:
                self.control_canvas.yview_scroll(
                    int(-1 * (event.delta / 120)),
                    "units"
                )
            return "break"

        self.control_canvas.bind(
            "<Enter>",
            lambda e: self.control_canvas.bind_all("<MouseWheel>", _control_wheel)
        )
        self.control_canvas.bind(
            "<Leave>",
            lambda e: self.control_canvas.unbind_all("<MouseWheel>")
        )

        # File
        file_box = ttk.LabelFrame(controls_outer, text="Image", padding=8)
        file_box.pack(fill="x", pady=(0, 8))

        ttk.Button(file_box, text="Load Image", command=self.choose_file).pack(fill="x")

        self.file_label_var = tk.StringVar(value="No image loaded")
        ttk.Label(
            file_box,
            textvariable=self.file_label_var,
            wraplength=260,
            justify="left"
        ).pack(fill="x", pady=(6, 0))

        # ROI
        roi_box = ttk.LabelFrame(controls_outer, text="Rim Selection", padding=8)
        roi_box.pack(fill="x", pady=(0, 8))

        ttk.Label(roi_box, text="Selection Color:").pack(anchor="w")
        self.color_menu = ttk.Combobox(
            roi_box,
            values=["white", "grey"],
            state="readonly",
            width=18
        )
        self.color_menu.set("white")
        self.color_menu.pack(fill="x", pady=(2, 6))
        self.color_menu.bind("<<ComboboxSelected>>", self._on_color_change)

        ttk.Label(roi_box, text="Rim Thickness (px):").pack(anchor="w")
        self.thickness_var = tk.IntVar(value=1)
        self.thickness_scale = tk.Scale(
            roi_box,
            from_=1,
            to=10,
            orient="horizontal",
            variable=self.thickness_var,
            command=self._on_thickness_change,
            showvalue=True,
            length=240
        )
        self.thickness_scale.pack(fill="x")

        self.smoothing_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            roi_box,
            text="Smooth Curve",
            variable=self.smoothing_var,
            command=self._on_smoothing_change
        ).pack(anchor="w", pady=(4, 0))

        ttk.Label(roi_box, text="Plot Color:").pack(anchor="w", pady=(6, 0))
        self.plot_color_menu = ttk.Combobox(
            roi_box,
            values=["blue", "red", "green", "black", "orange", "purple"],
            state="readonly",
            width=18
        )
        self.plot_color_menu.set("blue")
        self.plot_color_menu.pack(fill="x", pady=(2, 0))
        self.plot_color_menu.bind("<<ComboboxSelected>>", self._on_plot_color_change)

        # Display
        display_box = ttk.LabelFrame(
            controls_outer,
            text="Viewer Display (measurement unaffected)",
            padding=8
        )
        display_box.pack(fill="x", pady=(0, 8))

        self.display_status_var = tk.StringVar(value="Auto contrast")
        ttk.Label(
            display_box,
            textvariable=self.display_status_var
        ).pack(anchor="w", pady=(0, 4))

        # Kept internally because _render_view updates it, but the separate
        # Viewer Navigation section is intentionally gone.
        self.zoom_var = tk.StringVar(value="Zoom: 1.00x")

        ttk.Label(display_box, text="Brightness").pack(anchor="w")
        self.brightness_var = tk.DoubleVar(value=0.0)
        self.brightness_scale = tk.Scale(
            display_box,
            from_=-255,
            to=255,
            resolution=1,
            orient="horizontal",
            variable=self.brightness_var,
            command=self._on_brightness_change,
            length=250
        )
        self.brightness_scale.pack(fill="x")

        ttk.Label(display_box, text="Contrast").pack(anchor="w")
        self.contrast_var = tk.DoubleVar(value=1.0)
        self.contrast_scale = tk.Scale(
            display_box,
            from_=0.05,
            to=50.0,
            resolution=0.05,
            orient="horizontal",
            variable=self.contrast_var,
            command=self._on_contrast_change,
            length=250
        )
        self.contrast_scale.pack(fill="x")

        display_buttons = ttk.Frame(display_box)
        display_buttons.pack(fill="x", pady=(5, 0))
        for col in range(3):
            display_buttons.columnconfigure(col, weight=1)

        ttk.Button(
            display_buttons,
            text="Auto Contrast",
            command=self.use_auto_display
        ).grid(row=0, column=0, sticky="ew", padx=(0, 2))

        ttk.Button(
            display_buttons,
            text="Reset B/C",
            command=self.reset_display_to_original
        ).grid(row=0, column=1, sticky="ew", padx=2)

        ttk.Button(
            display_buttons,
            text="Fit Image",
            command=self.fit_image_to_window
        ).grid(row=0, column=2, sticky="ew", padx=(2, 0))

        # Processing / save
        action_box = ttk.LabelFrame(controls_outer, text="Analysis", padding=8)
        action_box.pack(fill="x", pady=(0, 8))

        self.process_button = ttk.Button(
            action_box,
            text="Process Image",
            command=self.process_image
        )
        self.process_button.pack(fill="x", pady=(0, 4))

        self.save_csv_button = ttk.Button(
            action_box,
            text="Save CSV",
            command=self.save_csv
        )
        self.save_csv_button.pack(fill="x", pady=2)

        self.save_plot_button = ttk.Button(
            action_box,
            text="Save Plot Image",
            command=self.save_plot_image
        )
        self.save_plot_button.pack(fill="x", pady=2)

        # Instructions -- use a true two-column grid so shortcuts and
        # descriptions stay aligned with proportional fonts and DPI scaling.
        help_box = ttk.LabelFrame(controls_outer, text="Controls & Shortcuts", padding=8)
        help_box.pack(fill="x", pady=(0, 8))
        help_box.columnconfigure(1, weight=1)

        row = 0

        ttk.Label(
            help_box,
            text="Viewer",
            font=("TkDefaultFont", 9, "bold")
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        viewer_shortcuts = [
            ("Mouse wheel", "Zoom at cursor"),
            ("Right-drag", "Pan image"),
            ("+ / -", "Zoom in / out"),
            ("0", "Reset zoom to 1:1"),
            ("F", "Fit image to viewer"),
        ]

        for shortcut, description in viewer_shortcuts:
            ttk.Label(help_box, text=shortcut).grid(
                row=row, column=0, sticky="nw", padx=(0, 12), pady=1
            )
            ttk.Label(
                help_box,
                text=description,
                wraplength=155,
                justify="left"
            ).grid(row=row, column=1, sticky="nw", pady=1)
            row += 1

        ttk.Separator(help_box, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=7
        )
        row += 1

        ttk.Label(
            help_box,
            text="Rim selection",
            font=("TkDefaultFont", 9, "bold")
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        selection_shortcuts = [
            ("LMB", "Draw ellipse"),
            ("Shift + LMB", "Draw circle"),
            ("Handles", "Adjust one side"),
            ("Shift + handle", "Adjust symmetrically"),
            ("Shift + Alt + handle", "Uniform circular adjustment"),
            ("D", "Redraw selection"),
            ("R", "Original display / reset B/C"),
        ]

        for shortcut, description in selection_shortcuts:
            ttk.Label(help_box, text=shortcut).grid(
                row=row, column=0, sticky="nw", padx=(0, 12), pady=1
            )
            ttk.Label(
                help_box,
                text=description,
                wraplength=155,
                justify="left"
            ).grid(row=row, column=1, sticky="nw", pady=1)
            row += 1

        # ---------------- Viewer area (RIGHT) ----------------
        viewer_frame = ttk.Frame(self.root)
        viewer_frame.grid(row=0, column=1, sticky="nsew")
        viewer_frame.rowconfigure(0, weight=1)
        viewer_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            viewer_frame,
            background="#202020",
            highlightthickness=0,
            cursor="crosshair"
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.h_scroll = ttk.Scrollbar(
            viewer_frame,
            orient="horizontal",
            command=self.canvas.xview
        )
        self.h_scroll.grid(row=1, column=0, sticky="ew")

        self.v_scroll = ttk.Scrollbar(
            viewer_frame,
            orient="vertical",
            command=self.canvas.yview
        )
        self.v_scroll.grid(row=0, column=1, sticky="ns")

        self.canvas.configure(
            xscrollcommand=self.h_scroll.set,
            yscrollcommand=self.v_scroll.set
        )

    def _bind_events(self):
        # Canvas mouse interactions
        self.canvas.bind("<ButtonPress-1>", self._on_left_down)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_up)

        # Windows / macOS / Linux mouse-wheel variants
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_at_canvas_point(1.25, e.x, e.y))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at_canvas_point(1 / 1.25, e.x, e.y))

        # Right mouse button pan
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_drag)

        # Keyboard modifiers / shortcuts
        self.root.bind_all("<KeyPress-Shift_L>", lambda e: self._set_shift(True))
        self.root.bind_all("<KeyPress-Shift_R>", lambda e: self._set_shift(True))
        self.root.bind_all("<KeyRelease-Shift_L>", lambda e: self._set_shift(False))
        self.root.bind_all("<KeyRelease-Shift_R>", lambda e: self._set_shift(False))

        self.root.bind_all("<KeyPress-Alt_L>", lambda e: self._set_alt(True))
        self.root.bind_all("<KeyPress-Alt_R>", lambda e: self._set_alt(True))
        self.root.bind_all("<KeyRelease-Alt_L>", lambda e: self._set_alt(False))
        self.root.bind_all("<KeyRelease-Alt_R>", lambda e: self._set_alt(False))

        self.root.bind_all("<KeyPress-d>", lambda e: self.clear_selection())
        self.root.bind_all("<KeyPress-D>", lambda e: self.clear_selection())
        self.root.bind_all("<KeyPress-r>", lambda e: self.reset_display_to_original())
        self.root.bind_all("<KeyPress-R>", lambda e: self.reset_display_to_original())
        self.root.bind_all("<KeyPress-plus>", lambda e: self.zoom_by(1.25))
        self.root.bind_all("<KeyPress-equal>", lambda e: self.zoom_by(1.25))
        self.root.bind_all("<KeyPress-minus>", lambda e: self.zoom_by(1 / 1.25))
        self.root.bind_all("<KeyPress-0>", lambda e: self.reset_zoom_1to1())
        self.root.bind_all("<KeyPress-f>", lambda e: self.fit_image_to_window())
        self.root.bind_all("<KeyPress-F>", lambda e: self.fit_image_to_window())

    # ========================================================
    # Image loading / viewer display
    # ========================================================

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.tif *.tiff")]
        )
        if not path:
            return

        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            messagebox.showerror("Error", "Failed to load image.")
            return

        self.img_path = path
        self.img_original = img
        self.file_label_var.set(os.path.basename(path))

        self.clear_selection(redraw=False)
        self.invalidate_previous_result()

        # New images start with viewer-only auto contrast.
        self.display_mode = "auto"
        self.brightness = 0.0
        self.contrast = 1.0
        self.brightness_var.set(0.0)
        self.contrast_var.set(1.0)
        self.display_status_var.set("Auto contrast")

        self._refresh_display_base()
        self.zoom_factor = 1.0
        self.process_button.config(state=tk.NORMAL)

        self._render_view()

        # Fit after geometry has updated, but never upscale absurdly.
        self.root.after(50, self.fit_image_to_window)

    def _preserve_display_channels(self, img):
        """
        Preserve channel coloring for the viewer.
        Measurement still uses self.img_original unchanged.

        OpenCV image order is BGR/BGRA; PIL/Tk display uses RGB/RGBA,
        so conversion to RGB happens later in _array_to_pil().
        """
        if img.ndim == 2:
            return img
        if img.ndim == 3 and img.shape[2] in (1, 3, 4):
            if img.shape[2] == 1:
                return img[:, :, 0]
            return img
        raise ValueError(f"Unsupported image shape: {img.shape}")

    def _make_original_display(self, img):
        """
        Linear unenhanced viewer mapping using the full dtype range.
        Preserves color channels.
        """
        arr = self._preserve_display_channels(img)

        if np.issubdtype(arr.dtype, np.integer):
            info = np.iinfo(arr.dtype)
            if info.max == info.min:
                return np.zeros(arr.shape, dtype=np.uint8)
            scaled = (
                arr.astype(np.float32) - float(info.min)
            ) * (255.0 / (float(info.max) - float(info.min)))
            return np.clip(scaled, 0, 255).astype(np.uint8)

        arr_f = arr.astype(np.float32)
        finite = arr_f[np.isfinite(arr_f)]
        if finite.size == 0:
            return np.zeros(arr.shape, dtype=np.uint8)

        lo = min(0.0, float(np.min(finite)))
        hi = float(np.max(finite))
        if hi <= lo:
            return np.zeros(arr.shape, dtype=np.uint8)

        scaled = (arr_f - lo) * (255.0 / (hi - lo))
        return np.clip(scaled, 0, 255).astype(np.uint8)

    def _make_auto_contrast_display(self, img):
        """
        Viewer-only percentile stretch.

        A single low/high pair is applied to all channels so RGB/BGR color
        relationships are preserved instead of converting the image to grey.
        """
        arr = self._preserve_display_channels(img).astype(np.float32)
        finite = arr[np.isfinite(arr)]

        if finite.size == 0:
            return np.zeros(arr.shape, dtype=np.uint8)

        nonzero = finite[finite > 0]
        sample = nonzero if nonzero.size >= 32 else finite

        lo = float(np.percentile(sample, 0.5))
        hi = float(np.percentile(sample, 99.5))

        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo = float(np.min(finite))
            hi = float(np.max(finite))

        if hi <= lo:
            return np.zeros(arr.shape, dtype=np.uint8)

        scaled = (arr - lo) * (255.0 / (hi - lo))
        return np.clip(scaled, 0, 255).astype(np.uint8)

    def _refresh_display_base(self):
        if self.img_original is None:
            self.display_base = None
            return

        if self.display_mode == "auto":
            self.display_base = self._make_auto_contrast_display(self.img_original)
        else:
            self.display_base = self._make_original_display(self.img_original)

    def _adjust_brightness_contrast(self, img):
        arr = img.astype(np.float32)
        arr = arr * float(self.contrast) + float(self.brightness)
        return np.clip(arr, 0, 255).astype(np.uint8)

    def _array_to_pil(self, arr):
        if arr.ndim == 2:
            return Image.fromarray(arr, mode="L")

        if arr.ndim == 3 and arr.shape[2] == 3:
            rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb)

        if arr.ndim == 3 and arr.shape[2] == 4:
            rgba = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGBA)
            return Image.fromarray(rgba)

        raise ValueError(f"Unsupported viewer array shape: {arr.shape}")

    def _render_view(self):
        if self.display_base is None:
            return

        adjusted = self._adjust_brightness_contrast(self.display_base)
        pil_img = self._array_to_pil(adjusted)

        new_w = max(1, int(round(pil_img.width * self.zoom_factor)))
        new_h = max(1, int(round(pil_img.height * self.zoom_factor)))

        if self.zoom_factor > 1.0:
            resample = Image.Resampling.NEAREST
        else:
            resample = Image.Resampling.LANCZOS

        if (new_w, new_h) != pil_img.size:
            pil_img = pil_img.resize((new_w, new_h), resample=resample)

        self.photo_image = ImageTk.PhotoImage(pil_img)

        if self.canvas_image_id is None:
            self.canvas_image_id = self.canvas.create_image(
                0, 0, anchor="nw", image=self.photo_image
            )
        else:
            self.canvas.itemconfig(self.canvas_image_id, image=self.photo_image)
            self.canvas.coords(self.canvas_image_id, 0, 0)

        self.canvas.config(scrollregion=(0, 0, new_w, new_h))
        self.zoom_var.set(f"Zoom: {self.zoom_factor:.2f}x")

        self._draw_roi()

    # ========================================================
    # Display controls
    # ========================================================

    def _on_brightness_change(self, value):
        self.brightness = float(value)
        if self.img_original is not None:
            self._render_view()

    def _on_contrast_change(self, value):
        self.contrast = float(value)
        if self.img_original is not None:
            self._render_view()

    def use_auto_display(self):
        if self.img_original is None:
            return
        self.display_mode = "auto"
        self.display_status_var.set("Auto contrast")
        self.brightness = 0.0
        self.contrast = 1.0
        self.brightness_var.set(0.0)
        self.contrast_var.set(1.0)
        self._refresh_display_base()
        self._render_view()

    def reset_display_to_original(self):
        """
        Reset B/C now means exactly what the user requested:
        original, unenhanced display plus neutral brightness/contrast.
        """
        if self.img_original is None:
            return
        self.display_mode = "original"
        self.display_status_var.set("Original / unenhanced")
        self.brightness = 0.0
        self.contrast = 1.0
        self.brightness_var.set(0.0)
        self.contrast_var.set(1.0)
        self._refresh_display_base()
        self._render_view()

    # ========================================================
    # Zoom / pan
    # ========================================================

    def _on_mousewheel(self, event):
        if self.img_original is None or event.delta == 0:
            return
        factor = 1.25 if event.delta > 0 else 1 / 1.25
        self._zoom_at_canvas_point(factor, event.x, event.y)
        return "break"

    def zoom_by(self, factor):
        if self.img_original is None:
            return
        # Zoom around the centre of the visible canvas.
        x = self.canvas.winfo_width() / 2
        y = self.canvas.winfo_height() / 2
        self._zoom_at_canvas_point(factor, x, y)

    def _zoom_at_canvas_point(self, factor, screen_x, screen_y):
        if self.img_original is None:
            return

        old_zoom = self.zoom_factor
        new_zoom = float(np.clip(
            old_zoom * factor,
            self.min_zoom,
            self.max_zoom
        ))

        if abs(new_zoom - old_zoom) < 1e-12:
            return

        # Image coordinate underneath the cursor BEFORE zoom.
        canvas_x_before = self.canvas.canvasx(screen_x)
        canvas_y_before = self.canvas.canvasy(screen_y)
        image_x = canvas_x_before / old_zoom
        image_y = canvas_y_before / old_zoom

        self.zoom_factor = new_zoom

        # Redraw and reposition in the same Tk event.  Flushing the resized
        # image before moving the viewport causes a brief visible "jump".
        self._render_view()

        # After zoom, scroll so the same image point remains under the cursor.
        target_canvas_x = image_x * new_zoom
        target_canvas_y = image_y * new_zoom

        image_w = self.img_original.shape[1] * new_zoom
        image_h = self.img_original.shape[0] * new_zoom
        visible_w = max(1, self.canvas.winfo_width())
        visible_h = max(1, self.canvas.winfo_height())

        desired_left = target_canvas_x - screen_x
        desired_top = target_canvas_y - screen_y

        max_left = max(0.0, image_w - visible_w)
        max_top = max(0.0, image_h - visible_h)

        desired_left = min(max(desired_left, 0.0), max_left)
        desired_top = min(max(desired_top, 0.0), max_top)

        if image_w > 0:
            self.canvas.xview_moveto(desired_left / image_w)
        if image_h > 0:
            self.canvas.yview_moveto(desired_top / image_h)

    def reset_zoom_1to1(self):
        if self.img_original is None:
            return
        self.zoom_factor = 1.0
        self._render_view()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def fit_image_to_window(self):
        if self.img_original is None:
            return

        self.root.update_idletasks()
        canvas_w = max(50, self.canvas.winfo_width())
        canvas_h = max(50, self.canvas.winfo_height())

        img_h, img_w = self.img_original.shape[:2]
        if img_w <= 0 or img_h <= 0:
            return

        fit = min(canvas_w / img_w, canvas_h / img_h)
        self.zoom_factor = float(np.clip(fit, self.min_zoom, self.max_zoom))

        self._render_view()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _on_pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _on_pan_drag(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    # ========================================================
    # ROI geometry / interaction
    # ========================================================

    def _set_shift(self, value):
        self.shift_pressed = bool(value)

    def _set_alt(self, value):
        self.alt_pressed = bool(value)

    def _event_to_image_point(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        return cx / self.zoom_factor, cy / self.zoom_factor

    def _calculate_ellipse(self):
        if self.start_point is None or self.end_point is None:
            return None

        x0, y0 = self.start_point
        x1, y1 = self.end_point

        width = abs(x1 - x0)
        height = abs(y1 - y0)
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0

        if self.shift_pressed:
            radius = max(width, height) / 2.0
            a = b = radius
        else:
            a = width / 2.0
            b = height / 2.0

        return [cx, cy, a, b, 0.0]

    def _calculate_bounds(self, params=None):
        p = self.ellipse_params if params is None else params
        if p is None:
            return None
        cx, cy, a, b, _ = p
        return [cx - a, cx + a, cy - b, cy + b]

    def _check_handle_hit(self, x, y):
        if self.bounds is None:
            return None

        left, right, top, bottom = self.bounds
        cx = (left + right) / 2.0
        cy = (top + bottom) / 2.0

        handles = {
            "center": (cx, cy),
            "left": (left, cy),
            "right": (right, cy),
            "top": (cx, top),
            "bottom": (cx, bottom),
        }

        hit_radius_image = (
            self.base_handle_size + self.handle_hit_padding
        ) / self.zoom_factor

        for name, (hx, hy) in handles.items():
            if abs(x - hx) <= hit_radius_image and abs(y - hy) <= hit_radius_image:
                return name

        return None

    def _adjust_bounds(self, x, y, handle):
        if self.bounds is None:
            return

        left, right, top, bottom = self.bounds
        cx = (left + right) / 2.0
        cy = (top + bottom) / 2.0

        if handle == "center":
            dx = x - cx
            dy = y - cy
            left += dx
            right += dx
            top += dy
            bottom += dy

        elif handle in ("left", "right"):
            if self.alt_pressed and self.shift_pressed:
                delta = abs(x - cx)
                left = cx - delta
                right = cx + delta
                top = cy - delta
                bottom = cy + delta
            elif self.shift_pressed:
                delta = abs(x - cx)
                left = cx - delta
                right = cx + delta
            elif handle == "left":
                left = x
            else:
                right = x

        elif handle in ("top", "bottom"):
            if self.alt_pressed and self.shift_pressed:
                delta = abs(y - cy)
                left = cx - delta
                right = cx + delta
                top = cy - delta
                bottom = cy + delta
            elif self.shift_pressed:
                delta = abs(y - cy)
                top = cy - delta
                bottom = cy + delta
            elif handle == "top":
                top = y
            else:
                bottom = y

        min_size = 1.0
        if right - left < min_size:
            if handle == "left":
                left = right - min_size
            else:
                right = left + min_size

        if bottom - top < min_size:
            if handle == "top":
                top = bottom - min_size
            else:
                bottom = top + min_size

        self.bounds = [left, right, top, bottom]
        self._update_ellipse_from_bounds()

    def _update_ellipse_from_bounds(self):
        left, right, top, bottom = self.bounds
        cx = (left + right) / 2.0
        cy = (top + bottom) / 2.0
        a = abs(right - left) / 2.0
        b = abs(bottom - top) / 2.0
        self.ellipse_params = [cx, cy, a, b, 0.0]

    def _on_left_down(self, event):
        if self.img_original is None:
            return

        self.canvas.focus_set()
        x, y = self._event_to_image_point(event)

        if self.ellipse_params is not None:
            handle = self._check_handle_hit(x, y)
            if handle is not None:
                self.moving_handle = handle
                return

        self.drawing = True
        self.start_point = (x, y)
        self.end_point = (x, y)
        self.invalidate_previous_result()

    def _on_left_drag(self, event):
        if self.img_original is None:
            return

        x, y = self._event_to_image_point(event)

        if self.drawing:
            self.end_point = (x, y)
            self._draw_roi(preview=True)
        elif self.moving_handle is not None:
            self._adjust_bounds(x, y, self.moving_handle)
            self.invalidate_previous_result()
            self._draw_roi()

    def _on_left_up(self, event):
        if self.img_original is None:
            return

        x, y = self._event_to_image_point(event)

        if self.drawing:
            self.drawing = False
            self.end_point = (x, y)
            self.ellipse_params = self._calculate_ellipse()
            self.bounds = self._calculate_bounds()
            self.invalidate_previous_result()

        self.moving_handle = None
        self._draw_roi()

    def clear_selection(self, redraw=True):
        self.drawing = False
        self.moving_handle = None
        self.start_point = None
        self.end_point = None
        self.ellipse_params = None
        self.bounds = None
        self.invalidate_previous_result()
        if redraw:
            self._draw_roi()

    def _delete_roi_items(self):
        if self.roi_item_id is not None:
            self.canvas.delete(self.roi_item_id)
            self.roi_item_id = None

        for item in self.handle_item_ids:
            self.canvas.delete(item)
        self.handle_item_ids = []

    def _draw_roi(self, preview=False):
        self._delete_roi_items()

        if self.img_original is None:
            return

        if preview and self.drawing:
            params = self._calculate_ellipse()
            if params is None:
                return
            roi_bounds = self._calculate_bounds(params)
        else:
            params = self.ellipse_params
            roi_bounds = self.bounds

        if params is None or roi_bounds is None:
            return

        cx, cy, a, b, _ = params

        x0 = (cx - a) * self.zoom_factor
        y0 = (cy - b) * self.zoom_factor
        x1 = (cx + a) * self.zoom_factor
        y1 = (cy + b) * self.zoom_factor

        color = "#ffffff" if self.color_choice == "white" else "#505050"

        # Rim thickness is in ORIGINAL IMAGE PIXELS, so the viewer line scales
        # with zoom. Handles, in contrast, remain fixed screen size.
        viewer_line_width = max(1, int(round(self.thickness * self.zoom_factor)))

        self.roi_item_id = self.canvas.create_oval(
            x0, y0, x1, y1,
            outline=color,
            width=viewer_line_width
        )

        left, right, top, bottom = roi_bounds
        rcx = (left + right) / 2.0
        rcy = (top + bottom) / 2.0

        handle_points = [
            (rcx, rcy),
            (left, rcy),
            (right, rcy),
            (rcx, top),
            (rcx, bottom),
        ]

        # Keep handles clearly visible above the rim at every zoom level.
        # The rim width scales with zoom because it represents image pixels,
        # so a fixed 5 px handle can otherwise disappear into the rim.
        #
        # Grow the handle just enough to remain larger than half the visible
        # rim width, but cap it so it never becomes excessively large.
        radius = max(
            self.base_handle_size,
            min(18, int(round(viewer_line_width / 2.0)) + 5)
        )

        # Add a contrasting border so handles remain distinguishable even
        # when their fill color matches the rim itself.
        handle_outline = "#000000" if self.color_choice == "white" else "#ffffff"

        for px, py in handle_points:
            sx = px * self.zoom_factor
            sy = py * self.zoom_factor
            item = self.canvas.create_oval(
                sx - radius,
                sy - radius,
                sx + radius,
                sy + radius,
                fill=color,
                outline=handle_outline,
                width=2
            )
            self.handle_item_ids.append(item)

    # ========================================================
    # Analysis
    # ========================================================

    def _sample_intensity_along_ellipse(self):
        if self.img_original is None or self.ellipse_params is None:
            return None

        cx, cy, a, b, angle = self.ellipse_params

        t = np.linspace(0, 2 * np.pi, 360)
        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        intensities = []

        for theta in t:
            profile_vals = []

            for offset in range(-self.thickness, self.thickness + 1):
                da = offset * np.cos(theta)
                db = offset * np.sin(theta)

                x = (
                    cx
                    + (a + da) * np.cos(theta) * cos_a
                    - (b + db) * np.sin(theta) * sin_a
                )
                y = (
                    cy
                    + (a + da) * np.cos(theta) * sin_a
                    + (b + db) * np.sin(theta) * cos_a
                )

                xi = int(np.clip(round(x), 0, self.img_original.shape[1] - 1))
                yi = int(np.clip(round(y), 0, self.img_original.shape[0] - 1))

                value = self.img_original[yi, xi]
                if np.ndim(value) > 0:
                    value = np.mean(value)

                profile_vals.append(float(value))

            intensities.append(np.mean(profile_vals))

        return np.degrees(t), np.array(intensities, dtype=float)

    @staticmethod
    def _smooth_curve(y, window=5):
        """
        Circular moving-average smoothing for angular rim profiles.

        The intensity profile represents a closed 0-360 degree loop, so values
        near 0 degrees must be averaged with values near 360 degrees rather
        than treated as an edge. Circular padding preserves that periodicity.
        """
        y = np.asarray(y, dtype=float)

        if y.size == 0 or window <= 1:
            return y.copy()

        # Keep the smoothing window odd so every output point has an equal
        # number of neighbours on both sides.
        if window % 2 == 0:
            window += 1

        # A window larger than the dataset is not meaningful here.
        window = min(window, y.size if y.size % 2 == 1 else y.size - 1)
        if window <= 1:
            return y.copy()

        pad = window // 2
        padded = np.pad(y, (pad, pad), mode="wrap")
        kernel = np.ones(window, dtype=float) / window

        return np.convolve(padded, kernel, mode="valid")

    def process_image(self):
        if self.img_original is None:
            messagebox.showwarning("Warning", "Load an image first.")
            return

        if self.ellipse_params is None:
            messagebox.showwarning("Warning", "Draw a rim selection first.")
            return

        result = self._sample_intensity_along_ellipse()
        if result is None:
            return

        self.intensity_data = result
        self.save_ready = True
        self._set_save_buttons(True)

        angles, intensities = result
        plot_vals = (
            self._smooth_curve(intensities)
            if self.smooth_enabled
            else intensities
        )

        plt.figure()
        plt.plot(angles, plot_vals, color=self.plot_color)
        plt.xlabel("Angle (degrees)")
        plt.ylabel("Intensity")
        plt.title("Rim Intensity Profile")
        plt.tight_layout()
        plt.show()

    def invalidate_previous_result(self):
        self.intensity_data = None
        self.save_ready = False
        self._set_save_buttons(False)

    # ========================================================
    # Option callbacks
    # ========================================================

    def _on_color_change(self, event=None):
        self.color_choice = self.color_menu.get()
        self._draw_roi()

    def _on_thickness_change(self, value):
        self.thickness = int(float(value))
        self.invalidate_previous_result()
        self._draw_roi()

    def _on_smoothing_change(self):
        self.smooth_enabled = bool(self.smoothing_var.get())

    def _on_plot_color_change(self, event=None):
        self.plot_color = self.plot_color_menu.get()

    # ========================================================
    # Saving
    # ========================================================

    def _set_save_buttons(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.save_csv_button.config(state=state)
        self.save_plot_button.config(state=state)

    def save_csv(self):
        if not self.save_ready or self.intensity_data is None:
            return

        angles, intensities = self.intensity_data
        output_intensities = (
            self._smooth_curve(intensities)
            if self.smooth_enabled
            else intensities
        )

        save_path = filedialog.asksaveasfilename(
            title="Save CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if not save_path:
            return

        try:
            with open(save_path, "w") as f:
                f.write("Angle (degrees),Intensity\n")
                for angle, intensity in zip(angles, output_intensities):
                    f.write(f"{angle:.2f},{intensity:.2f}\n")

            self._save_analysis_log(
                self.img_path,
                save_path,
                angles,
                output_intensities
            )
            messagebox.showinfo("Saved", f"CSV saved to:\n{save_path}")

        except Exception as exc:
            messagebox.showerror("Error", f"Failed to save file:\n{exc}")

    def _save_analysis_log(self, image_filename, csv_filename, angles, intensities):
        if len(intensities) == 0:
            return

        log_path = os.path.splitext(csv_filename)[0] + "_log.txt"

        settings = {
            "Rim Thickness": self.thickness,
            "Smoothing": "Enabled" if self.smooth_enabled else "Disabled",
            "Plot Color": self.plot_color,
            "Display Mode": self.display_mode,
            "Display Brightness": self.brightness,
            "Display Contrast": self.contrast,
            "Viewer Zoom": self.zoom_factor,
        }

        summary = {
            "Mean Intensity": mean(intensities),
            "Max Intensity": max(intensities),
            "Min Intensity": min(intensities),
            "Std Dev": stdev(intensities) if len(intensities) > 1 else 0.0,
        }

        with open(log_path, "w") as f:
            f.write(
                f"Analysis Log - "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            f.write(f"Image File: {os.path.basename(image_filename)}\n")
            f.write(f"CSV Output: {os.path.basename(csv_filename)}\n\n")

            f.write("Settings Used:\n")
            for key, value in settings.items():
                f.write(f"  {key}: {value}\n")

            f.write("\nResult Summary:\n")
            for key, value in summary.items():
                f.write(f"  {key}: {value:.2f}\n")

    def save_plot_image(self):
        if not self.save_ready or self.intensity_data is None:
            return

        angles, intensities = self.intensity_data
        plot_vals = (
            self._smooth_curve(intensities)
            if self.smooth_enabled
            else intensities
        )

        save_path = filedialog.asksaveasfilename(
            title="Save Plot as Image",
            defaultextension=".png",
            filetypes=[
                ("PNG files", "*.png"),
                ("SVG files", "*.svg"),
                ("All files", "*.*"),
            ]
        )
        if not save_path:
            return

        try:
            plt.figure()
            plt.plot(angles, plot_vals, color=self.plot_color)
            plt.xlabel("Angle (degrees)")
            plt.ylabel("Intensity")
            plt.title("Rim Intensity Profile")
            plt.tight_layout()

            if save_path.lower().endswith(".svg"):
                plt.savefig(save_path)
            else:
                plt.savefig(save_path, dpi=300)

            plt.close()
            messagebox.showinfo("Saved", f"Plot image saved to:\n{save_path}")

        except Exception as exc:
            messagebox.showerror("Error", f"Failed to save plot:\n{exc}")


def main():
    root = tk.Tk()
    app = RimAnalysisApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
