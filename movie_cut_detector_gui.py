#!/usr/bin/env python3
"""
movie_cut_detector_gui.py
------------------------
Tkinter GUI wrapper for movie_cut_detector.py.
App name: Movie Cut Detector  (for Plex)
Version:  v1.0.0

Bundles into a standalone Windows .exe via:
    build.bat   (or:  pyinstaller --onefile --windowed --name PlexCutDetector movie_cut_detector_gui.py)

All scanning logic lives in movie_cut_detector.py — this file only handles the UI.
Both files must be in the same directory when running from source.
"""

import os
import sys
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path

# ── Locate .env next to the executable / script ──────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

ENV_FILE    = BASE_DIR / ".env"
REPORT_FILE  = BASE_DIR / "movie_cut_report.json"
IGNORE_FILE  = BASE_DIR / "movie_cut_ignore.json"

# ── Colour palette (Plex-inspired) ───────────────────────────────────────────
BG_DARK    = "#1a1c21"
BG_CARD    = "#252830"
BG_ROW_A   = "#1e2028"
BG_ROW_B   = "#22252e"
BG_INPUT   = "#2c303a"
ACCENT     = "#e5a00d"       # Plex orange
ACCENT_HVR = "#f0b429"
TEXT_PRI   = "#e8e9ec"
TEXT_SEC   = "#8b90a0"
TEXT_WARN  = "#f5a623"
TEXT_ERR   = "#e05c5c"
TEXT_OK    = "#5cb85c"
BORDER     = "#383d4a"
FONT_UI    = ("Segoe UI", 10)
FONT_TITLE = ("Segoe UI Semibold", 11)
FONT_MONO  = ("Consolas", 9)
FONT_BIG   = ("Segoe UI Semibold", 13)


# ── .env helpers ─────────────────────────────────────────────────────────────

def load_env() -> dict:
    env = {"PLEX_URL": "http://localhost:32400", "PLEX_TOKEN": "", "TMDB_API_KEY": "", "PLEX_LIBRARY": "Movies"}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def save_env(values: dict):
    lines = []
    for k, v in values.items():
        lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


# ── Styled widgets ────────────────────────────────────────────────────────────

def styled_entry(parent, show=None, width=38):
    e = tk.Entry(parent, bg=BG_INPUT, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                 relief="flat", font=FONT_UI, bd=0, highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT,
                 width=width, show=show or "")
    return e


class PasswordEntry(tk.Frame):
    """
    A text entry with a toggleable eye icon on the right edge.
    Acts like a tk.Entry for .get() / .insert() / .delete().
    """
    EYE_OPEN   = "\U0001F441"   # Unicode eye emoji — fallback below
    EYE_CLOSED = "\U0001F648"   # see-no-evil monkey — fallback below

    def __init__(self, parent, width=30, **kw):
        super().__init__(parent, bg=BG_INPUT, highlightthickness=1,
                         highlightbackground=BORDER, bd=0)
        self._hidden = True

        self._entry = tk.Entry(
            self, bg=BG_INPUT, fg=TEXT_PRI, insertbackground=TEXT_PRI,
            relief="flat", font=FONT_UI, bd=0, highlightthickness=0,
            show="\u2022", width=width, **kw)
        self._entry.pack(side="left", fill="both", expand=True,
                         padx=(6, 28), pady=3)

        # Eye toggle button — sits inside the frame on the right
        self._eye_btn = tk.Label(
            self, text="\U0001F441", bg=BG_INPUT, fg=TEXT_SEC,
            font=("Segoe UI", 9), cursor="hand2", padx=4)
        self._eye_btn.place(relx=1.0, rely=0.5, anchor="e", x=-4)
        self._eye_btn.bind("<Button-1>", self._toggle)
        Tooltip(self._eye_btn, "Show / hide")

        # Focus highlight pass-through
        self._entry.bind("<FocusIn>",  lambda e: self.config(highlightbackground=ACCENT))
        self._entry.bind("<FocusOut>", lambda e: self.config(highlightbackground=BORDER))

    def _toggle(self, _event=None):
        self._hidden = not self._hidden
        self._entry.config(show="\u2022" if self._hidden else "")
        # Switch between filled-eye and slashed-eye using plain ASCII fallbacks
        # that render reliably on Windows without needing emoji fonts
        self._eye_btn.config(text="\U0001F441" if self._hidden else "\U0001F513")

    # Proxy the most-used Entry methods so callers can treat this as an Entry
    def get(self):          return self._entry.get()
    def insert(self, i, s): return self._entry.insert(i, s)
    def delete(self, a, b): return self._entry.delete(a, b)
    def config(self, **kw):
        # Allow frame-level highlight config AND entry-level config
        entry_keys = {"show", "state", "textvariable"}
        frame_kw   = {k: v for k, v in kw.items() if k not in entry_keys}
        entry_kw   = {k: v for k, v in kw.items() if k in entry_keys}
        if frame_kw: super().config(**frame_kw)
        if entry_kw: self._entry.config(**entry_kw)


def accent_button(parent, text, command, width=14):
    btn = tk.Button(
        parent, text=text, command=command,
        bg=ACCENT, fg="#1a1a1a", activebackground=ACCENT_HVR,
        activeforeground="#1a1a1a", relief="flat", font=("Segoe UI Semibold", 10),
        cursor="hand2", bd=0, padx=12, pady=6, width=width,
    )
    return btn


def ghost_button(parent, text, command, width=14):
    btn = tk.Button(
        parent, text=text, command=command,
        bg=BG_CARD, fg=TEXT_SEC, activebackground=BG_INPUT,
        activeforeground=TEXT_PRI, relief="flat", font=FONT_UI,
        cursor="hand2", bd=0, padx=12, pady=6, width=width,
        highlightthickness=1, highlightbackground=BORDER,
    )
    return btn


# ── Tooltip + Info popup ─────────────────────────────────────────────────────

class Tooltip:
    """Simple hover tooltip for any widget."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text   = text
        self.tw     = None
        widget.bind("<Enter>",  self._show)
        widget.bind("<Leave>",  self._hide)
        widget.bind("<Button>", self._hide)

    def _show(self, _event=None):
        if self.tw:
            return
        x = self.widget.winfo_rootx() + 24
        y = self.widget.winfo_rooty() + 24
        self.tw = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.configure(bg=BORDER)
        # Outer border frame
        inner = tk.Frame(tw, bg=BG_CARD, padx=12, pady=8)
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=self.text, bg=BG_CARD, fg=TEXT_PRI,
                 font=("Segoe UI", 9), justify="left",
                 wraplength=340).pack()

    def _hide(self, _event=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None


class InfoPopup:
    """
    Clicking the info icon opens a small popup with multi-line help text
    and optional clickable hyperlinks: [(label, url), ...]
    """
    def __init__(self, widget, title, body, links=None):
        self.widget = widget
        self.title  = title
        self.body   = body
        self.links  = links or []
        widget.bind("<Button-1>", self._open)
        widget.config(cursor="hand2")

    def _open(self, _event=None):
        popup = tk.Toplevel(self.widget)
        popup.title(self.title)
        popup.configure(bg=BG_DARK)
        popup.resizable(False, False)
        popup.grab_set()

        # Title bar
        tk.Label(popup, text=self.title, bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI Semibold", 11),
                 padx=18, pady=(12)).pack(anchor="w")

        ttk.Separator(popup, orient="horizontal").pack(fill="x", padx=14, pady=(0, 8))

        # Body text
        body_frame = tk.Frame(popup, bg=BG_DARK)
        body_frame.pack(fill="x", padx=18, pady=(0, 8))
        tk.Label(body_frame, text=self.body, bg=BG_DARK, fg=TEXT_PRI,
                 font=("Segoe UI", 10), justify="left",
                 wraplength=400).pack(anchor="w")

        # Hyperlinks
        if self.links:
            ttk.Separator(popup, orient="horizontal").pack(fill="x", padx=14, pady=(0, 8))
            link_frame = tk.Frame(popup, bg=BG_DARK)
            link_frame.pack(fill="x", padx=18, pady=(0, 4))
            tk.Label(link_frame, text="Helpful links:", bg=BG_DARK, fg=TEXT_SEC,
                     font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 4))
            for label, url in self.links:
                lnk = tk.Label(link_frame, text=f"  -> {label}",
                               bg=BG_DARK, fg="#5b9bd5",
                               font=("Segoe UI", 10, "underline"),
                               cursor="hand2")
                lnk.pack(anchor="w")
                lnk.bind("<Button-1>", lambda e, u=url: _open_url(u))

        # Close button
        tk.Frame(popup, bg=BG_DARK, height=8).pack()
        accent_button(popup, "Close", popup.destroy, width=10).pack(pady=(0, 14))

        # Centre over parent
        popup.update_idletasks()
        pw = popup.winfo_width()
        ph = popup.winfo_height()
        rx = self.widget.winfo_rootx()
        ry = self.widget.winfo_rooty()
        popup.geometry(f"+{rx - pw // 2 + 12}+{ry + 28}")


def info_icon(parent, row, col, title, body, links=None):
    """Place a small ⓘ label in the grid and attach an InfoPopup to it."""
    lbl = tk.Label(parent, text=" ⓘ", bg=BG_CARD, fg=TEXT_SEC,
                   font=("Segoe UI", 11))
    lbl.grid(row=row, column=col, sticky="w", padx=(0, 8))
    Tooltip(lbl, "Click for help")
    InfoPopup(lbl, title, body, links)
    return lbl


# ── Main application ──────────────────────────────────────────────────────────

class PlexCutApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Movie Cut Detector")
        self.configure(bg=BG_DARK)
        self.resizable(True, True)
        self.minsize(780, 620)

        # State
        self._scan_results   = []   # raw dicts from scanner
        self._plex_objects   = {}   # guid → plexapi movie objects
        self._check_vars     = {}   # (guid, label) → BooleanVar
        self._scan_thread    = None
        self._queue          = queue.Queue()
        self._cancel_flag    = threading.Event()  # set() to request cancel
        self._ignored_guids  = self._load_ignore_list()
        self.incremental_var = tk.BooleanVar(value=False)  # placeholder before _build_ui
        self._debug_enabled  = False              # thread-safe copy of debug_var

        self._build_ui()
        self._load_env_to_fields()
        self.after(100, self._poll_queue)

    # ── File I/O helpers ─────────────────────────────────────────────────────

    def _load_ignore_list(self):
        try:
            if IGNORE_FILE.exists():
                import json as _j
                return set(_j.loads(IGNORE_FILE.read_text(encoding="utf-8"))
                           .get("ignored_guids", []))
        except Exception:
            pass
        return set()

    def _save_ignore_list(self):
        import json as _j
        IGNORE_FILE.write_text(
            _j.dumps({"ignored_guids": sorted(self._ignored_guids)}, indent=2),
            encoding="utf-8")
        self._append_log(f"[dbg] Ignore list saved: {IGNORE_FILE}\n"
                         f"[dbg]   {len(self._ignored_guids)} entry/entries\n", "debug")

    def _save_report(self, results):
        """Write scan results to movie_cut_report.json.
        File write is always attempted first, logging second.
        Any exception shows a visible error so it can never silently fail.
        """
        incremental = getattr(self, "incremental_var", None) and self.incremental_var.get()
        written_path = None
        record_count = 0
        merge_mode   = False

        try:
            # ── FILE WRITE — no logging here, so exceptions are clean ──
            if incremental and REPORT_FILE.exists():
                merge_mode = True
                with open(REPORT_FILE, encoding="utf-8") as _f:
                    prev = json.load(_f)
                new_guids = {r["guid"] for r in results}
                merged = [r for r in prev if r.get("guid") not in new_guids] + results
                with open(REPORT_FILE, "w", encoding="utf-8") as _f:
                    json.dump(merged, _f, indent=2, ensure_ascii=False)
                written_path = REPORT_FILE
                record_count = len(merged)
            else:
                with open(REPORT_FILE, "w", encoding="utf-8") as _f:
                    json.dump(results, _f, indent=2, ensure_ascii=False)
                written_path = REPORT_FILE
                record_count = len(results)

        except Exception as e:
            # Write failed — show visible error regardless of debug mode
            err_msg = f"Could not save report: {e}"
            self._set_status(err_msg, "err")
            try:
                self._append_log(f"[dbg] ERROR saving report: {e}\n", "debug")
            except Exception:
                pass
            messagebox.showerror("Report save failed", err_msg)
            return

        # ── LOGGING — always visible in the log, plus debug detail ──
        try:
            if merge_mode:
                self._append_log(
                    f"  Report saved (merged — {record_count} total records)\n", "dim")
                self._append_log(
                    f"[dbg] Path: {written_path}\n", "debug")
            else:
                self._append_log(
                    f"  Report saved ({record_count} records)\n", "dim")
                self._append_log(
                    f"[dbg] Path: {written_path}\n", "debug")
        except Exception:
            pass  # logging failure never blocks the successful write

    def _ignore_movie(self, guid, title, year):
        self._ignored_guids.add(guid)
        self._save_ignore_list()
        self._set_status(f"Ignored: {title} ({year}) — won't appear in future scans.", "warn")
        if self._scan_results:
            self._build_results_list(self._scan_results)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        hdr = tk.Frame(self, bg=BG_DARK)
        hdr.pack(fill="x", padx=20, pady=(18, 0))

        tk.Label(hdr, text="🎬", bg=BG_DARK, font=("Segoe UI", 20)).pack(side="left")
        tk.Label(hdr, text="  Movie Cut Detector", bg=BG_DARK, fg=TEXT_PRI,
                 font=("Segoe UI Semibold", 16)).pack(side="left")
        tk.Label(hdr, text="  for Plex", bg=BG_DARK, fg=TEXT_SEC,
                 font=("Segoe UI", 11, "italic")).pack(side="left", pady=(4, 0))
        tk.Label(hdr, text="    identify & label alternate cuts in your library",
                 bg=BG_DARK, fg=TEXT_SEC, font=("Segoe UI", 10)).pack(side="left", pady=(4, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=20, pady=12)

        # ── Config card ──
        cfg = tk.Frame(self, bg=BG_CARD, bd=0, highlightthickness=1,
                       highlightbackground=BORDER)
        cfg.pack(fill="x", padx=20, pady=(0, 10))

        tk.Label(cfg, text="Connection Settings", bg=BG_CARD, fg=ACCENT,
                 font=FONT_TITLE).grid(row=0, column=0, columnspan=4,
                                       sticky="w", padx=14, pady=(12, 6))

        def lbl(parent, text, row, col):
            tk.Label(parent, text=text, bg=BG_CARD, fg=TEXT_SEC,
                     font=FONT_UI).grid(row=row, column=col, sticky="w",
                                        padx=(14, 6), pady=4)

        lbl(cfg, "Plex URL",      1, 0);  self.e_plex_url   = styled_entry(cfg, width=30)
        lbl(cfg, "Plex Token",    2, 0);  self.e_plex_token = PasswordEntry(cfg, width=30)
        lbl(cfg, "TMDb API Key",  3, 0);  self.e_tmdb_key   = PasswordEntry(cfg, width=30)
        lbl(cfg, "Library Name",  4, 0)
        self.e_library = styled_entry(cfg, width=30)

        self.e_plex_url  .grid(row=1, column=1, sticky="ew", padx=(0, 4), pady=4)
        self.e_plex_token.grid(row=2, column=1, sticky="ew", padx=(0, 4), pady=4)
        self.e_tmdb_key  .grid(row=3, column=1, sticky="ew", padx=(0, 4), pady=4)
        self.e_library   .grid(row=4, column=1, sticky="ew", padx=(0, 4), pady=4)

        # ── Info icons (column 2, immediately right of each field) ──
        info_icon(cfg, 1, 2, "Plex Server URL",
            "This is the address used to reach your Plex Media Server.\n\n"
            "LOCAL (same network as your server):\n"
            "  http://localhost:32400\n"
            "  http://192.168.x.x:32400\n"
            "  (replace 192.168.x.x with your server\'s local IP)\n\n"
            "REMOTE (different network, e.g. a laptop away from home):\n"
            "  Use your public IP and port shown in Plex Web:\n"
            "  http://YOUR.PUBLIC.IP:PORT\n\n"
            "  To find your public IP and port:\n"
            "  1. Open Plex Web on your server machine\n"
            "  2. Go to Settings -> Remote Access\n"
            "  3. The Public IP and port are shown there\n"
            "     e.g.  Public  YOUR.PUBLIC.IP : PORT\n"
            "  4. Your remote URL would be:\n"
            "     http://YOUR.PUBLIC.IP:PORT\n\n"
            "  Note: port forwarding must be enabled on your router\n"
            "  for remote access to work.",
            links=[
                ("Plex Remote Access setup guide",
                 "https://support.plex.tv/articles/200289506-remote-access/"),
                ("What is my public IP?",
                 "https://www.whatismyip.com/"),
            ])

        info_icon(cfg, 2, 2, "Plex Token",
            "Your Plex Token (X-Plex-Token) lets this app talk to your server.\n"
            "Keep it private — it grants full access to your Plex account.\n\n"
            "How to find it:\n"
            "  1. Sign in to Plex Web App in your browser\n"
            "  2. Browse to any movie in your library\n"
            "  3. Click the three-dot menu (...) on that movie\n"
            "  4. Choose \'Get Info\'\n"
            "  5. In the Get Info panel, click \'View XML\'\n"
            "  6. A new browser tab opens with XML data\n"
            "  7. Look in the URL bar for:\n"
            "       ?X-Plex-Token=XXXXXXXXXXXXXXXXX\n"
            "  8. Copy that value (after the = sign) — that is your token\n\n"
            "The official Plex guide (link below) has screenshots.",
            links=[
                ("How to find your Plex token (official Plex guide)",
                 "https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/"),
            ])

        info_icon(cfg, 3, 2, "TMDb API Key",
            "The Movie Database (TMDb) API key is free and used to look up\n"
            "movie runtimes and edition information.\n\n"
            "How to get one:\n"
            "  1. Create a free account at themoviedb.org\n"
            "  2. Go to Settings -> API\n"
            "  3. Request an API key (choose \'Developer\')\n"
            "  4. Copy the \'API Key (v3 auth)\' value here\n\n"
            "Without this key, runtime comparison is disabled and\n"
            "fewer alternate cuts will be detected.",
            links=[
                ("Create a free TMDb account",
                 "https://www.themoviedb.org/signup"),
                ("TMDb API settings page",
                 "https://www.themoviedb.org/settings/api"),
            ])

        info_icon(cfg, 4, 2, "Library Name",
            "The exact name of your Plex movie library section as it appears\n"
            "in the Plex sidebar. This is case-sensitive.\n\n"
            "Common examples:\n"
            "  Movies\n"
            "  4K Movies\n"
            "  Films\n"
            "  Home Videos\n\n"
            "If you have multiple movie libraries, run the tool once\n"
            "per library by changing this name between runs.\n\n"
"Common examples:\n"
"  Movies\n"
"  4K Movies\n"
"  Films")

        # Limit field
        lbl(cfg, "Scan limit (0=all)", 1, 3)
        self.e_limit = styled_entry(cfg, width=6)
        self.e_limit.insert(0, "0")
        self.e_limit.grid(row=1, column=4, sticky="w", pady=4, padx=(0, 14))

        # Dry run + Incremental checkboxes
        self.dry_run_var = tk.BooleanVar(value=False)
        cb = tk.Checkbutton(cfg, text="Dry run (no writes)", variable=self.dry_run_var,
                            bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_INPUT,
                            activebackground=BG_CARD, activeforeground=TEXT_PRI,
                            font=FONT_UI, cursor="hand2")
        cb.grid(row=2, column=3, columnspan=2, sticky="w", padx=(14, 0))
        self.incremental_var = tk.BooleanVar(value=False)
        inc_cb = tk.Checkbutton(cfg, text="Incremental (skip already-scanned)",
                                variable=self.incremental_var,
                                bg=BG_CARD, fg=TEXT_SEC, selectcolor=BG_INPUT,
                                activebackground=BG_CARD, activeforeground=TEXT_PRI,
                                font=FONT_UI, cursor="hand2")
        inc_cb.grid(row=3, column=3, columnspan=2, sticky="w", padx=(14, 0))
        Tooltip(inc_cb, "Skip movies already processed in a previous run.\n"
                        "Uses movie_cut_report.json to find prior results.")

        # Save + Run + Cancel buttons
        btn_row = tk.Frame(cfg, bg=BG_CARD)
        btn_row.grid(row=5, column=0, columnspan=5, sticky="e", padx=14, pady=(8, 14))
        ghost_button(btn_row, "Save Settings", self._save_settings, width=14).pack(side="left", padx=(0, 8))
        self.btn_run = accent_button(btn_row, "\u25b6  Run Scan", self._start_scan, width=14)
        self.btn_run.pack(side="left", padx=(0, 6))
        self.btn_cancel = tk.Button(
            btn_row, text="\u25a0  Cancel", command=self._cancel_scan,
            bg="#3a2020", fg=TEXT_ERR, activebackground="#4a2828",
            activeforeground=TEXT_ERR, relief="flat",
            font=("Segoe UI Semibold", 10), cursor="hand2",
            bd=0, padx=12, pady=6, width=10,
            highlightthickness=1, highlightbackground="#5a3030",
            state="disabled"
        )
        self.btn_cancel.pack(side="left")

        cfg.columnconfigure(1, weight=1)

        # ── Scan status panel (hidden until scan starts) ──
        self.progress_var = tk.DoubleVar(value=0)
        self._progress_frame = tk.Frame(self, bg=BG_CARD, highlightthickness=1,
                                        highlightbackground=BORDER)
        # Don't pack yet — shown only when scanning

        status_inner = tk.Frame(self._progress_frame, bg=BG_CARD)
        status_inner.pack(fill="x", padx=12, pady=(8, 4))

        # Top row: spinner label + current movie title
        top_row = tk.Frame(status_inner, bg=BG_CARD)
        top_row.pack(fill="x")
        self._spinner_lbl = tk.Label(top_row, text="", bg=BG_CARD, fg=ACCENT,
                                     font=("Consolas", 11), width=2)
        self._spinner_lbl.pack(side="left")
        self.progress_lbl = tk.Label(top_row, text="Starting...",
                                     bg=BG_CARD, fg=TEXT_PRI, font=FONT_UI,
                                     anchor="w")
        self.progress_lbl.pack(side="left", fill="x", expand=True)

        # Counter label: "42 / 1,204 movies"
        self._counter_lbl = tk.Label(top_row, text="", bg=BG_CARD,
                                     fg=TEXT_SEC, font=FONT_MONO)
        self._counter_lbl.pack(side="right")

        # Progress bar
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
                        fieldbackground=BG_INPUT, background=BG_CARD,
                        foreground=TEXT_PRI, selectbackground=ACCENT,
                        selectforeground="#1a1a1a", bordercolor=BORDER,
                        arrowcolor=TEXT_SEC)
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", BG_INPUT)],
                  background=[("active", BG_INPUT)])
        style.configure("Plex.Horizontal.TProgressbar",
                        troughcolor=BG_INPUT, background=ACCENT,
                        bordercolor=BG_CARD, lightcolor=ACCENT, darkcolor=ACCENT)
        self.progress_bar = ttk.Progressbar(status_inner,
                                            variable=self.progress_var,
                                            style="Plex.Horizontal.TProgressbar",
                                            maximum=100)
        self.progress_bar.pack(fill="x", pady=(4, 0))

        # Stats row: found / skipped / errors so far
        stats_row = tk.Frame(status_inner, bg=BG_CARD)
        stats_row.pack(fill="x", pady=(4, 6))
        self._stat_found = tk.Label(stats_row, text="proposed: 0",
                                    bg=BG_CARD, fg=TEXT_OK, font=FONT_MONO)
        self._stat_found.pack(side="left", padx=(0, 16))
        self._stat_has_ed = tk.Label(stats_row, text="has edition: 0",
                                     bg=BG_CARD, fg=TEXT_SEC, font=FONT_MONO)
        self._stat_has_ed.pack(side="left", padx=(0, 16))
        self._stat_errors = tk.Label(stats_row, text="errors: 0",
                                     bg=BG_CARD, fg=TEXT_ERR, font=FONT_MONO)
        self._stat_errors.pack(side="left")
        self._eta_lbl = tk.Label(stats_row, text="",
                                 bg=BG_CARD, fg=TEXT_SEC, font=FONT_MONO)
        self._eta_lbl.pack(side="right")

        # Internal running counters updated during scan
        self._cnt_proposed    = 0
        self._cnt_errors      = 0
        self._cnt_has_edition = 0
        self._scan_total    = 0
        self._spinner_idx   = 0
        self._spinner_chars = ["|", "/", "-", "\\"]
        self._movie_timestamps = []  # (idx, timestamp) rolling window for ETA

        # ── Tabbed results pane ──
        nb_style = ttk.Style()
        nb_style.configure("Dark.TNotebook", background=BG_DARK, borderwidth=0)
        nb_style.configure("Dark.TNotebook.Tab",
                           background=BG_CARD, foreground=TEXT_SEC,
                           padding=(12, 4), font=FONT_UI)
        nb_style.map("Dark.TNotebook.Tab",
                     background=[("selected", BG_INPUT)],
                     foreground=[("selected", TEXT_PRI)])
        # Outer container holds notebook on the left and log panel on the right
        main_area = tk.Frame(self, bg=BG_DARK)
        main_area.pack(fill="both", expand=True, padx=20, pady=(0, 4))
        self._main_area = main_area

        self._notebook = ttk.Notebook(main_area, style="Dark.TNotebook")
        self._notebook.pack(side="left", fill="both", expand=True)

        # Tab 1: Scan results
        scan_tab = tk.Frame(self._notebook, bg=BG_DARK)
        self._notebook.add(scan_tab, text="  Scan Results  ")

        # Tab 2: Remove editions
        undo_tab = tk.Frame(self._notebook, bg=BG_DARK)
        self._notebook.add(undo_tab, text="  Remove Editions  ")
        self._build_undo_tab(undo_tab)

        results_outer = scan_tab
        self._results_outer = scan_tab

        # Left: proposals list
        left = tk.Frame(results_outer, bg=BG_DARK)
        left.pack(side="left", fill="both", expand=True)

        res_header = tk.Frame(left, bg=BG_DARK)
        res_header.pack(fill="x")
        tk.Label(res_header, text="Proposed Label Changes",
                 bg=BG_DARK, fg=TEXT_PRI, font=FONT_TITLE).pack(side="left")

        # Inline info icon explaining the runtime columns
        info_lbl = tk.Label(res_header, text=" ⓘ", bg=BG_DARK, fg=TEXT_SEC,
                            font=("Segoe UI", 11), cursor="hand2")
        info_lbl.pack(side="left", pady=(1,0))
        Tooltip(info_lbl, "Click for help reading the results")
        InfoPopup(info_lbl, "Reading the Results",
            "Each movie shows three runtime values:\n\n"
            "  Plex: X  — the actual duration of your file\n"
            "  TMDb theatrical: X  — the runtime of the standard\n"
            "    theatrical release as listed on TMDb\n"
            "  +Xm / -Xm diff  — how much longer or shorter\n"
            "    your file is compared to the theatrical cut\n\n"
            "A positive diff (+) means your file is LONGER than\n"
            "theatrical — suggesting an extended or director\'s cut.\n\n"
            "A negative diff (-) means your file is SHORTER —\n"
            "suggesting a theatrical or TV cut.\n\n"
            "A zero or small diff means your file likely matches\n"
            "the standard theatrical release, but TMDb metadata\n"
            "(release notes or alt titles) still flagged a known\n"
            "alternate cut for this title.\n\n"
            "TMDb\'s theatrical runtime is the baseline — it does\n"
            "not store per-cut runtimes, so the suggestion is based\n"
            "on metadata clues (release notes, alternative titles)."
        )

        self.lbl_count = tk.Label(res_header, text="", bg=BG_DARK, fg=TEXT_SEC, font=FONT_UI)
        self.lbl_count.pack(side="left", padx=8)

        # Approve-all checkbox
        self.approve_all_var = tk.BooleanVar(value=False)
        tk.Checkbutton(res_header, text="Approve All",
                       variable=self.approve_all_var,
                       command=self._toggle_all,
                       bg=BG_DARK, fg=ACCENT, selectcolor=BG_INPUT,
                       activebackground=BG_DARK, activeforeground=ACCENT,
                       font=("Segoe UI Semibold", 10),
                       cursor="hand2").pack(side="right")

        # Show-existing-editions checkbox
        self.show_existing_var = tk.BooleanVar(value=False)
        show_existing_cb = tk.Checkbutton(
            res_header, text="Show media with existing tags",
            variable=self.show_existing_var,
            command=self._refresh_results_filter,
            bg=BG_DARK, fg=TEXT_SEC, selectcolor=BG_INPUT,
            activebackground=BG_DARK, activeforeground=TEXT_PRI,
            font=("Segoe UI", 9), cursor="hand2")
        show_existing_cb.pack(side="right", padx=(0, 12))
        Tooltip(show_existing_cb,
                "Show media that already has an edition tag set in Plex.\n"
                "These are hidden by default. Checking this lets you review\n"
                "or overwrite existing edition tags.")

        # Scrollable canvas for checkboxes
        canvas_frame = tk.Frame(left, bg=BG_CARD, highlightthickness=1,
                                highlightbackground=BORDER)
        canvas_frame.pack(fill="both", expand=True, pady=(6, 0))

        self.canvas = tk.Canvas(canvas_frame, bg=BG_CARD, highlightthickness=0,
                                bd=0)
        vscroll = ttk.Scrollbar(canvas_frame, orient="vertical",
                                command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.list_frame = tk.Frame(self.canvas, bg=BG_CARD)
        self._canvas_window = self.canvas.create_window(
            (0, 0), window=self.list_frame, anchor="nw")
        self.list_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # ── Debug log panel — right side of main_area, hidden by default ──
        self._log_panel = tk.Frame(main_area, bg=BG_DARK, width=300)
        self._log_panel.pack_propagate(False)
        # Not packed yet — shown when Debug checkbox is checked

        log_header = tk.Frame(self._log_panel, bg=BG_DARK)
        log_header.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(log_header, text="Scan Log", bg=BG_DARK, fg=TEXT_PRI,
                 font=FONT_TITLE).pack(side="left")

        self.log_box = scrolledtext.ScrolledText(
            self._log_panel, bg=BG_CARD, fg=TEXT_SEC, font=FONT_MONO,
            state="disabled", relief="flat", bd=0,
            highlightthickness=1, highlightbackground=BORDER,
            wrap="word", width=32,
        )
        self.log_box.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.log_box.tag_config("ok",    foreground=TEXT_OK)
        self.log_box.tag_config("warn",  foreground=TEXT_WARN)
        self.log_box.tag_config("err",   foreground=TEXT_ERR)
        self.log_box.tag_config("dim",   foreground=TEXT_SEC)
        self.log_box.tag_config("acc",   foreground=ACCENT)
        self.log_box.tag_config("debug", foreground="#5a6080")

        # ── Bottom action bar ──
        bar = tk.Frame(self, bg=BG_DARK)
        bar.pack(fill="x", padx=20, pady=(6, 14))


        self.lbl_status = tk.Label(bar, text="Ready.", bg=BG_DARK,
                                   fg=TEXT_SEC, font=FONT_UI)
        self.lbl_status.pack(side="left")

        self.btn_apply = accent_button(bar, "✔  Apply Selected", self._apply_labels, width=16)
        self.btn_apply.pack(side="right")
        self.btn_apply.config(state="disabled")

        ghost_button(bar, "Clear", self._clear_results, width=8).pack(side="right", padx=(0, 8))
        self.btn_export = ghost_button(bar, "Export CSV", self._export_csv, width=10)
        self.btn_export.pack(side="right", padx=(0, 8))
        self.btn_export.config(state="disabled")

        # Debug toggle in bottom bar — always visible
        self.debug_var = tk.BooleanVar(value=False)
        debug_cb = tk.Checkbutton(bar, text="Debug Log", variable=self.debug_var,
                                  bg=BG_DARK, fg=TEXT_SEC, selectcolor=BG_INPUT,
                                  activebackground=BG_DARK, activeforeground=TEXT_PRI,
                                  font=("Segoe UI", 9), cursor="hand2",
                                  command=self._on_debug_toggle)
        debug_cb.pack(side="right", padx=(0, 12))
        Tooltip(debug_cb, "Show the debug log panel")

        tk.Label(bar, text="v1.0.2", bg=BG_DARK, fg="#3d4255",
                 font=("Segoe UI", 8)).pack(side="right", padx=(0, 16))
        tk.Label(bar, text="Not affiliated with Plex Inc. or TMDb.",
                 bg=BG_DARK, fg="#3d4255",
                 font=("Segoe UI", 7, "italic")).pack(side="bottom")

    # ── Env / settings ────────────────────────────────────────────────────────

    def _load_env_to_fields(self):
        env = load_env()
        self.e_plex_url  .delete(0, "end"); self.e_plex_url  .insert(0, env.get("PLEX_URL", ""))
        self.e_plex_token.delete(0, "end"); self.e_plex_token.insert(0, env.get("PLEX_TOKEN", ""))
        self.e_tmdb_key  .delete(0, "end"); self.e_tmdb_key  .insert(0, env.get("TMDB_API_KEY", ""))
        self.e_library.delete(0, "end"); self.e_library.insert(0, env.get("PLEX_LIBRARY", "Movies"))

    def _save_settings(self):
        save_env({
            "PLEX_URL":      self.e_plex_url  .get().strip(),
            "PLEX_TOKEN":    self.e_plex_token.get().strip(),
            "TMDB_API_KEY":  self.e_tmdb_key  .get().strip(),
            "PLEX_LIBRARY":  self.e_library.get().strip(),
        })
        self._append_log(f"[dbg] Settings saved to: {ENV_FILE}\n", "debug")
        self._set_status("Settings saved to .env  ✓", "ok")

    # ── Scan ─────────────────────────────────────────────────────────────────

    def _start_scan(self):
        if self._scan_thread and self._scan_thread.is_alive():
            return

        token   = self.e_plex_token.get().strip()
        tmdb    = self.e_tmdb_key  .get().strip()
        url     = self.e_plex_url  .get().strip()
        library = self.e_library.get().strip()
        limit_s = self.e_limit     .get().strip()

        if not token:
            messagebox.showerror("Missing config", "Plex Token is required.")
            return
        if not tmdb:
            if not messagebox.askyesno("No TMDb key",
                "No TMDb API key — runtime comparison will be disabled.\nContinue anyway?"):
                return

        self._save_settings()
        self._clear_results()
        self.btn_run   .config(state="disabled", text="Scanning…")
        self.btn_cancel.config(state="normal")
        self.btn_apply .config(state="disabled")
        self._set_status("Connecting to Plex…", "")
        self.progress_var.set(0)
        self._cnt_proposed = self._cnt_errors = self._cnt_has_edition = 0
        self._movie_timestamps = []
        self._scan_total   = 0
        self._update_stat_labels()
        self.progress_lbl.config(text="Connecting to Plex server…")
        self._counter_lbl.config(text="")
        self._cancel_flag.clear()
        self._debug_enabled = self.debug_var.get()
        self._progress_frame.pack(fill="x", after=self._get_cfg_frame(),
                                  padx=20, pady=(4, 0))
        self._start_spinner()

        limit = int(limit_s) if limit_s.isdigit() else 0

        incremental = self.incremental_var.get()
        self._scan_thread = threading.Thread(
            target=self._run_scan_thread,
            args=(url, token, tmdb, library or "Movies", limit, incremental,
                  frozenset(getattr(self, "_ignored_guids", set()))),
            daemon=True,
        )
        self._scan_thread.start()

    def _cancel_scan(self):
        if self._scan_thread and self._scan_thread.is_alive():
            self._cancel_flag.set()
            self.btn_cancel.config(state="disabled", text="Cancelling…")
            self._set_status("Cancelling…", "warn")
            self.progress_lbl.config(text="Cancelling — will stop after current movie…")
            self._append_log("Cancel requested — stopping after current movie…\n", "warn")
            # Poll until thread actually finishes (max 30s) then force-complete
            self._wait_for_cancel()

    def _wait_for_cancel(self):
        """Called on main thread. Polls every 200ms until scan thread exits."""
        if self._scan_thread and self._scan_thread.is_alive():
            self.after(200, self._wait_for_cancel)
        else:
            # Thread has exited — if the queue handler hasn't fired _on_scan_cancelled
            # yet (race condition), force a clean UI reset here
            self.btn_run   .config(state="normal", text="▶  Run Scan")
            self.btn_cancel.config(state="disabled", text="■  Cancel")
            self._stop_spinner()
            self._progress_frame.pack_forget()
            # Only update status if it still says "Cancelling" (not overwritten by handler)
            if "ancelling" in self.lbl_status.cget("text"):
                self._set_status("Scan cancelled.", "warn")

    def _on_debug_toggle(self):
        """Show/hide log panel and sync thread-safe bool."""
        self._debug_enabled = self.debug_var.get()
        if self._debug_enabled:
            self._log_panel.pack(side="right", fill="y", padx=(8, 0),
                                 in_=self._main_area)
        else:
            self._log_panel.pack_forget()


    def _ensure_debug_visible(self):
        """Auto-open the debug log panel and write a section header.
        Called by Remove Editions tab actions so activity is always visible.
        """
        if not self.debug_var.get():
            self.debug_var.set(True)
            self._debug_enabled = True
            self._log_panel.pack(side="right", fill="y", padx=(8, 0),
                                 in_=self._main_area)
        self._append_log("\n\u2500\u2500 Remove Editions \u2500\u2500\n", "acc")
    def _dbg(self, msg):
        """Always put debug messages on queue; poll handler filters by _debug_enabled."""
        self._queue.put(("log_debug", f"[dbg] {msg}\n"))

    def _run_scan_thread(self, url, token, tmdb_key, library, limit,
                         incremental=False, ignored_guids=frozenset()):
        """
        Fully self-contained scan thread.
        No imports of plex_cut_detector — all logic is inlined here.
        Every operation is inside the outer try block so nothing is silent.
        Communicates with the main thread only via self._queue.
        """
        # ── All imports inside the function so failures surface as errors ──
        import re
        import time
        import xml.etree.ElementTree as ET

        results      = []
        plex_objects = {}

        def dbg(msg):
            self._queue.put(("log_debug", f"[dbg] {msg}\n"))

        def log(msg):
            self._queue.put(("log", msg if msg.endswith("\n") else msg + "\n"))

        def check_cancel():
            if self._cancel_flag.is_set():
                raise InterruptedError("Cancelled by user.")

        try:
            import requests
            import urllib3
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            CONN_TIMEOUT = 8
            READ_TIMEOUT = 15
            TMDB_BASE    = "https://api.themoviedb.org/3"
            TMDB_DELAY   = 0.25

            # ── Shared session — explicit timeout on every call ───────────
            session = requests.Session()
            session.mount("http://",  HTTPAdapter(max_retries=Retry(total=0)))
            session.mount("https://", HTTPAdapter(max_retries=Retry(total=0)))

            def get(url_str, params=None, headers=None):
                """Timeout-enforced GET. Never hangs."""
                check_cancel()
                return session.get(
                    url_str,
                    params=params,
                    headers=headers,
                    timeout=(CONN_TIMEOUT, READ_TIMEOUT),
                    verify=False,
                )

            base = url.rstrip("/")

            # ════════════════════════════════════════════════════════════
            # STEP 1 — raw TCP reachability: GET /identity (no auth)
            # ════════════════════════════════════════════════════════════
            self._queue.put(("status", "Step 1/3: Reaching server…"))
            dbg(f"GET {base}/identity  timeout=({CONN_TIMEOUT},{READ_TIMEOUT})")
            try:
                r1 = get(f"{base}/identity")
                dbg(f"  → HTTP {r1.status_code}  {len(r1.content)} bytes")
            except requests.exceptions.ConnectTimeout:
                raise ConnectionError(
                    f"TCP connection timed out after {CONN_TIMEOUT}s.\n\n"
                    f"Tested: {url}\n\n"
                    "Causes:\n"
                    "  • Wrong IP or port\n"
                    "  • Port not forwarded on router\n"
                    "  • Firewall blocking the connection\n"
                    "  • Plex server is offline or sleeping"
                )
            except requests.exceptions.ConnectionError as e:
                raise ConnectionError(
                    f"Connection refused or host not found.\n\n"
                    f"Tested: {url}\n"
                    f"Detail: {e}"
                )
            except requests.exceptions.ReadTimeout:
                raise ConnectionError(
                    f"Server connected but sent no data within {READ_TIMEOUT}s.\n"
                    f"Tested: {url}"
                )

            # ════════════════════════════════════════════════════════════
            # STEP 2 — authentication + library list
            # ════════════════════════════════════════════════════════════
            check_cancel()
            self._queue.put(("status", "Step 2/3: Authenticating…"))
            dbg(f"GET {base}/library/sections  (token hidden)")
            try:
                r2 = get(f"{base}/library/sections",
                         params={"X-Plex-Token": token})
                dbg(f"  → HTTP {r2.status_code}  {len(r2.content)} bytes")
            except requests.exceptions.Timeout:
                raise ConnectionError("Auth request timed out.")

            if r2.status_code == 401:
                raise ConnectionError(
                    "Authentication failed (HTTP 401).\n\n"
                    "Your Plex Token is invalid or expired.\n"
                    "Click the ⓘ next to Plex Token for instructions."
                )
            if r2.status_code != 200:
                raise ConnectionError(
                    f"Unexpected HTTP {r2.status_code} from Plex auth check.\n"
                    f"Raw response: {r2.text[:300]}"
                )

            try:
                root      = ET.fromstring(r2.content)
                available = [d.get("title", "?") for d in root.findall("Directory")]
                dbg(f"  → Libraries: {available}")
            except ET.ParseError as e:
                dbg(f"  → XML parse error: {e}  raw={r2.text[:200]}")
                available = []

            if library not in available:
                avail_str = ("\n".join(f"  • {t}" for t in available)
                             if available else "  (none found — token may be wrong)")
                raise ValueError(
                    f"Library '{library}' not found on this server.\n\n"
                    f"Libraries available:\n{avail_str}\n\n"
                    "Fix the Library Name in Connection Settings."
                )

            # Auth confirmed + library found — report connected now
            log(f"Connected to Plex. Library '{library}' found.\n")
            self._queue.put(("status", "Connected — loading movie list…"))

            # ════════════════════════════════════════════════════════════
            # STEP 3 — load movie list via plexapi
            # ════════════════════════════════════════════════════════════
            check_cancel()
            self._queue.put(("status", "Step 3/3: Loading movie list…"))
            dbg("Importing plexapi (local, no network call yet)")

            try:
                from plexapi.server import PlexServer
                import plexapi.exceptions as plexexc
            except ImportError:
                raise RuntimeError(
                    "plexapi is not installed.\n"
                    "Run:  pip install plexapi"
                )

            dbg("Calling PlexServer() — uses our verified session")
            try:
                plex = PlexServer(base, token, session=session,
                                  timeout=READ_TIMEOUT)
            except plexexc.Unauthorized:
                raise ConnectionError("plexapi: Unauthorized. Check your token.")
            except Exception as e:
                raise ConnectionError(f"plexapi failed: {type(e).__name__}: {e}")

            all_movies_with_lib = []
            # ── STEP 3 cont: load section and movies ─────────────────
            try:
                sect = plex.library.section(library)
            except plexexc.NotFound:
                avail = [s.title for s in plex.library.sections()]
                raise ValueError(
                    f"Library '{library}' was not found.\n\n"
                    f"Available libraries:\n"
                    + "\n".join(f"  • {t}" for t in avail)
                    + "\n\nFix the Library Name in Connection Settings."
                )
            movies = sect.all()
            if limit:
                movies = movies[:limit]
            total = len(movies)
            log(f"Loaded {total} movies from '{library}'.\n")
            self._queue.put(("scan_total", total))
            all_movies_with_lib = [(m, library) for m in movies]



            previously_scanned = set()
            if incremental:
                rp = BASE_DIR / "movie_cut_report.json"
                if rp.exists():
                    try:
                        import json as _json
                        prev = _json.loads(rp.read_text(encoding="utf-8"))
                        previously_scanned = {r["guid"] for r in prev if "guid" in r}
                        skipping = sum(1 for m in movies if m.guid in previously_scanned)
                        log(f"Incremental: skipping {skipping} previously scanned movies.\n")
                    except Exception as e:
                        log(f"Warning: could not load previous report ({e})\n")
                else:
                    log("No previous report found — full scan this run.\n")

            # ════════════════════════════════════════════════════════════
            # Inline helpers (replaces plex_cut_detector imports)
            # ════════════════════════════════════════════════════════════
            # Each entry: keyword -> canonical label.
            # _derive_label() may override suffix based on raw TMDb text.
            LABEL_TEMPLATES = {
                "director's cut":      "Director's Cut",
                "director cut":        "Director's Cut",
                "extended cut":        "Extended Cut",
                "extended edition":    "Extended Edition",
                "unrated cut":         "Unrated Cut",
                "unrated edition":     "Unrated Edition",
                "unrated":             "Unrated Cut",
                "theatrical cut":      "Theatrical Cut",
                "theatrical version":  "Theatrical Cut",
                "final cut":           "Final Cut",
                "ultimate cut":        "Ultimate Cut",
                "ultimate edition":    "Ultimate Edition",
                "redux":               "Redux",
                "workprint":           "Workprint",
                "work print":          "Workprint",
                "complete cut":        "Complete Cut",
                "assembly cut":        "Assembly Cut",
                "producer's cut":      "Producer's Cut",
                "producer cut":        "Producer's Cut",
                "television cut":      "Television Cut",
                "tv cut":              "Television Cut",
                "broadcast cut":       "Television Cut",
            }

            def _derive_label(kw, raw_text):
                """
                Preserve 'Edition' or 'Cut' from the raw TMDb text where possible.
                e.g. raw='The Movie: Unrated Edition' -> 'Unrated Edition'
                     raw='Unrated Version'            -> 'Unrated Cut' (canonical)
                """
                canonical = LABEL_TEMPLATES[kw]
                rl = raw_text.lower()
                kw_pos  = rl.find(kw)
                context = rl[kw_pos:kw_pos + len(kw) + 25] if kw_pos >= 0 else ""
                # Only override suffix for ambiguous keywords (no suffix in kw itself)
                if kw not in ("extended cut", "extended edition", "unrated cut",
                              "unrated edition", "theatrical cut", "final cut",
                              "ultimate cut", "ultimate edition", "complete cut",
                              "assembly cut", "producer's cut", "television cut",
                              "tv cut", "broadcast cut", "director's cut",
                              "director cut", "producer cut", "work print"):
                    base = canonical.rsplit(" ", 1)[0]  # e.g. 'Unrated'
                    if "edition" in context:
                        return base + " Edition"
                    elif "cut" in context:
                        return base + " Cut"
                return canonical
            ALL_CUT_LABELS = set(LABEL_TEMPLATES.values()) | {
                "Director\'s Cut", "Extended", "Extended Edition", "Unrated",
                "Theatrical", "Theatrical Cut", "Final Cut",
                "Ultimate Cut", "Redux", "Complete Cut", "Assembly Cut",
                "Ultimate Edition", "Workprint", "Producer\'s Cut",
                "Television Cut",
            }
            MATCH_MIN = 4
            ALT_MIN   = 8
            LARGE_MIN = 15
            THEATRICAL_TOL = 5

            def existing_cut_labels(labels):
                return [l for l in labels if l in ALL_CUT_LABELS]

            def check_label_plausibility(lbl, diff):
                if diff is None: return "unknown"
                l = lbl.lower()
                if "theatrical" in l:
                    return "ok" if abs(diff) <= THEATRICAL_TOL else "suspicious"
                if any(k in l for k in ("extended","ultimate","complete","assembly","redux","director")):
                    return "ok" if diff >= ALT_MIN else "suspicious"
                if any(k in l for k in ("international","unrated")):
                    return "suspicious" if abs(diff) >= LARGE_MIN * 2 else "ok"
                return "ok"

            def guess_label(plex_m, tmdb_m):
                if tmdb_m is None: return None
                d = plex_m - tmdb_m
                if d >= LARGE_MIN:  return "Extended Cut"
                if d <= -LARGE_MIN: return "Theatrical Cut"
                return None

            def get_tmdb_id_from_plex(movie_obj):
                """
                Read the TMDb ID that Plex already matched for this movie.
                Returns an int ID or None if Plex has no TMDb match stored.
                movie.guids is a list of Guid objects with .id like 'tmdb://123456'.
                """
                try:
                    for g in movie_obj.guids:
                        if g.id.startswith("tmdb://"):
                            return int(g.id.split("tmdb://")[1])
                except Exception:
                    pass
                return None

            def tmdb_search_fallback(title, year):
                """
                Text search fallback — only used when Plex has no TMDb ID stored.
                Tries title+year first, then title-only.
                """
                params = {"api_key": tmdb_key, "query": title, "include_adult": False}
                if year: params["year"] = year
                try:
                    r = get(f"{TMDB_BASE}/search/movie", params=params)
                    results_list = r.json().get("results", [])
                except Exception:
                    results_list = []
                if not results_list and year:
                    params.pop("year", None)
                    try:
                        r = get(f"{TMDB_BASE}/search/movie", params=params)
                        results_list = r.json().get("results", [])
                    except Exception:
                        results_list = []
                return results_list[0]["id"] if results_list else None

            def tmdb_details(tmdb_id):
                params = {"api_key": tmdb_key,
                          "append_to_response": "release_dates,alternative_titles"}
                r = get(f"{TMDB_BASE}/movie/{tmdb_id}", params=params)
                return r.json()

            def extract_hints(details):
                hints = []
                seen  = set()
                for country in details.get("release_dates", {}).get("results", []):
                    for rel in country.get("release_dates", []):
                        note = rel.get("note", "").strip()
                        if not note: continue
                        nl = note.lower()
                        for kw in LABEL_TEMPLATES:
                            if kw in nl:
                                label = _derive_label(kw, note)
                                if label not in seen:
                                    seen.add(label)
                                    hints.append({
                                        "label":  label,
                                        "source": "release note (" + country.get("iso_3166_1","?") + ")",
                                        "raw":    note,
                                    })
                for at in details.get("alternative_titles", {}).get("titles", []):
                    t  = at.get("title", "")
                    tl = t.lower()
                    for kw in LABEL_TEMPLATES:
                        if kw in tl:
                            label = _derive_label(kw, t)
                            if label not in seen:
                                seen.add(label)
                                hints.append({
                                    "label":  label,
                                    "source": "alt title (" + at.get("iso_3166_1","?") + ")",
                                    "raw":    t,
                                })
                return hints


            # ════════════════════════════════════════════════════════════
            # Main movie loop
            # ════════════════════════════════════════════════════════════
            for idx, (movie, movie_lib) in enumerate(all_movies_with_lib, 1):
                check_cancel()
                # Skip ignored movies
                if movie.guid in ignored_guids:
                    self._queue.put(("progress", idx / total * 100))
                    continue
                # Skip previously-scanned movies (incremental mode)
                if movie.guid in ignored_guids:
                    self._queue.put(("progress", idx / total * 100))
                    continue
                if movie.guid in ignored_guids:
                    self._queue.put(("progress", idx / total * 100))
                    continue
                if incremental and movie.guid in previously_scanned:
                    self._queue.put(("progress", idx / total * 100))
                    continue

                self._queue.put(("progress",       idx / total * 100))
                self._queue.put(("movie_progress", (idx, total, movie.title, time.time())))

                plex_min      = round((movie.duration or 0) / 60000, 1)
                all_existing  = [lbl.tag for lbl in movie.labels]
                cut_existing  = existing_cut_labels(all_existing)
                edition_title = (getattr(movie, "editionTitle", None) or "").strip()

                rec = {
                    "guid":               movie.guid,
                    "library":            movie_lib,
                    "title":              movie.title,
                    "year":               movie.year,
                    "plex_runtime":       plex_min,
                    "tmdb_id":            None,
                    "tmdb_runtime":       None,
                    "runtime_diff":       None,
                    "runtime_status":     "no_tmdb_match",
                    "edition_hints":      [],
                    "proposed_labels":    [],
                    "existing_labels":    all_existing,
                    "existing_cut_labels": cut_existing,
                    "existing_edition_title": edition_title,
                    "mislabel_warnings":  [],
                    "flags":              [],
                }
                plex_objects[movie.guid] = movie

                if tmdb_key:
                    try:
                        check_cancel()

                        # Step 1: try to get TMDb ID directly from Plex's stored metadata
                        tmdb_id = get_tmdb_id_from_plex(movie)
                        dbg(f"  {movie.title}: Plex GUID TMDb ID = {tmdb_id}")

                        # Step 2: fall back to text search only if Plex has no TMDb ID
                        if not tmdb_id:
                            dbg(f"  {movie.title}: no GUID, falling back to text search")
                            tmdb_id = tmdb_search_fallback(movie.title, movie.year)
                            time.sleep(TMDB_DELAY)

                        if tmdb_id:
                            rec["tmdb_id"] = tmdb_id
                            details      = tmdb_details(tmdb_id)
                            time.sleep(TMDB_DELAY)

                            tmdb_rt = details.get("runtime")
                            rec["tmdb_runtime"] = tmdb_rt

                            if tmdb_rt:
                                diff   = round(abs(plex_min - tmdb_rt), 1)
                                signed = round(plex_min - tmdb_rt, 1)
                                rec["runtime_diff"] = diff
                                if diff <= MATCH_MIN:
                                    rec["runtime_status"] = "match"
                                elif diff <= ALT_MIN:
                                    rec["runtime_status"] = "close"
                                else:
                                    rec["runtime_status"] = "different"
                                    rec["flags"].append("runtime_mismatch")
                                if diff >= LARGE_MIN:
                                    rec["flags"].append("large_gap")
                            else:
                                signed = None
                                rec["runtime_status"] = "no_tmdb_runtime"

                            hints = extract_hints(details)
                            rec["edition_hints"] = hints
                            if hints:
                                rec["flags"].append("alternate_cuts_known")

                            signed_diff = round(plex_min - (tmdb_rt or plex_min), 1)

                            mislabels = []
                            for ec in cut_existing:
                                if check_label_plausibility(ec, signed_diff) == "suspicious":
                                    mislabels.append({
                                        "label":  ec,
                                        "reason": "label '" + ec + "' vs diff " + f"{signed_diff:+.0f}m",
                                    })
                            rec["mislabel_warnings"] = mislabels
                            if mislabels:
                                rec["flags"].append("possible_mislabel")

                            proposed = []
                            # Skip proposing if movie already has an editionTitle set
                            if not cut_existing and not edition_title:
                                for h in hints:
                                    if h["label"] not in all_existing and h["label"] not in proposed:
                                        proposed.append(h["label"])
                                if rec["runtime_status"] == "different" and not hints:
                                    g = guess_label(plex_min, tmdb_rt)
                                    if g and g not in all_existing:
                                        proposed.append(g)
                                        rec["flags"].append("label_inferred")
                            elif edition_title:
                                rec["flags"].append("has_edition_title")
                            rec["proposed_labels"] = proposed

                    except InterruptedError:
                        raise
                    except Exception as e:
                        rec["flags"].append(f"error:{str(e)[:50]}")
                        self._queue.put(("stat_error", 1))

                if rec["proposed_labels"]:
                    self._queue.put(("stat_proposed", len(rec["proposed_labels"])))
                if rec.get("existing_edition_title"):
                    self._queue.put(("stat_has_edition", 1))

                results.append(rec)

            self._queue.put(("done", (results, plex_objects)))

        except InterruptedError:
            self._queue.put(("cancelled", (results, plex_objects)))
        except Exception as e:
            self._queue.put(("error", str(e)))

    def _poll_queue(self):
        try:
            while True:
                try:
                    msg = self._queue.get_nowait()
                except queue.Empty:
                    break
                kind = msg[0]
                try:
                    if kind == "log":
                        self._append_log(msg[1])
                    elif kind == "log_acc":
                        self._append_log(msg[1], "acc")
                    elif kind == "log_debug":
                        if self._debug_enabled:
                            self._append_log(msg[1], "debug")
                    elif kind == "progress":
                        self.progress_var.set(msg[1])
                    elif kind == "scan_total":
                        self._scan_total = msg[1]
                    elif kind == "movie_progress":
                        idx, total, title, ts = msg[1]
                        self.progress_lbl.config(text=f"Checking:  {title}")
                        self._counter_lbl.config(text=f"{idx:,} / {total:,}")
                        # Rolling ETA
                        self._movie_timestamps.append((idx, ts))
                        window = 20 if idx > 100 else 10
                        if len(self._movie_timestamps) > window:
                            self._movie_timestamps = self._movie_timestamps[-window:]
                        if len(self._movie_timestamps) >= 2:
                            oldest_idx, oldest_ts = self._movie_timestamps[0]
                            newest_idx, newest_ts = self._movie_timestamps[-1]
                            elapsed = newest_ts - oldest_ts
                            movies_in_window = newest_idx - oldest_idx
                            if movies_in_window > 0 and elapsed > 0:
                                secs_per_movie = elapsed / movies_in_window
                                remaining = (total - idx) * secs_per_movie
                                self._eta_lbl.config(text="ETA: " + _fmt_eta(remaining))
                            else:
                                self._eta_lbl.config(text="")
                        else:
                            self._eta_lbl.config(text="")
                    elif kind == "stat_proposed":
                        self._cnt_proposed += msg[1]; self._update_stat_labels()
                    elif kind == "stat_error":
                        self._cnt_errors += msg[1]; self._update_stat_labels()
                    elif kind == "stat_has_edition":
                        self._cnt_has_edition += msg[1]; self._update_stat_labels()
                    elif kind == "status":
                        self._set_status(msg[1])
                    elif kind == "done":
                        self._on_scan_done(*msg[1])
                    elif kind == "cancelled":
                        self._on_scan_cancelled(*msg[1])
                    elif kind == "error":
                        self._on_scan_error(msg[1])
                    elif kind == "fetch_libs_err":
                        messagebox.showerror("Fetch failed", msg[1])
                    elif kind == "undo_done":
                        success, errors, dry = msg[1]
                        self._undo_remove_btn.config(state="normal", text="Remove Selected")
                        prefix = "[dry-run] " if dry else ""
                        err_str = f"{errors} error(s)." if errors else ""
                        self._set_status(
                            f"{prefix}Removed {success} edition(s). {err_str}",
                            "ok" if not errors else "warn")
                        if not dry:
                            self._fetch_tagged_movies()
                    elif kind == "undo_remove_done":
                        success, errors, dry, err_str = msg[1]
                        self._undo_remove_btn.config(state="normal", text="Remove Selected")
                        prefix = "[dry-run] " if dry else ""
                        self._set_status(
                            f"{prefix}Removed {success} edition(s). {err_str}",
                            "ok" if not errors else "warn")
                    elif kind == "apply_done":
                        success, errors, dry, by_guid = msg[1]
                        self.btn_apply.config(state="normal", text="\u2714  Apply Selected")
                        tag = "ok" if not errors else "warn"
                        prefix = "[dry-run] " if dry else ""
                        self._append_log(
                            f"\n{prefix}Done: {success} applied, {errors} errors\n", tag)
                        err_str = f"{errors} error(s)." if errors else ""
                        self._set_status(
                            f"{'Simulated' if dry else 'Applied'} {success} label(s).  {err_str}",
                            "ok" if not errors else "warn")
                        if not dry and success > 0 and self._scan_results:
                            for r in self._scan_results:
                                if r["guid"] in by_guid:
                                    r["existing_edition_title"] = by_guid[r["guid"]][0]
                                    r["proposed_labels"] = []
                                    r["flags"].append("applied")
                            self._append_log(
                                f"  Report updated: {len(by_guid)} edition(s) recorded\n", "dim")
                            self._save_report(self._scan_results)
                except Exception as _poll_err:
                    # One crashed handler never kills the poll loop
                    import traceback as _tb
                    print(f"[poll_queue] handler crash ({kind!r}): {_poll_err}")
                    print(_tb.format_exc())
                    try:
                        self._append_log(
                            f"[err] Internal error processing {kind!r}: {_poll_err}\n", "err")
                    except Exception:
                        pass
        except Exception as _outer:
            print(f"[poll_queue] outer error: {_outer}")
        finally:
            self.after(80, self._poll_queue)

    # ── Scan completion ───────────────────────────────────────────────────────

    def _update_stat_labels(self):
        self._stat_found .config(text=f"proposed: {self._cnt_proposed}")
        self._stat_has_ed.config(text=f"has edition: {self._cnt_has_edition}")
        self._stat_errors.config(text=f"errors: {self._cnt_errors}")

    def _start_spinner(self):
        self._spinner_running = True
        self._tick_spinner()

    def _tick_spinner(self):
        if not getattr(self, "_spinner_running", False):
            return
        self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_chars)
        self._spinner_lbl.config(text=self._spinner_chars[self._spinner_idx])
        self.after(120, self._tick_spinner)

    def _stop_spinner(self):
        self._spinner_running = False
        self._spinner_lbl.config(text="")
        if hasattr(self, "_eta_lbl"): self._eta_lbl.config(text="")

    def _on_scan_cancelled(self, results, plex_objects):
        self._stop_spinner()
        self._scan_results = results
        self._plex_objects = plex_objects
        self.progress_var.set(0)
        self.btn_run   .config(state="normal", text="▶  Run Scan")
        self.btn_cancel.config(state="disabled", text="■  Cancel")
        self._progress_frame.pack_forget()
        self._append_log(f"\n-- Scan cancelled after {len(results)} movies --\n", "warn")
        self._set_status(f"Scan cancelled. {len(results)} movies processed.", "warn")
        if results:
            self._build_results_list(results)
            n = sum(len(r["proposed_labels"]) for r in results if r["proposed_labels"])
            if n > 0:
                self.btn_apply.config(state="normal")

    def _on_scan_done(self, results, plex_objects):
        self._stop_spinner()
        self._scan_results = results
        self._plex_objects = plex_objects
        self.progress_var.set(100)
        self.btn_run   .config(state="normal", text="▶  Run Scan")
        self.btn_cancel.config(state="disabled", text="■  Cancel")
        self._progress_frame.pack_forget()

        actionable  = [r for r in results if r["proposed_labels"]]

        self._append_log(f"\n── Scan complete ──\n", "acc")
        self._append_log(f"  {len(results)} movies scanned\n", "dim")
        self._append_log(f"  {len(actionable)} with proposed labels\n",
                         "ok" if actionable else "dim")

        # Save report FIRST — before building UI so a crash there never blocks the write
        self._save_report(results)

        self._build_results_list(results)

        n = sum(len(r["proposed_labels"]) for r in actionable)
        if n > 0:
            self.btn_apply.config(state="disabled")  # checkboxes gate this
            self._set_status(
                f"Found {n} proposed change(s). Select items and click Apply.", "ok")
        else:
            self._set_status("Nothing new to label — library looks good.", "ok")
        if self._scan_results:
            self.btn_export.config(state="normal")

    def _on_scan_error(self, err):
        self._stop_spinner()
        self.btn_run   .config(state="normal", text="▶  Run Scan")
        self.btn_cancel.config(state="disabled", text="■  Cancel")
        self._progress_frame.pack_forget()
        self._append_log(f"\nERROR: {err}\n", "err")
        self._set_status(f"Error: {err[:80]}", "err")
        # Show a clean error dialog — limit width by wrapping long messages
        messagebox.showerror("Scan failed", err)

    # ── Results list ──────────────────────────────────────────────────────────

    def _build_results_list(self, results):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._check_vars.clear()

        show_existing = getattr(self, "show_existing_var", None) and self.show_existing_var.get()
        ignored = getattr(self, "_ignored_guids", set())

        actionable  = [r for r in results
                       if r["proposed_labels"] and r["guid"] not in ignored]
        ignored_here = [r for r in results
                        if r["proposed_labels"] and r["guid"] in ignored]
        # Movies with editionTitle already set — hidden unless checkbox is on
        has_edition = [r for r in results
                       if r.get("existing_edition_title")
                       and not r["proposed_labels"]
                       and not r["mislabel_warnings"]]

        # Split actionable into single-option and multi-option
        single_opt = [r for r in actionable if len(r["proposed_labels"]) == 1]
        multi_opt  = [r for r in actionable if len(r["proposed_labels"]) > 1]

        total_changes = sum(len(r["proposed_labels"]) for r in actionable)
        ignore_note = f", {len(ignored_here)} ignored" if ignored_here else ""
        self.lbl_count.config(
            text=f"({total_changes} change(s) across {len(actionable)} movie(s)"
                 + (f", {len(multi_opt)} need review" if multi_opt else "")
                 + ignore_note + ")")

        row_idx = 0

        def section_header(text, colour=TEXT_PRI, bg=BG_CARD):
            tk.Label(self.list_frame, text=text, bg=bg, fg=colour,
                     font=("Segoe UI Semibold", 10), anchor="w",
                     padx=10, pady=6).pack(fill="x")

        def divider(colour=BORDER):
            tk.Frame(self.list_frame, bg=colour, height=1).pack(fill="x", padx=8)

        # ── Multi-option movies FIRST (need manual review) ──
        BG_MULTI = "#2a2518"   # warm dark tint to distinguish
        if multi_opt:
            section_header(
                f"  ⚠  {len(multi_opt)} movie(s) with multiple possible cuts — review required",
                TEXT_WARN, bg=BG_MULTI)
            tk.Label(self.list_frame,
                     text="  Select ONE label per movie. Approve All skips these.",
                     bg=BG_MULTI, fg=TEXT_SEC, font=("Segoe UI", 9),
                     anchor="w", padx=10).pack(fill="x")
            divider("#5a4a20")
            for rec in multi_opt:
                row_idx += 1
                self._add_proposal_row(rec, BG_MULTI, multi=True)
            divider("#5a4a20")
            tk.Frame(self.list_frame, bg=BG_DARK, height=6).pack(fill="x")

        # ── Single-option movies (safe to Approve All) ──
        if single_opt:
            section_header(
                f"  ✚  {len(single_opt)} movie(s) with a single suggested label",
                ACCENT)
            divider()
            for rec in single_opt:
                bg = BG_ROW_A if row_idx % 2 == 0 else BG_ROW_B
                row_idx += 1
                self._add_proposal_row(rec, bg, multi=False)
            divider()

        # ── Already has editionTitle set (shown only when checkbox is on) ──
        if has_edition and show_existing:
            section_header(
                f"  ⓘ  {len(has_edition)} movie(s) already have an edition set",
                TEXT_SEC)
            tk.Label(self.list_frame,
                     text="  These will be overwritten if you check and apply them.",
                     bg=BG_CARD, fg=TEXT_WARN, font=("Segoe UI", 9),
                     anchor="w", padx=10).pack(fill="x")
            divider()
            for rec in has_edition:
                bg = BG_ROW_A if row_idx % 2 == 0 else BG_ROW_B
                row_idx += 1
                self._add_existing_edition_row(rec, bg)
            divider()
        elif has_edition and not show_existing:
            tk.Label(self.list_frame,
                     text=f"  ⓘ  {len(has_edition)} movie(s) hidden (already have edition set)."
                          "  Check \'Show existing editions\' to review.",
                     bg=BG_CARD, fg=TEXT_SEC, font=("Segoe UI", 9),
                     anchor="w", padx=10, pady=4).pack(fill="x")

        if not actionable:
            tk.Label(self.list_frame,
                     text="\n  No changes found. Your library labels look complete!\n",
                     bg=BG_CARD, fg=TEXT_OK, font=FONT_UI).pack()

    def _add_proposal_row(self, rec, bg, multi=False):
        outer = tk.Frame(self.list_frame, bg=bg)
        outer.pack(fill="x", padx=4, pady=2)

        # Title + runtime info
        info_row = tk.Frame(outer, bg=bg)
        info_row.pack(fill="x", padx=8, pady=(4, 1))

        title_str = f"{rec['title']} ({rec['year']})"
        rt_plex   = _fmt_rt(rec["plex_runtime"])
        rt_tmdb   = _fmt_rt(rec["tmdb_runtime"])
        diff_s    = ""
        if rec["runtime_diff"] is not None:
            sign   = "+" if rec["plex_runtime"] > (rec["tmdb_runtime"] or 0) else "-"
            diff_s = f"  {sign}{int(rec['runtime_diff'])}m diff"

        # Movie title is a clickable Google search link
        import urllib.parse
        search_q   = urllib.parse.quote_plus(
            rec['title'] + ' ' + str(rec['year']) + ' editions runtimes')
        search_url = 'https://www.google.com/search?q=' + search_q
        title_lnk  = tk.Label(info_row, text=title_str, bg=bg, fg=TEXT_PRI,
                              font=("Segoe UI Semibold", 10), anchor="w",
                              cursor="hand2")
        title_lnk.pack(side="left")
        title_lnk.bind("<Enter>", lambda e, w=title_lnk: w.config(
            fg=ACCENT_HVR, font=("Segoe UI Semibold", 10, "underline")))
        title_lnk.bind("<Leave>", lambda e, w=title_lnk: w.config(
            fg=TEXT_PRI, font=("Segoe UI Semibold", 10)))
        title_lnk.bind("<Button-1>", lambda e, u=search_url: _open_url(u))
        Tooltip(title_lnk, "Click here to search Google for this movie's edition runtimes")
        # Ignore button — right-aligned, subtle until hovered
        _ig_btn = tk.Label(info_row, text="✕ Ignore", bg=bg, fg="#5a3535",
                           font=("Segoe UI", 8), cursor="hand2")
        _ig_btn.pack(side="right", padx=(0, 8))
        _ig_btn.bind("<Enter>", lambda e, w=_ig_btn: w.config(fg=TEXT_ERR))
        _ig_btn.bind("<Leave>", lambda e, w=_ig_btn: w.config(fg="#5a3535"))
        _ig_btn.bind("<Button-1>", lambda e, g=rec["guid"], t=rec["title"],
                     yr=rec["year"]: self._ignore_movie(g, t, yr))
        Tooltip(_ig_btn, "Permanently hide this movie from results.\n"
                         "Reversible by editing movie_cut_ignore.json.")
        # Explicitly label TMDb runtime as "theatrical" so users understand the baseline
        tk.Label(info_row,
                 text=f"  Plex: {rt_plex}  TMDb theatrical: {rt_tmdb}{diff_s}",
                 bg=bg, fg=TEXT_SEC, font=FONT_MONO, anchor="w").pack(side="left")

        guid = rec["guid"]
        labels = rec["proposed_labels"]

        # For multi-option rows, vars are mutually exclusive (radio-style)
        # For single-option rows, plain checkbox
        if multi:
            # Radio-style mutual exclusion using BooleanVars only.
            # All vars for this guid are registered first, then callbacks
            # reference the shared dict by guid to uncheck siblings.
            # We pre-register all vars before creating any callbacks so
            # the closure captures the complete set.
            label_vars = {}
            for lbl in labels:
                var = tk.BooleanVar(value=False)
                self._check_vars[(guid, lbl)] = var
                label_vars[lbl] = var

            def make_exclusive_cb(this_lbl, this_guid, lbl_vars):
                def on_click():
                    if lbl_vars[this_lbl].get():
                        # This one was just turned ON — turn all siblings OFF
                        for other_lbl, other_var in lbl_vars.items():
                            if other_lbl != this_lbl:
                                other_var.set(False)
                    self._update_approve_all_state()
                return on_click

            for lbl in labels:
                src = next((h["source"] for h in rec["edition_hints"] if h["label"] == lbl),
                           "runtime inference")
                raw = next((h["raw"]    for h in rec["edition_hints"] if h["label"] == lbl), "")

                cb_row = tk.Frame(outer, bg=bg)
                cb_row.pack(fill="x", padx=24, pady=1)

                cb = tk.Checkbutton(
                    cb_row, text=f"  {lbl}",
                    variable=label_vars[lbl],
                    command=make_exclusive_cb(lbl, guid, label_vars),
                    bg=bg, fg=TEXT_WARN, selectcolor=BG_INPUT,
                    activebackground=bg, activeforeground=TEXT_WARN,
                    font=("Segoe UI Semibold", 10), cursor="hand2", anchor="w",
                )
                cb.pack(side="left")

                src_txt = f"← {src}"
                if raw and raw.lower() != lbl.lower():
                    src_txt += f'  "{raw}"'
                tk.Label(cb_row, text=src_txt, bg=bg, fg=TEXT_SEC,
                         font=FONT_MONO, anchor="w").pack(side="left", padx=4)
        else:
            # Single-option — plain checkbox
            lbl = labels[0]
            src = next((h["source"] for h in rec["edition_hints"] if h["label"] == lbl),
                       "runtime inference")
            raw = next((h["raw"]    for h in rec["edition_hints"] if h["label"] == lbl), "")

            cb_row = tk.Frame(outer, bg=bg)
            cb_row.pack(fill="x", padx=24, pady=1)

            var = tk.BooleanVar(value=False)
            self._check_vars[(guid, lbl)] = var

            cb = tk.Checkbutton(
                cb_row, text=f"  {lbl}",
                variable=var,
                command=self._update_approve_all_state,
                bg=bg, fg=ACCENT, selectcolor=BG_INPUT,
                activebackground=bg, activeforeground=ACCENT,
                font=("Segoe UI Semibold", 10), cursor="hand2", anchor="w",
            )
            cb.pack(side="left")

            src_txt = f"← {src}"
            if raw and raw.lower() != lbl.lower():
                src_txt += f'  "{raw}"'
            tk.Label(cb_row, text=src_txt, bg=bg, fg=TEXT_SEC,
                     font=FONT_MONO, anchor="w").pack(side="left", padx=4)

        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(3, 0))

    def _refresh_results_filter(self):
        """Called when Show existing editions checkbox is toggled — rebuild list."""
        if self._scan_results:
            self._build_results_list(self._scan_results)

    def _add_existing_edition_row(self, rec, bg):
        """Row for a movie that already has editionTitle set in Plex."""
        outer = tk.Frame(self.list_frame, bg=bg)
        outer.pack(fill="x", padx=4, pady=2)

        info_row = tk.Frame(outer, bg=bg)
        info_row.pack(fill="x", padx=8, pady=(4, 1))

        import urllib.parse
        search_q   = urllib.parse.quote_plus(
            rec["title"] + " " + str(rec["year"]) + " editions runtimes")
        search_url = "https://www.google.com/search?q=" + search_q
        title_lnk  = tk.Label(info_row,
                               text=f"{rec['title']} ({rec['year']})",
                               bg=bg, fg=TEXT_PRI,
                               font=("Segoe UI Semibold", 10), anchor="w",
                               cursor="hand2")
        title_lnk.pack(side="left")
        title_lnk.bind("<Enter>", lambda e, w=title_lnk: w.config(
            fg=ACCENT_HVR, font=("Segoe UI Semibold", 10, "underline")))
        title_lnk.bind("<Leave>", lambda e, w=title_lnk: w.config(
            fg=TEXT_PRI, font=("Segoe UI Semibold", 10)))
        title_lnk.bind("<Button-1>", lambda e, u=search_url: _open_url(u))

        rt_plex = _fmt_rt(rec["plex_runtime"])
        rt_tmdb = _fmt_rt(rec["tmdb_runtime"])
        tk.Label(info_row,
                 text=f"  Plex: {rt_plex}  TMDb theatrical: {rt_tmdb}",
                 bg=bg, fg=TEXT_SEC, font=FONT_MONO, anchor="w").pack(side="left")

        # Show current editionTitle
        et_row = tk.Frame(outer, bg=bg)
        et_row.pack(fill="x", padx=24, pady=(1, 3))
        tk.Label(et_row, text="Current edition: ",
                 bg=bg, fg=TEXT_SEC, font=FONT_MONO).pack(side="left")
        tk.Label(et_row, text=rec.get("existing_edition_title", ""),
                 bg=bg, fg=ACCENT, font=("Segoe UI Semibold", 10)).pack(side="left")

        # Checkbox to overwrite (unchecked by default)
        for lbl in (rec.get("proposed_labels") or []):
            cb_row = tk.Frame(outer, bg=bg)
            cb_row.pack(fill="x", padx=24, pady=1)
            var = tk.BooleanVar(value=False)
            self._check_vars[(rec["guid"], lbl)] = var
            tk.Checkbutton(cb_row, text=f"  Overwrite with: {lbl}",
                           variable=var,
                           command=self._update_approve_all_state,
                           bg=bg, fg=TEXT_WARN, selectcolor=BG_INPUT,
                           activebackground=bg, activeforeground=TEXT_WARN,
                           font=("Segoe UI Semibold", 10), cursor="hand2",
                           anchor="w").pack(side="left")

        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(3, 0))

    def _add_mislabel_row(self, rec, bg):
        outer = tk.Frame(self.list_frame, bg=bg)
        outer.pack(fill="x", padx=4, pady=2)

        info_row = tk.Frame(outer, bg=bg)
        info_row.pack(fill="x", padx=8, pady=(4, 1))

        rt_plex = _fmt_rt(rec["plex_runtime"])
        rt_tmdb = _fmt_rt(rec["tmdb_runtime"])
        tk.Label(info_row, text=f"⚠  {rec['title']} ({rec['year']})",
                 bg=bg, fg=TEXT_WARN, font=("Segoe UI Semibold", 10),
                 anchor="w").pack(side="left")
        tk.Label(info_row, text=f"  Plex: {rt_plex}  TMDb theatrical: {rt_tmdb}",
                 bg=bg, fg=TEXT_SEC, font=FONT_MONO, anchor="w").pack(side="left")

        for w in rec["mislabel_warnings"]:
            wr = tk.Frame(outer, bg=bg)
            wr.pack(fill="x", padx=24, pady=1)
            tk.Label(wr, text=f"Label: {w['label']}  —  {w['reason']}",
                     bg=bg, fg=TEXT_WARN, font=FONT_MONO, anchor="w").pack(side="left")

        if rec["tmdb_id"]:
            link = tk.Label(outer,
                            text=f"  https://www.themoviedb.org/movie/{rec['tmdb_id']}",
                            bg=bg, fg=TEXT_SEC, font=FONT_MONO, cursor="hand2")
            link.pack(anchor="w", padx=24)
            link.bind("<Button-1>", lambda e, tid=rec["tmdb_id"]:
                      _open_url(f"https://www.themoviedb.org/movie/{tid}"))

        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(3, 0))

    # ── Checkbox helpers ──────────────────────────────────────────────────────

    def _enforce_single_selection_all(self):
        """
        When Approve All is turned on, only auto-check single-option movies.
        Multi-option movies are left unchecked — user must review them manually.
        """
        # Build per-guid label counts
        guid_labels = {}
        for (guid, lbl) in self._check_vars:
            guid_labels.setdefault(guid, []).append(lbl)

        for (guid, lbl), var in self._check_vars.items():
            if len(guid_labels[guid]) == 1:
                var.set(True)   # single-option: auto-approve
            else:
                var.set(False)  # multi-option: leave for user

    def _toggle_all(self):
        state = self.approve_all_var.get()
        if state:
            # Don't blanket-check everything — only safe single-option items
            self._enforce_single_selection_all()
        else:
            for var in self._check_vars.values():
                var.set(False)
        # Gate Apply button
        any_on = any(v.get() for v in self._check_vars.values())
        if hasattr(self, "btn_apply"):
            self.btn_apply.config(state="normal" if any_on else "disabled")

    def _update_approve_all_state(self):
        vals = [v.get() for v in self._check_vars.values()]
        all_on  = vals and all(vals)
        any_on  = any(vals)
        self.approve_all_var.set(all_on)
        # Gate the Apply button on whether anything is checked
        if hasattr(self, "btn_apply"):
            self.btn_apply.config(state="normal" if any_on else "disabled")

    # ── Apply labels ──────────────────────────────────────────────────────────

    def _apply_labels(self):
        approved = {k for k, v in self._check_vars.items() if v.get()}
        if not approved:
            messagebox.showinfo("Nothing selected", "No labels are checked.")
            return

        dry = self.dry_run_var.get()
        verb = "simulate applying" if dry else "apply"
        if not messagebox.askyesno("Confirm",
            f"About to {verb} {len(approved)} label change(s) to Plex.\n\nContinue?"):
            return

        self.btn_apply.config(state="disabled", text="Applying…")
        self._set_status("Writing labels to Plex…", "")

        def worker():
            by_guid = {}
            for (guid, label) in approved:
                by_guid.setdefault(guid, []).append(label)

            success = errors = 0
            try:
                self._queue.put(("log_debug",
                    f"[dbg] Applying {len(by_guid)} edition(s) to Plex\n"))
                if not self._plex_objects:
                    raise RuntimeError(
                        "No Plex movie objects in memory. "
                        "Run a scan before applying.")

                for guid, labels in by_guid.items():
                    movie = self._plex_objects.get(guid)
                    if not movie:
                        self._queue.put(("log",
                            f"\u26a0 Movie not found in memory (GUID: {guid[:30]})\n"))
                        self._queue.put(("log_debug",
                            f"[dbg] GUID not in plex_objects: {guid}\n"))
                        errors += len(labels)
                        continue

                    edition = labels[0]
                    self._queue.put(("log_debug",
                        f"[dbg] Setting editionTitle on: {movie.title}\n"))

                    if dry:
                        self._queue.put(("log",
                            f"[dry-run] {movie.title} would set editionTitle={edition!r}\n"))
                        success += len(labels)
                        continue
                    try:
                        movie.editField("editionTitle", edition, locked=True)
                        movie.reload()
                        new_val = getattr(movie, "editionTitle", None)
                        if new_val == edition:
                            self._queue.put(("log",
                                f"\u2713 {movie.title} editionTitle={edition!r}\n"))
                            self._queue.put(("log_debug",
                                f"[dbg]   Confirmed editionTitle={new_val!r}\n"))
                        else:
                            self._queue.put(("log_debug",
                                f"[dbg]   editField may not be supported; trying addLabel\n"))
                            movie.addLabel(edition)
                            movie.reload()
                            self._queue.put(("log",
                                f"\u2713 {movie.title} label={edition!r} "
                                f"(editionTitle unsupported on this server)\n"))
                        success += len(labels)
                    except Exception as e:
                        self._queue.put(("log", f"\u2717 {movie.title}: {e}\n"))
                        self._queue.put(("log_debug",
                            f"[dbg]   Exception: {type(e).__name__}: {e}\n"))
                        errors += len(labels)

            except Exception as outer_e:
                self._queue.put(("log", f"\u2717 Apply failed: {outer_e}\n"))
                self._queue.put(("log_debug",
                    f"[dbg] Outer exception: {type(outer_e).__name__}: {outer_e}\n"))
                errors += len(by_guid)

            # Always send — ensures button never stays stuck on Applying
            self._queue.put(("apply_done", (success, errors, dry, by_guid)))

        threading.Thread(target=worker, daemon=True).start()

    # ── Canvas / scroll ───────────────────────────────────────────────────────

    # ── Undo / Remove Editions tab ───────────────────────────────────────────

    def _build_undo_tab(self, parent):
        """Build the Remove Editions tab UI."""
        hdr = tk.Frame(parent, bg=BG_DARK)
        hdr.pack(fill="x", pady=(6, 0))
        tk.Label(hdr, text="Movies with Edition Tags Set",
                 bg=BG_DARK, fg=TEXT_PRI, font=FONT_TITLE).pack(side="left")
        self._undo_count_lbl = tk.Label(hdr, text="", bg=BG_DARK,
                                        fg=TEXT_SEC, font=FONT_UI)
        self._undo_count_lbl.pack(side="left", padx=8)

        self._undo_select_all_var = tk.BooleanVar(value=False)
        tk.Checkbutton(hdr, text="Select All",
                       variable=self._undo_select_all_var,
                       command=self._undo_toggle_all,
                       bg=BG_DARK, fg=ACCENT, selectcolor=BG_INPUT,
                       activebackground=BG_DARK, activeforeground=ACCENT,
                       font=("Segoe UI Semibold", 10),
                       cursor="hand2").pack(side="right")

        btn_row = tk.Frame(parent, bg=BG_DARK)
        btn_row.pack(fill="x", pady=(4, 0))
        accent_button(btn_row, "Fetch Tagged Movies",
                      self._fetch_tagged_movies, width=18).pack(side="left")
        Tooltip(btn_row.winfo_children()[0],
                "Load movies with edition tags from the last scan report.\n"
                "No network call — reads movie_cut_report.json.\n"
                "Run a full scan first to populate the report.")
        self._undo_remove_btn = ghost_button(btn_row, "Remove Selected",
                                             self._remove_selected_editions, width=16)
        self._undo_remove_btn.pack(side="left", padx=8)
        self._undo_remove_btn.config(state="disabled")

        canvas_frame = tk.Frame(parent, bg=BG_CARD, highlightthickness=1,
                                highlightbackground=BORDER)
        canvas_frame.pack(fill="both", expand=True, pady=(6, 0))
        self._undo_canvas = tk.Canvas(canvas_frame, bg=BG_CARD, highlightthickness=0)
        vscroll = ttk.Scrollbar(canvas_frame, orient="vertical",
                                command=self._undo_canvas.yview)
        self._undo_canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        self._undo_canvas.pack(side="left", fill="both", expand=True)
        self._undo_frame = tk.Frame(self._undo_canvas, bg=BG_CARD)
        self._undo_win = self._undo_canvas.create_window(
            (0,0), window=self._undo_frame, anchor="nw")
        self._undo_frame.bind("<Configure>",
            lambda e: self._undo_canvas.configure(
                scrollregion=self._undo_canvas.bbox("all")))
        self._undo_canvas.bind("<Configure>",
            lambda e: self._undo_canvas.itemconfig(self._undo_win, width=e.width))
        self._undo_check_vars = {}  # guid -> BooleanVar
        self._undo_plex_objects = {}  # guid -> movie

    def _fetch_tagged_movies(self):
        """
        Load movies with edition tags from the saved scan report (no network call).
        Falls back to a helpful message if no report exists yet.
        """
        report_path = BASE_DIR / "movie_cut_report.json"
        if not report_path.exists():
            messagebox.showinfo(
                "No scan report found",
                "No movie_cut_report.json found next to this app.\n\n"
                "Run a full scan on the Scan Results tab first.\n"
                "The report is saved automatically after each scan.")
            return

        try:
            with open(report_path, encoding="utf-8") as f:
                import json as _json
                records = _json.load(f)
        except Exception as e:
            messagebox.showerror("Could not read report", str(e))
            return

        # Filter to records that have an editionTitle set
        tagged = [
            (r["guid"], r["title"], r.get("year",""), r.get("existing_edition_title",""),
             r.get("library",""))
            for r in records
            if r.get("existing_edition_title","").strip()
        ]

        self._undo_check_vars.clear()
        self._undo_plex_objects.clear()
        for w in self._undo_frame.winfo_children():
            w.destroy()

        if not tagged:
            tk.Label(self._undo_frame,
                     text="\n  No movies with edition tags found in the last scan report.\n",
                     bg=BG_CARD, fg=TEXT_SEC, font=FONT_UI).pack()
            self._undo_count_lbl.config(text="")
            self._set_status("No tagged movies in report.", "")
            return

        self._undo_count_lbl.config(text=f"({len(tagged)} movie(s))")
        self._set_status(f"Loaded {len(tagged)} tagged movie(s) from report.", "ok")

        for i, (guid, title, year, edition, lib) in enumerate(tagged):
            bg = BG_ROW_A if i % 2 == 0 else BG_ROW_B
            row = tk.Frame(self._undo_frame, bg=bg)
            row.pack(fill="x", padx=4, pady=1)

            var = tk.BooleanVar(value=False)
            self._undo_check_vars[guid] = var

            cb = tk.Checkbutton(row, variable=var,
                                command=self._undo_update_remove_btn,
                                bg=bg, fg=TEXT_PRI, selectcolor=BG_INPUT,
                                activebackground=bg, cursor="hand2")
            cb.pack(side="left", padx=(6, 0))

            tk.Label(row, text=f"{title} ({year})",
                     bg=bg, fg=TEXT_PRI, font=("Segoe UI Semibold", 10),
                     anchor="w").pack(side="left", padx=(4, 0))
            tk.Label(row, text=f"  {edition}",
                     bg=bg, fg=ACCENT, font=FONT_UI,
                     anchor="w").pack(side="left")
            if lib:
                tk.Label(row, text=f"  [{lib}]",
                         bg=bg, fg=TEXT_SEC, font=FONT_MONO).pack(side="left")

        self._undo_canvas.configure(
            scrollregion=self._undo_canvas.bbox("all"))

    def _undo_update_remove_btn(self):
        any_on = any(v.get() for v in self._undo_check_vars.values())
        self._undo_remove_btn.config(state="normal" if any_on else "disabled")

    def _undo_toggle_all(self):
        state = self._undo_select_all_var.get()
        for var in self._undo_check_vars.values():
            var.set(state)
        self._undo_update_remove_btn()

    def _update_undo_remove_btn(self):
        any_on = any(v.get() for v in self._undo_check_vars.values())
        self._undo_remove_btn.config(state="normal" if any_on else "disabled")

    def _populate_undo_list(self, tagged):
        """tagged: list of (plexapi movie, library_name, edition_title)"""
        for w in self._undo_frame.winfo_children():
            w.destroy()
        self._undo_check_vars.clear()
        self._undo_plex_objects.clear()

        if not tagged:
            tk.Label(self._undo_frame,
                     text="\n  No movies with edition tags found in this library.\n",
                     bg=BG_CARD, fg=TEXT_OK, font=FONT_UI).pack()
            self._undo_count_lbl.config(text="")
            return

        self._undo_count_lbl.config(text=f"({len(tagged)} movie(s))")
        for i, (movie, lib_name, edition) in enumerate(tagged):
            bg = BG_ROW_A if i % 2 == 0 else BG_ROW_B
            row = tk.Frame(self._undo_frame, bg=bg)
            row.pack(fill="x", padx=4, pady=1)
            var = tk.BooleanVar(value=False)
            self._undo_check_vars[movie.guid] = var
            self._undo_plex_objects[movie.guid] = movie
            cb = tk.Checkbutton(row, variable=var,
                                command=self._update_undo_remove_btn,
                                bg=bg, fg=TEXT_PRI, selectcolor=BG_INPUT,
                                activebackground=bg, cursor="hand2")
            cb.pack(side="left", padx=(6,0))
            tk.Label(row, text=f"  {movie.title} ({movie.year})",
                     bg=bg, fg=TEXT_PRI, font=("Segoe UI Semibold",10),
                     anchor="w").pack(side="left")
            tk.Label(row, text=f"  [{edition}]",
                     bg=bg, fg=ACCENT, font=FONT_MONO,
                     anchor="w").pack(side="left")
            tk.Label(row, text=f"  {lib_name}",
                     bg=bg, fg=TEXT_SEC, font=FONT_MONO,
                     anchor="w").pack(side="left")

    def _remove_selected_editions(self):
        selected_guids = [g for g, v in self._undo_check_vars.items() if v.get()]
        if not selected_guids:
            return
        dry = self.dry_run_var.get()
        verb = "simulate removing" if dry else "remove"
        if not messagebox.askyesno("Confirm",
            f"About to {verb} edition tags from "
            f"{len(selected_guids)} movie(s).\n\nContinue?"):
            return
        self._undo_remove_btn.config(state="disabled", text="Removing...")
        url   = self.e_plex_url  .get().strip()
        token = self.e_plex_token.get().strip()
        def worker():
            success = errors = 0
            try:
                import requests, urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                from plexapi.server import PlexServer
                session = requests.Session()
                session.verify = False
                plex = PlexServer(url.rstrip("/"), token,
                                  session=session, timeout=20)
                library = self.e_library.get().strip() or "Movies"
                sect = plex.library.section(library)
                # Build guid->movie map for selected guids only
                guid_map = {}
                for m in sect.all():
                    if m.guid in selected_guids:
                        guid_map[m.guid] = m
                for guid in selected_guids:
                    movie = guid_map.get(guid)
                    if not movie:
                        self._queue.put(("log", f"\u26a0 Could not find movie (GUID: {guid[:30]})\n"))
                        errors += 1
                        continue
                    if dry:
                        self._queue.put(("log", f"[dry-run] Would clear editionTitle for: {movie.title}\n"))
                        success += 1
                        continue
                    try:
                        movie.editField("editionTitle", "", locked=False)
                        self._queue.put(("log", f"\u2713 Cleared edition tag: {movie.title}\n"))
                        success += 1
                    except Exception as e:
                        self._queue.put(("log", f"\u2717 {movie.title}: {e}\n"))
                        errors += 1
            except Exception as e:
                self._queue.put(("log", f"Error connecting to Plex: {e}\n"))
                errors += len(selected_guids)
            err_str = f"{errors} error(s)." if errors else ""
            self._queue.put(("undo_remove_done", (success, errors, dry, err_str)))
        threading.Thread(target=worker, daemon=True).start()

    def _on_frame_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self._scan_results:
            messagebox.showinfo("Nothing to export",
                "Run a scan first, then export the results.")
            return
        import csv
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile="movie_cut_results.csv",
            title="Export results as CSV")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Title", "Year", "Library",
                    "Plex Runtime (min)", "TMDb Theatrical (min)",
                    "Diff (min)", "Suggested Label",
                    "Source", "Existing Edition", "Status"
                ])
                for r in self._scan_results:
                    labels = ", ".join(r.get("proposed_labels", []))
                    sources = ", ".join(
                        h["source"] for h in r.get("edition_hints", []))
                    diff = r.get("runtime_diff")
                    if r.get("plex_runtime") and r.get("tmdb_runtime"):
                        signed_diff = round(
                            r["plex_runtime"] - r["tmdb_runtime"], 1)
                        diff_str = f"{signed_diff:+.1f}"
                    else:
                        diff_str = ""
                    writer.writerow([
                        r.get("title", ""),
                        r.get("year", ""),
                        r.get("library", ""),
                        r.get("plex_runtime", ""),
                        r.get("tmdb_runtime", ""),
                        diff_str,
                        labels,
                        sources,
                        r.get("existing_edition_title", ""),
                        r.get("runtime_status", ""),
                    ])
            self._set_status(f"Exported to {path}", "ok")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def _append_log(self, text, tag=None):
        self.log_box.config(state="normal")
        if tag:
            self.log_box.insert("end", text, tag)
        else:
            self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def _set_status(self, text, level=""):
        colour = {"ok": TEXT_OK, "warn": TEXT_WARN, "err": TEXT_ERR}.get(level, TEXT_SEC)
        self.lbl_status.config(text=text, fg=colour)
        self.progress_lbl.config(text=text if level == "" else "")

    def _get_cfg_frame(self):
        """Return the config card frame so we can pack progress bar after it."""
        # The cfg frame is the second child of self (after the header frame)
        children = self.winfo_children()
        # Find by background colour match — cfg has BG_CARD bg
        for w in children:
            try:
                if w.cget("bg") == BG_CARD:
                    return w
            except Exception:
                pass
        return children[1] if len(children) > 1 else children[0]

    def _clear_results(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._check_vars.clear()
        self._scan_results = []
        self._plex_objects = {}
        self.lbl_count.config(text="")
        self.btn_apply .config(state="disabled")
        self.btn_cancel.config(state="disabled", text="■  Cancel")
        self._movie_timestamps = []
        if hasattr(self, "_eta_lbl"): self._eta_lbl.config(text="")
        self.progress_var.set(0)
        self._cnt_proposed = self._cnt_errors = self._cnt_has_edition = 0
        self._update_stat_labels()
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")
        self._set_status("Ready.", "")


# ── Utility ───────────────────────────────────────────────────────────────────

def _fmt_rt(minutes):
    if minutes is None:
        return "?"
    h, m = divmod(int(minutes), 60)
    return f"{h}h{m:02d}m"


def _fmt_eta(seconds):
    """Format a number of seconds as a human-readable ETA string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s:02d}s"
    else:
        h, remainder = divmod(seconds, 3600)
        m = remainder // 60
        return f"{h}h {m:02d}m"


def _open_url(url):
    import webbrowser
    webbrowser.open(url)


# ── Queue apply_done handler (hooked after class to keep things clean) ────────



# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # When frozen by PyInstaller, add the _MEIPASS temp dir to sys.path
    # so movie_cut_detector.py (bundled as data) can be imported
    if getattr(sys, "frozen", False):
        sys.path.insert(0, sys._MEIPASS)

    app = PlexCutApp()
    app.mainloop()
