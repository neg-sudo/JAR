"""JAR Desktop GUI (optional). Gracefully degrades when GUI deps are missing."""

from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from .. import APP_NAME, APP_TAGLINE, __version__
from ..config import CONFLICT_STRATEGIES, MODES, Config
from ..duplicates import choose_keeper
from ..journal import Journal
from ..organizer import Organizer
from ..reports import report_text
from ..trash import list_quarantine, purge_quarantine, restore_quarantine_item
from ..utils import format_ts, human_size

try:
    import customtkinter as ctk
    CTK = True
except ImportError:
    ctk = None
    CTK = False

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    Image = None
    ImageTk = None
    PIL_OK = False


def launch(config: Config | None = None) -> None:
    app = JarApp(config)
    app.mainloop()


class JarApp:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.organizer = Organizer(self.config)
        self.journal = Journal(self.config.paths.db_file)
        self.stop_event = threading.Event()
        self.watching = False

        if CTK:
            ctk.set_appearance_mode(self.config.data.get("theme") or "dark")
            ctk.set_default_color_theme("blue")
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
            self.root.configure(bg="#1a1a1a")
        self.root.title(f"{APP_NAME} {__version__} | {APP_TAGLINE}")
        self.root.geometry("980x720")
        self.root.minsize(820, 640)
        self._build_menu()
        self._build_tabs()
        self._refresh_all()
        self.root.bind("<F5>", lambda _event: self._refresh_all())
        self.root.bind("<Control-o>", lambda _event: self.run_organize(bool(self.org_dry.get())))
        self.root.bind("<Control-d>", lambda _event: self.find_duplicates())
        self.root.bind("<Control-z>", lambda _event: self.undo_last())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----------------------------------------------------------------- UI
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Config...", command=self.new_config)
        file_menu.add_command(label="Open Config...", command=self.open_config)
        file_menu.add_command(label="Save Config", command=self.save_config)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        action_menu = tk.Menu(menubar, tearoff=0)
        action_menu.add_command(label="Organize Now (Dry Run)", command=lambda: self.run_organize(True))
        action_menu.add_command(label="Organize Now", command=lambda: self.run_organize(False))
        action_menu.add_command(label="Scan Preview", command=self.scan_preview)
        action_menu.add_command(label="Find Duplicates", command=self.find_duplicates)
        menubar.add_cascade(label="Actions", menu=action_menu)
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Undo Last Batch", command=self.undo_last)
        tools_menu.add_command(label="Quarantine Manager", command=self.tab_quarantine)
        tools_menu.add_command(label="Run Doctor", command=self.run_doctor)
        tools_menu.add_command(label="Refresh", command=self._refresh_all)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        help_menu.add_command(label="Keyboard Shortcuts", command=self.show_shortcuts)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

    def _build_tabs(self):
        if CTK:
            self.notebook = ctk.CTkTabview(self.root)
        else:
            self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)
        if CTK:
            self.tab_overview = self.notebook.add("Overview")
            self.tab_organize = self.notebook.add("Organize")
            self.tab_watch = self.notebook.add("Watch")
            self.tab_rules = self.notebook.add("Rules")
            self.tab_duplicates = self.notebook.add("Duplicates")
            self.tab_quarantine = self.notebook.add("Quarantine")
            self.tab_history = self.notebook.add("History")
            self.tab_stats = self.notebook.add("Stats & Reports")
            self.tab_settings = self.notebook.add("Settings")
            self.tab_doctor = self.notebook.add("Doctor")
        else:
            self.tab_overview = ttk.Frame(self.notebook)
            self.tab_organize = ttk.Frame(self.notebook)
            self.tab_watch = ttk.Frame(self.notebook)
            self.tab_rules = ttk.Frame(self.notebook)
            self.tab_duplicates = ttk.Frame(self.notebook)
            self.tab_quarantine = ttk.Frame(self.notebook)
            self.tab_history = ttk.Frame(self.notebook)
            self.tab_stats = ttk.Frame(self.notebook)
            self.tab_settings = ttk.Frame(self.notebook)
            self.tab_doctor = ttk.Frame(self.notebook)
            for name, tab in [("Overview", self.tab_overview), ("Organize", self.tab_organize), ("Watch", self.tab_watch),
                              ("Rules", self.tab_rules), ("Duplicates", self.tab_duplicates),
                              ("Quarantine", self.tab_quarantine), ("History", self.tab_history),
                              ("Stats & Reports", self.tab_stats), ("Settings", self.tab_settings),
                              ("Doctor", self.tab_doctor)]:
                self.notebook.add(tab, text=name)
        self._build_overview()
        self._build_organize()
        self._build_watch()
        self._build_rules()
        self._build_duplicates()
        self._build_quarantine_tab()
        self._build_history()
        self._build_stats()
        self._build_settings()
        self._build_doctor()

    # Overview
    def _build_overview(self):
        f = self._frame(self.tab_overview)
        self._label(f, f"{APP_NAME} {__version__}", size=24).pack(anchor="w")
        self._label(f, APP_TAGLINE, size=12).pack(anchor="w")
        stats_f = self._frame(f)
        self.over_moved = self._label(stats_f, "Moved: -", size=14)
        self.over_bytes = self._label(stats_f, "Routed: -", size=14)
        self.over_batches = self._label(stats_f, "Batches: -", size=14)
        self.over_moved.pack(side="left", padx=10)
        self.over_bytes.pack(side="left", padx=10)
        self.over_batches.pack(side="left", padx=10)
        stats_f.pack(pady=10)
        btn_f = self._frame(f)
        self._button(btn_f, "Scan & Preview", self.scan_preview).pack(side="left", padx=5)
        self._button(btn_f, "Organize (Dry Run)", lambda: self.run_organize(True)).pack(side="left", padx=5)
        self._button(btn_f, "Organize Now", lambda: self.run_organize(False)).pack(side="left", padx=5)
        self._button(btn_f, "Find Duplicates", self.find_duplicates).pack(side="left", padx=5)
        self._button(btn_f, "Undo Last", self.undo_last).pack(side="left", padx=5)
        btn_f.pack(pady=10)
        self.over_log = self._textbox(f, height=18)
        self.over_log.pack(expand=True, fill="both", padx=10, pady=10)

    # Organize
    def _build_organize(self):
        f = self._frame(self.tab_organize)
        self._label(f, "Folders to organize:").pack(anchor="w")
        self.org_paths = self._textbox(f, height=4)
        self.org_paths.pack(fill="x", padx=5)
        btn_f = self._frame(f)
        self._button(btn_f, "Add Folder", self.add_org_path).pack(side="left")
        self._button(btn_f, "Use Config Folders", self.use_config_paths).pack(side="left", padx=5)
        self._button(btn_f, "Clear", lambda: self.org_paths.delete("1.0", "end")).pack(side="left")
        btn_f.pack(anchor="w", pady=5)
        opts = self._frame(f)
        self.org_recursive = self._var("bool", True)
        self.org_dry = self._var("bool", True)
        self._check(opts, "Recursive", self.org_recursive).pack(side="left")
        self._check(opts, "Dry Run", self.org_dry).pack(side="left", padx=10)
        self._label(opts, "Conflict:").pack(side="left", padx=(20, 5))
        self.org_conflict = self._combo(opts, CONFLICT_STRATEGIES, self.config.data.get("conflict", "rename"))
        self.org_conflict.pack(side="left")
        self._label(opts, "Mode:").pack(side="left", padx=(20, 5))
        self.org_mode = self._combo(opts, MODES, self.config.data.get("mode", "global"))
        self.org_mode.pack(side="left")
        opts.pack(anchor="w")
        btn_f2 = self._frame(f)
        self._button(btn_f2, "Preview Plan", self.scan_preview).pack(side="left")
        self._button(btn_f2, "Run", lambda: self.run_organize(bool(self.org_dry.get()))).pack(side="left", padx=5)
        self._button(btn_f2, "Open Destination", self.open_dest).pack(side="left")
        btn_f2.pack(pady=10)
        self.org_plan = self._textbox(f, height=22)
        self.org_plan.pack(expand=True, fill="both")

    # Watch
    def _build_watch(self):
        f = self._frame(self.tab_watch)
        self._label(f, "Watch Folders:").pack(anchor="w")
        self.watch_paths = self._textbox(f, height=4)
        self.watch_paths.pack(fill="x")
        btn_f = self._frame(f)
        self._button(btn_f, "Add Folder", self.add_watch_path).pack(side="left")
        self._button(btn_f, "Use Config", self.use_watch_config).pack(side="left", padx=5)
        btn_f.pack(anchor="w", pady=5)
        opts = self._frame(f)
        self.watch_existing = self._var("bool", False)
        self._check(opts, "Organize existing on start", self.watch_existing).pack(side="left")
        self._label(opts, "Interval:").pack(side="left", padx=(20, 5))
        self.watch_interval = self._entry(opts, "2")
        self.watch_interval.pack(side="left")
        self._label(opts, "Stability:").pack(side="left", padx=(10, 5))
        self.watch_stability = self._entry(opts, "2")
        self.watch_stability.pack(side="left")
        opts.pack(anchor="w")
        btn_f2 = self._frame(f)
        self.watch_btn = self._button(btn_f2, "Start Watching", self.toggle_watch)
        self.watch_btn.pack(side="left")
        self._button(btn_f2, "Stop", self.stop_watch).pack(side="left", padx=5)
        btn_f2.pack(pady=10)
        self.watch_log = self._textbox(f, height=24)
        self.watch_log.pack(expand=True, fill="both")

    # Rules
    def _build_rules(self):
        f = self._frame(self.tab_rules)
        top = self._frame(f)
        self._label(top, "Custom Rules").pack(side="left")
        self._button(top, "Add Rule", self.add_rule).pack(side="right")
        self._button(top, "Reload", self.load_rules).pack(side="right", padx=5)
        top.pack(fill="x")
        self.rules_list = tk.Listbox(f, height=10)
        self.rules_list.pack(fill="x", pady=5)
        form = self._frame(f)
        self.rule_name = self._entry_l(form, "Name")
        self.rule_cat = self._entry_l(form, "Category")
        self.rule_ext = self._entry_l(form, "Extensions (comma)")
        self.rule_glob = self._entry_l(form, "Globs (comma)")
        self.rule_regex = self._entry_l(form, "Regex")
        self.rule_dest = self._entry_l(form, "Destination template")
        self.rule_prio = self._entry_l(form, "Priority")
        self.rule_name[1].pack(); self.rule_cat[1].pack(); self.rule_ext[1].pack()
        self.rule_glob[1].pack(); self.rule_regex[1].pack(); self.rule_dest[1].pack(); self.rule_prio[1].pack()
        form.pack(fill="x")
        btn_f = self._frame(f)
        self._button(btn_f, "Save Rule", self.save_rule).pack(side="left")
        self._button(btn_f, "Remove Selected", self.remove_rule).pack(side="left", padx=5)
        self._button(btn_f, "Enable/Disable", self.toggle_rule).pack(side="left")
        btn_f.pack(pady=5)
        self.builtin_rules = self._textbox(f, height=14)
        self.builtin_rules.pack(expand=True, fill="both")
        self.load_rules()

    # Duplicates
    def _build_duplicates(self):
        f = self._frame(self.tab_duplicates)
        top = self._frame(f)
        self._button(top, "Scan", self.find_duplicates).pack(side="left")
        self._label(top, "Keep:").pack(side="left", padx=(20, 5))
        self.dup_keep = self._combo(top, ["first", "oldest", "newest", "shortest"], "first")
        self.dup_keep.pack(side="left")
        self.dup_permanent = self._var("bool", False)
        self._check(top, "Delete permanently (dangerous)", self.dup_permanent).pack(side="left", padx=15)
        top.pack(anchor="w")
        self.dup_list = tk.Listbox(f, height=12)
        self.dup_list.pack(fill="x", pady=5)
        self.dup_detail = self._textbox(f, height=10)
        self.dup_detail.pack(fill="x")
        btn_f = self._frame(f)
        self._button(btn_f, "Remove Duplicates", self.remove_dupes).pack(side="left")
        self._button(btn_f, "Clear Results", lambda: [self.dup_list.delete(0, "end"), self.dup_detail.delete("1.0", "end")]).pack(side="left", padx=5)
        btn_f.pack(pady=5)
        self.dup_groups = []

    # Quarantine
    def _build_quarantine_tab(self):
        f = self._frame(self.tab_quarantine)
        top = self._frame(f)
        self._button(top, "Refresh", self.load_quarantine).pack(side="left")
        self._button(top, "Restore Selected", self.restore_quarantine).pack(side="left", padx=5)
        self._button(top, "Purge Older Than 30d", lambda: self.purge_quarantine_days(30)).pack(side="left")
        self._button(top, "Purge Older Than 7d", lambda: self.purge_quarantine_days(7)).pack(side="left", padx=5)
        top.pack(anchor="w")
        self.q_list = tk.Listbox(f, height=18)
        self.q_list.pack(expand=True, fill="both", pady=5)
        self.q_items = []
        self.load_quarantine()

    # History
    def _build_history(self):
        f = self._frame(self.tab_history)
        top = self._frame(f)
        self._button(top, "Refresh", self.load_history).pack(side="left")
        self._button(top, "Undo Last Batch", self.undo_last).pack(side="left", padx=5)
        self._button(top, "Clear History", self.clear_history).pack(side="left")
        top.pack(anchor="w")
        cols = ("when", "action", "status", "category", "source", "dest")
        self.hist_tree = ttk.Treeview(f, columns=cols, show="headings", height=24)
        for c, w in zip(cols, [140, 80, 80, 120, 320, 320]):
            self.hist_tree.heading(c, text=c.title())
            self.hist_tree.column(c, width=w)
        self.hist_tree.pack(expand=True, fill="both", pady=5)
        self.load_history()

    # Stats
    def _build_stats(self):
        f = self._frame(self.tab_stats)
        top = self._frame(f)
        self._button(top, "Refresh Stats", self.load_stats).pack(side="left")
        self._button(top, "Export JSON", lambda: self.export_stats("json")).pack(side="left", padx=5)
        self._button(top, "Export Markdown", lambda: self.export_stats("md")).pack(side="left")
        self._button(top, "Export CSV", lambda: self.export_stats("csv")).pack(side="left", padx=5)
        top.pack(anchor="w")
        self.stats_text = self._textbox(f, height=34)
        self.stats_text.pack(expand=True, fill="both", pady=5)
        self.load_stats()

    # Settings
    def _build_settings(self):
        f = self._frame(self.tab_settings)
        self._label(f, "Core Settings", size=16).pack(anchor="w")
        grid = self._frame(f)
        self.s_mode = self._entry_l(grid, "Mode (global/local)")
        self.s_conflict = self._entry_l(grid, "Conflict strategy")
        self.s_dest = self._entry_l(grid, "Destination root")
        self.s_theme = self._entry_l(grid, "Theme (dark/light/system)")
        for e in [self.s_mode, self.s_conflict, self.s_dest, self.s_theme]:
            e[1].pack(fill="x")
        grid.pack(fill="x")
        btn_f = self._frame(f)
        self._button(btn_f, "Load", self.load_settings).pack(side="left")
        self._button(btn_f, "Save", self.save_settings).pack(side="left", padx=5)
        self._button(btn_f, "Open Config Folder", self.open_config_dir).pack(side="left")
        btn_f.pack(pady=10)
        self._label(f, "Feature Toggles", size=14).pack(anchor="w", pady=(10, 0))
        toggles = self._frame(f)
        self.t_trash = self._var("bool", self.config.data.get("use_trash", False))
        self.t_notify = self._var("bool", self.config.data.get("notifications", True))
        self.t_clean = self._var("bool", self.config.data.get("cleanup_empty_dirs", False))
        self.t_hidden = self._var("bool", self.config.data.get("ignore_hidden", True))
        self.t_sanitize = self._var("bool", self.config.data.get("sanitize_names", False))
        self.t_normalize = self._var("bool", self.config.data.get("normalize_names", False))
        self.t_dry = self._var("bool", self.config.data.get("dry_run", False))
        self._check(toggles, "Use quarantine/trash", self.t_trash).grid(row=0, column=0, sticky="w")
        self._check(toggles, "Notifications", self.t_notify).grid(row=0, column=1, sticky="w")
        self._check(toggles, "Cleanup empty dirs", self.t_clean).grid(row=0, column=2, sticky="w")
        self._check(toggles, "Ignore hidden files", self.t_hidden).grid(row=1, column=0, sticky="w")
        self._check(toggles, "Sanitize filenames", self.t_sanitize).grid(row=1, column=1, sticky="w")
        self._check(toggles, "Normalize filenames", self.t_normalize).grid(row=1, column=2, sticky="w")
        self._check(toggles, "Dry run by default", self.t_dry).grid(row=2, column=0, sticky="w")
        toggles.pack(anchor="w")
        self._button(f, "Apply Toggles", self.save_toggles).pack(anchor="w", pady=5)
        self.load_settings()

    # Doctor
    def _build_doctor(self):
        f = self._frame(self.tab_doctor)
        top = self._frame(f)
        self._button(top, "Run Doctor", self.run_doctor).pack(side="left")
        self._button(top, "Open Log", self.open_log).pack(side="left", padx=5)
        self._button(top, "Open Data Dir", self.open_data).pack(side="left")
        top.pack(anchor="w")
        self.doc_text = self._textbox(f, height=30)
        self.doc_text.pack(expand=True, fill="both", pady=5)
        self.run_doctor()

    # Helpers
    def _frame(self, parent):
        return ctk.CTkFrame(parent) if CTK else tk.Frame(parent, bg="#2b2b2b")

    def _label(self, parent, text, size=12):
        if CTK:
            label = ctk.CTkLabel(parent, text=text, font=("Arial", size))
            label.pack(anchor="w")
            return label
        label = tk.Label(parent, text=text, bg="#2b2b2b", fg="#ffffff", font=("Arial", size))
        label.pack(anchor="w")
        return label

    def _button(self, parent, text, cmd):
        if CTK:
            return ctk.CTkButton(parent, text=text, command=cmd)
        b = tk.Button(parent, text=text, command=cmd, bg="#3b3b3b", fg="#ffffff", relief="flat")
        return b

    def _textbox(self, parent, height=10):
        if CTK:
            return ctk.CTkTextbox(parent, height=height)
        return tk.Text(parent, height=height, bg="#1e1e1e", fg="#d4d4d4", insertbackground="#ffffff")

    def _entry(self, parent, val=""):
        if CTK:
            e = ctk.CTkEntry(parent)
        else:
            e = tk.Entry(parent, bg="#1e1e1e", fg="#ffffff", insertbackground="#ffffff")
        e.insert(0, val)
        return e

    def _entry_l(self, parent, label):
        frame = self._frame(parent)
        self._label(frame, label).pack(anchor="w")
        e = self._entry(frame)
        e.pack(fill="x")
        frame.pack(fill="x", pady=2)
        return (frame, e)

    def _check(self, parent, text, var):
        if CTK:
            return ctk.CTkCheckBox(parent, text=text, variable=var)
        return tk.Checkbutton(parent, text=text, variable=var, bg="#2b2b2b", fg="#ffffff", selectcolor="#1e1e1e")

    def _combo(self, parent, values, default):
        if CTK:
            var = ctk.StringVar(value=default)
            c = ctk.CTkOptionMenu(parent, values=list(values), variable=var)
            c._var = var
            return c
        var = tk.StringVar(value=default)
        c = ttk.Combobox(parent, textvariable=var, values=list(values), state="readonly")
        c._var = var
        return c

    def _var(self, kind, default):
        if kind == "bool":
            return tk.BooleanVar(value=bool(default))
        return tk.StringVar(value=str(default))

    def _get_combo(self, combo):
        if hasattr(combo, "_var"):
            return combo._var.get()
        return combo.get()

    # Actions
    def log(self, msg):
        ts = format_ts(__import__("time").time())
        text = f"[{ts}] {msg}\n"
        for widget in [self.over_log, getattr(self, "watch_log", None)]:
            if widget:
                try:
                    if CTK:
                        widget.configure(state="normal")
                        widget.insert("end", text)
                        widget.see("end")
                        widget.configure(state="disabled")
                    else:
                        widget.insert("end", text)
                        widget.see("end")
                except Exception:
                    pass

    def _refresh_all(self):
        self.load_settings()
        self.load_rules()
        self.load_history()
        self.load_stats()
        self.load_quarantine()
        self.log("JAR GUI ready")

    def new_config(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not p:
            return
        cfg = Config(p, load=False)
        cfg.create_default(force=True)
        messagebox.showinfo("JAR", f"Created {p}")

    def open_config(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if not p:
            return
        try:
            self.config = Config(p)
            self.organizer = Organizer(self.config)
            self.journal = Journal(self.config.paths.db_file)
            self._refresh_all()
            messagebox.showinfo("JAR", "Configuration loaded")
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def save_config(self):
        try:
            path = self.config.save()
            messagebox.showinfo("JAR", f"Saved {path}")
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def add_org_path(self):
        p = filedialog.askdirectory()
        if p:
            self.org_paths.insert("end", p + "\n")

    def use_config_paths(self):
        self.org_paths.delete("1.0", "end")
        for p in self.config.watch_dirs:
            self.org_paths.insert("end", p + "\n")

    def add_watch_path(self):
        p = filedialog.askdirectory()
        if p:
            self.watch_paths.insert("end", p + "\n")

    def use_watch_config(self):
        self.watch_paths.delete("1.0", "end")
        for p in self.config.watch_dirs:
            self.watch_paths.insert("end", p + "\n")

    def _get_paths(self, widget):
        text = widget.get("1.0", "end")
        return [line.strip() for line in text.splitlines() if line.strip()]

    def scan_preview(self):
        paths = self._get_paths(self.org_paths)
        if not paths:
            paths = self.config.watch_dirs
        try:
            plan = self.organizer.plan(paths)
            lines = [f"JAR Plan - {plan.mode} mode | dest: {plan.dest_root}", f"Files: {len(plan.items)} to move: {len(plan.moves)} size: {human_size(plan.total_size)}", ""]
            for item in plan.items[:80]:
                lines.append(f"[{item.action.upper()}] {item.category} | {item.src.name} -> {item.dst.name if item.dst else '-'} | {item.reason}")
            if len(plan.items) > 80:
                lines.append(f"... {len(plan.items) - 80} more")
            self.org_plan.delete("1.0", "end")
            self.org_plan.insert("end", "\n".join(lines))
            self.log(f"Scanned {len(plan.items)} file(s)")
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def run_organize(self, dry):
        paths = self._get_paths(self.org_paths)
        if not paths:
            paths = self.config.watch_dirs
        def work():
            try:
                plan = self.organizer.plan(paths)
                result = self.organizer.execute(plan, dry_run=dry)
                def done():
                    self.log(f"{'Dry run' if dry else 'Organize'}: moved {len(result.moved)} skipped {len(result.skipped)} failed {len(result.failed)}")
                    self.load_history()
                    self.load_stats()
                    self.scan_preview()
                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("JAR", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def toggle_watch(self):
        if self.watching:
            self.stop_watch()
            return
        paths = self._get_paths(self.watch_paths)
        if not paths:
            paths = self.config.watch_dirs
        from ..watcher import WatchService
        def handle(p):
            try:
                plan = self.organizer.plan([p])
                if plan.moves:
                    result = self.organizer.execute(plan)
                    self.root.after(0, lambda: self.log(f"Auto: {Path(p).name} -> {len(result.moved)} moved"))
            except Exception as e:
                self.root.after(0, lambda: self.log(f"Watch error: {e}"))
        try:
            service = WatchService(self.config, paths, handle, process_existing=self.watch_existing.get(),
                                   interval=float(self.watch_interval.get() or 2),
                                   stability=float(self.watch_stability.get() or 2))
            self.watch_service = service
            service.start()
            self.watching = True
            self.watch_btn.configure(text="Watching..." if CTK else "Watching...")
            self.log(f"Started watching {len(paths)} folder(s)")
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def stop_watch(self):
        if hasattr(self, "watch_service"):
            self.watch_service.stop()
        self.watching = False
        try:
            self.watch_btn.configure(text="Start Watching" if CTK else "Start Watching")
        except Exception:
            pass
        self.log("Stopped watching")

    def load_rules(self):
        self.rules_list.delete(0, "end")
        try:
            rules = self.organizer.engine.describe()
            self._rules_cache = rules
            for r in rules:
                if not r["builtin"]:
                    self.rules_list.insert("end", r["name"])
            lines = ["BUILT-IN RULES", "=" * 60]
            for r in rules:
                if r["builtin"]:
                    m = ", ".join(r["extensions"][:8]) if r["extensions"] else r["regex"] or r["globs"][0] if r["globs"] else "-"
                    lines.append(f"{r['name']}: {r['category']} (p{r['priority']}) [{m}]")
            self.builtin_rules.delete("1.0", "end")
            self.builtin_rules.insert("end", "\n".join(lines))
        except Exception as e:
            self.log(f"Rules error: {e}")

    def add_rule(self):
        for w in [self.rule_name[1], self.rule_cat[1], self.rule_ext[1], self.rule_glob[1], self.rule_regex[1], self.rule_dest[1], self.rule_prio[1]]:
            w.delete(0, "end")
        self.rule_prio[1].insert(0, "10")

    def save_rule(self):
        try:
            name = self.rule_name[1].get().strip()
            cat = self.rule_cat[1].get().strip()
            if not name or not cat:
                messagebox.showerror("JAR", "Name and category required")
                return
            extensions = [x.strip() for x in self.rule_ext[1].get().split(",") if x.strip()]
            globs = [x.strip() for x in self.rule_glob[1].get().split(",") if x.strip()]
            rule = {"name": name, "category": cat, "priority": int(self.rule_prio[1].get() or 10),
                    "enabled": True, "extensions": extensions, "globs": globs,
                    "regex": self.rule_regex[1].get().strip(), "destination": self.rule_dest[1].get().strip(), "stop": True}
            rules = list(self.config.data.get("rules") or [])
            rules = [r for r in rules if str(r.get("name")) != name]
            rules.append(rule)
            self.config.set("rules", rules)
            self.config.save()
            self.organizer = Organizer(self.config)
            self.load_rules()
            self.log(f"Saved rule {name}")
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def remove_rule(self):
        sel = self.rules_list.curselection()
        if not sel:
            return
        name = self.rules_list.get(sel[0])
        try:
            rules = [r for r in (self.config.data.get("rules") or []) if str(r.get("name")) != name]
            self.config.set("rules", rules)
            self.config.save()
            self.organizer = Organizer(self.config)
            self.load_rules()
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def toggle_rule(self):
        sel = self.rules_list.curselection()
        if not sel:
            return
        name = self.rules_list.get(sel[0])
        try:
            rules = list(self.config.data.get("rules") or [])
            for r in rules:
                if str(r.get("name")) == name:
                    r["enabled"] = not r.get("enabled", True)
                    break
            self.config.set("rules", rules)
            self.config.save()
            self.organizer = Organizer(self.config)
            self.load_rules()
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def find_duplicates(self):
        paths = self._get_paths(self.org_paths)
        if not paths:
            paths = self.config.watch_dirs
        def work():
            try:
                groups = self.organizer.scan_duplicates(paths)
                self.dup_groups = groups
                def done():
                    self.dup_list.delete(0, "end")
                    self.dup_detail.delete("1.0", "end")
                    total_waste = sum(g.wasted_bytes for g in groups)
                    self.log(f"Duplicates: {len(groups)} groups, {human_size(total_waste)} waste")
                    for i, g in enumerate(groups[:50]):
                        self.dup_list.insert("end", f"Group {i+1}: {len(g.files)} files | {human_size(g.size)} each | waste {human_size(g.wasted_bytes)}")
                    if groups:
                        keeper = choose_keeper(groups[0], self._get_combo(self.dup_keep))
                        lines = [f"Keeps: {keeper}"] + [f"  - {f}" for f in groups[0].files]
                        self.dup_detail.insert("end", "\n".join(lines))
                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("JAR", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def remove_dupes(self):
        if not self.dup_groups:
            messagebox.showinfo("JAR", "No duplicates scanned")
            return
        if not messagebox.askyesno("JAR", "Remove duplicates? (quarantined unless permanent delete is checked)"):
            return
        def work():
            try:
                result = self.organizer.dedupe(self.dup_groups, keep=self._get_combo(self.dup_keep),
                                               permanent=self.dup_permanent.get(), dry_run=False)
                self.root.after(0, lambda: [self.log(f"Dupes: removed {len(result.removed)} reclaimed {human_size(result.bytes_reclaimed)}"), self.find_duplicates(), self.load_quarantine()])
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("JAR", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def load_quarantine(self):
        self.q_list.delete(0, "end")
        try:
            self.q_items = list_quarantine(self.config.quarantine_dir)
            for item in self.q_items[:80]:
                self.q_list.insert("end", f"{item['name']} | {human_size(item['size'])} | {format_ts(item['mtime'])}")
        except Exception as e:
            self.log(f"Quarantine error: {e}")

    def restore_quarantine(self):
        sel = self.q_list.curselection()
        if not sel or not self.q_items:
            return
        item = self.q_items[sel[0]]
        dest = filedialog.askdirectory(title="Restore to folder")
        if not dest:
            return
        try:
            restored = restore_quarantine_item(self.config.quarantine_dir, item["name"], dest)
            messagebox.showinfo("JAR", f"Restored to {restored}")
            self.load_quarantine()
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def purge_quarantine_days(self, days):
        if not messagebox.askyesno("JAR", f"Purge quarantine items older than {days} days?"):
            return
        try:
            removed = purge_quarantine(self.config.quarantine_dir, days * 86400)
            self.log(f"Purged {len(removed)} quarantine item(s)")
            self.load_quarantine()
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def load_history(self):
        for row in self.hist_tree.get_children():
            self.hist_tree.delete(row)
        try:
            ops = self.journal.operations(limit=100)
            for row in ops:
                self.hist_tree.insert("", "end", values=(
                    format_ts(row["ts"], "%Y-%m-%d %H:%M:%S"),
                    row["action"], row["status"], row["category"] or "-",
                    row["src"], row["dst"] or "-"))
        except Exception as e:
            self.log(f"History error: {e}")

    def undo_last(self):
        if not messagebox.askyesno("JAR", "Undo last batch?"):
            return
        try:
            result = self.organizer.undo(count=1)
            messagebox.showinfo("JAR", f"Restored {len(result.restored)} skipped {len(result.skipped)} failed {len(result.failed)}")
            self.load_history()
            self.load_stats()
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def clear_history(self):
        if not messagebox.askyesno("JAR", "Clear all history?"):
            return
        try:
            self.journal.clear()
            self.load_history()
            self.load_stats()
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def load_stats(self):
        try:
            stats = self.journal.stats()
            self.over_moved.configure(text=f"Moved: {stats['moved']}")
            self.over_bytes.configure(text=f"Routed: {human_size(stats['bytes_moved'])}")
            self.over_batches.configure(text=f"Batches: {stats['batches']}")
            self.stats_text.delete("1.0", "end")
            self.stats_text.insert("end", report_text(stats))
        except Exception as e:
            self.log(f"Stats error: {e}")

    def export_stats(self, fmt):
        try:
            from ..reports import export_report
            p = filedialog.asksaveasfilename(defaultextension=f".{fmt}", filetypes=[(fmt.upper(), f"*.{fmt}")])
            if not p:
                return
            stats = self.journal.stats()
            path = export_report(stats, p, fmt)
            messagebox.showinfo("JAR", f"Exported to {path}")
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def load_settings(self):
        try:
            self.s_mode[1].delete(0, "end"); self.s_mode[1].insert(0, self.config.data.get("mode", "global"))
            self.s_conflict[1].delete(0, "end"); self.s_conflict[1].insert(0, self.config.data.get("conflict", "rename"))
            self.s_dest[1].delete(0, "end"); self.s_dest[1].insert(0, str(self.config.destination_root))
            self.s_theme[1].delete(0, "end"); self.s_theme[1].insert(0, self.config.data.get("theme", "dark"))
        except Exception:
            pass

    def save_settings(self):
        try:
            self.config.set("mode", self.s_mode[1].get())
            self.config.set("conflict", self.s_conflict[1].get())
            self.config.set("dest_root", self.s_dest[1].get())
            self.config.set("theme", self.s_theme[1].get())
            self.config.save()
            messagebox.showinfo("JAR", "Settings saved")
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def save_toggles(self):
        try:
            self.config.set("use_trash", bool(self.t_trash.get()))
            self.config.set("notifications", bool(self.t_notify.get()))
            self.config.set("cleanup_empty_dirs", bool(self.t_clean.get()))
            self.config.set("ignore_hidden", bool(self.t_hidden.get()))
            self.config.set("sanitize_names", bool(self.t_sanitize.get()))
            self.config.set("normalize_names", bool(self.t_normalize.get()))
            self.config.set("dry_run", bool(self.t_dry.get()))
            self.config.save()
            messagebox.showinfo("JAR", "Toggles saved")
        except Exception as e:
            messagebox.showerror("JAR", str(e))

    def run_doctor(self):
        try:
            from ..cli import cmd_doctor
            import argparse
            args = argparse.Namespace(json=False, config=str(self.config.paths.config_file), profile=self.config.profile,
                                     quiet=False, verbose=False, no_color=True)
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                cmd_doctor(args)
            self.doc_text.delete("1.0", "end")
            self.doc_text.insert("end", buf.getvalue())
        except Exception as e:
            self.doc_text.delete("1.0", "end")
            self.doc_text.insert("end", str(e))

    def open_dest(self):
        try:
            import os, subprocess
            path = str(self.config.destination_root)
            if os.name == "nt":
                os.startfile(path)
            elif __import__("platform").system() == "Darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            pass

    def open_config_dir(self):
        try:
            import os, subprocess
            path = str(self.config.paths.config_dir)
            if os.name == "nt":
                os.startfile(path)
            elif __import__("platform").system() == "Darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            pass

    def open_log(self):
        try:
            import os, subprocess
            path = str(self.config.paths.log_file)
            if os.name == "nt":
                os.startfile(path)
            elif __import__("platform").system() == "Darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            pass

    def open_data(self):
        try:
            import os, subprocess
            path = str(self.config.paths.data_dir)
            if os.name == "nt":
                os.startfile(path)
            elif __import__("platform").system() == "Darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            pass

    def show_about(self):
        messagebox.showinfo("About", f"{APP_NAME} {__version__}\n{APP_TAGLINE}\n\nJust Automated Routing - 50+ features\nCLI + GUI")

    def show_shortcuts(self):
        messagebox.showinfo("Shortcuts", "F5: Refresh\nCtrl+O: Organize\nCtrl+D: Duplicates\nCtrl+Z: Undo")

    def on_close(self):
        self.stop_watch()
        try:
            self.journal.close()
        except Exception:
            pass
        try:
            self.organizer.close()
        except Exception:
            pass
        self.root.destroy()
