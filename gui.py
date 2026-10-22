"""Tkinter user interface. Talks only to the service layer."""
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from models import PURPOSES, RESOURCE_TYPES, PermissionDenied
from services import BookingService, CampusService, ReportService, ResourceService, AuthService, ValidationError, TS_FORMAT

BG, ACCENT, TEXT = "#f4f6f9", "#12355b", "#1b1b1b"
REFRESH_MS = 30_000


def make_tree(parent, columns, widths=None, height=10):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height, selectmode="browse")
    for i, (key, title) in enumerate(columns):
        tree.heading(key, text=title)
        tree.column(key, width=(widths or {}).get(key, 110), anchor="w")
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return frame, tree


def fill(tree, rows):
    tree.delete(*tree.get_children())
    for iid, values in rows:
        tree.insert("", "end", iid=str(iid), values=values)


def bar_chart(canvas, data, title, unit="h"):
    """Minimal bar chart drawn on a Canvas (no third party libraries)."""
    canvas.delete("all")
    w, h = int(canvas.cget("width")), int(canvas.cget("height"))
    canvas.create_text(w / 2, 14, text=title, font=("Segoe UI", 10, "bold"), fill=TEXT)
    if not data:
        canvas.create_text(w / 2, h / 2, text="No data yet", fill="#666")
        return
    top = max(v for _, v in data) or 1
    left, bottom, usable = 40, h - 28, h - 90
    slot = (w - left - 10) / len(data)
    canvas.create_line(left, 28, left, bottom, fill="#999")
    canvas.create_line(left, bottom, w - 8, bottom, fill="#999")
    for i, (label, value) in enumerate(data):
        x0 = left + i * slot + slot * 0.18
        x1 = left + (i + 1) * slot - slot * 0.18
        y = bottom - usable * (value / top)
        canvas.create_rectangle(x0, y, x1, bottom, fill=ACCENT, outline="")
        canvas.create_text((x0 + x1) / 2, y - 8, text=f"{value:g}{unit}", font=("Segoe UI", 8))
        canvas.create_text((x0 + x1) / 2, bottom + 12, text=label, font=("Segoe UI", 8))


class App(tk.Tk):
    def __init__(self, db):
        super().__init__()
        self.title("Smart Campus Resource Booking System")
        self.geometry("1060x700")
        self.minsize(900, 600)
        self.configure(bg=BG)
        self.db = db
        self.campus_svc = CampusService(db)
        self.resource_svc = ResourceService(db)
        self.booking_svc = BookingService(db, self.campus_svc)
        self.report_svc = ReportService(db)
        self.auth_svc = AuthService(db)
        self.user = None
        self.campus = None        # Campus or None (None = all campuses, operator only)
        self._after_id = None
        self._style()
        self._build_header()
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=12, pady=8)
        self.show_login()
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ---- chrome -------------------------------------------------------------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("Title.TLabel", font=("Segoe UI", 16, "bold"), foreground=ACCENT)
        s.configure("TButton", font=("Segoe UI", 10), padding=6)
        s.configure("Accent.TButton", background=ACCENT, foreground="white")
        s.map("Accent.TButton", background=[("active", "#1d4f85")])
        s.configure("Treeview", rowheight=24, font=("Segoe UI", 9))
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        s.configure("Banner.TLabel", background="#fff4cc", foreground="#4a3b00", padding=6, font=("Segoe UI", 9))
        s.configure("TLabelframe", background=BG)
        s.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=("Segoe UI", 10, "bold"))
        s.configure("TNotebook", background=BG)

    def _build_header(self):
        bar = tk.Frame(self, bg=ACCENT)
        bar.pack(fill="x")
        self.hdr_title = tk.Label(bar, text="Smart Campus", bg=ACCENT, fg="white", font=("Segoe UI", 13, "bold"))
        self.hdr_title.pack(side="left", padx=12, pady=8)
        self.hdr_user = tk.Label(bar, text="", bg=ACCENT, fg="#cfe0f5", font=("Segoe UI", 10))
        self.hdr_user.pack(side="left", padx=12)
        self.btn_logout = ttk.Button(bar, text="Log out", command=self.logout)
        self.btn_switch = ttk.Button(bar, text="Switch campus", command=self.show_campus_select)
        self.hdr_campus = tk.Label(bar, text="", bg=ACCENT, fg="white", font=("Segoe UI", 11, "bold"))
        self.banner = ttk.Label(self, text="", style="Banner.TLabel", wraplength=1000, justify="left")

    def refresh_header(self, selecting=False):
        for w in (self.hdr_title, self.hdr_user, self.hdr_campus, self.btn_logout, self.btn_switch, self.banner):
            w.pack_forget()
        if not self.user:
            self.hdr_title.pack(side="left", padx=12, pady=8)
            return
        # Right hand widgets are packed first so they are never clipped on a narrow window.
        self.btn_logout.pack(side="right", padx=8)
        if self.user.can_switch_campus and not selecting:
            self.btn_switch.pack(side="right", padx=4)
        self.hdr_campus.pack(side="right", padx=14)
        self.hdr_title.pack(side="left", padx=12, pady=8)
        self.hdr_user.config(text=f"{self.user.full_name}  |  {self.user.role.title()}")
        self.hdr_user.pack(side="left", padx=8)
        if selecting:
            self.hdr_campus.config(text="Active campus: none selected yet")
            return
        self.hdr_campus.config(text=f"Active campus: {self.campus.name if self.campus else 'ALL CAMPUSES'}")
        self.banner.pack(fill="x", before=self.body)
        if self.campus:
            self.banner.config(text="Booking policy in effect: " + self.campus_svc.policy(self.campus.id).describe())
        else:
            self.banner.config(text="System-wide view: each campus applies its own booking policy.")

    def clear_body(self):
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        for w in self.body.winfo_children():
            w.destroy()

    def _close(self):
        if self._after_id:
            self.after_cancel(self._after_id)
        self.db.close()
        self.destroy()

    def error(self, exc):
        if isinstance(exc, ValidationError):
            messagebox.showerror("Cannot complete request", "\n".join(f"- {p}" for p in exc.problems))
        elif isinstance(exc, PermissionDenied):
            messagebox.showerror("Access denied", str(exc))
        else:
            raise exc

    # ---- navigation ---------------------------------------------------------
    def show_login(self):
        self.user, self.campus = None, None
        self.clear_body()
        self.refresh_header()
        LoginFrame(self.body, self).pack(expand=True)

    def logout(self):
        self.show_login()

    def after_login(self, user):
        self.user = user
        if user.role == "admin":
            self.campus = self.campus_svc.get(user.campus_id)
            self.show_dashboard()
        else:
            self.show_campus_select()

    def show_campus_select(self):
        self.clear_body()
        self.refresh_header(selecting=True)
        CampusSelectFrame(self.body, self).pack(expand=True)

    def choose_campus(self, campus):
        self.campus = campus
        self.show_dashboard()

    def show_dashboard(self):
        self.clear_body()
        self.refresh_header()
        frame = {"lecturer": LecturerView, "admin": AdminView, "operator": OperatorView}[self.user.role](self.body, self)
        frame.pack(fill="both", expand=True)
        self._schedule(frame)

    def _schedule(self, frame):
        def tick():
            if frame.winfo_exists():
                frame.refresh()
                self._after_id = self.after(REFRESH_MS, tick)
        self._after_id = self.after(REFRESH_MS, tick)


# --------------------------------------------------------------------------- login and campus
class LoginFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        ttk.Label(self, text="Smart Campus Resource Booking", style="Title.TLabel").grid(columnspan=2, pady=(0, 4))
        ttk.Label(self, text="Richfield Graduate Institute of Technology").grid(columnspan=2, pady=(0, 16))
        self.user_var, self.pw_var = tk.StringVar(), tk.StringVar()
        ttk.Label(self, text="Username").grid(row=2, column=0, sticky="e", padx=6, pady=4)
        e1 = ttk.Entry(self, textvariable=self.user_var, width=30)
        e1.grid(row=2, column=1, pady=4)
        ttk.Label(self, text="Password").grid(row=3, column=0, sticky="e", padx=6, pady=4)
        e2 = ttk.Entry(self, textvariable=self.pw_var, show="*", width=30)
        e2.grid(row=3, column=1, pady=4)
        ttk.Button(self, text="Log in", style="Accent.TButton", command=self.login).grid(row=4, column=1, sticky="we", pady=(12, 4))
        ttk.Button(self, text="Register as lecturer", command=self.register).grid(row=5, column=1, sticky="we")
        e2.bind("<Return>", lambda _e: self.login())
        e1.focus_set()

    def login(self):
        try:
            user = self.app.auth_svc.login(self.user_var.get().strip(), self.pw_var.get())
        except ValidationError as exc:
            self.app.error(exc)
            return
        self.app.after_login(user)

    def register(self):
        RegisterDialog(self.app)


class RegisterDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Register lecturer account")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.vars = {k: tk.StringVar() for k in ("username", "full_name", "password", "confirm")}
        for i, (key, label, secret) in enumerate([("username", "Username", False), ("full_name", "Full name", False),
                                                  ("password", "Password (10+ characters)", True), ("confirm", "Confirm password", True)]):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="e", padx=8, pady=5)
            ttk.Entry(self, textvariable=self.vars[key], show="*" if secret else "", width=32).grid(row=i, column=1, padx=8)
        ttk.Button(self, text="Create account", style="Accent.TButton", command=self.submit).grid(row=4, column=1, sticky="e", padx=8, pady=10)
        self.transient(app)
        self.grab_set()

    def submit(self):
        v = {k: x.get() for k, x in self.vars.items()}
        if v["password"] != v["confirm"]:
            messagebox.showerror("Passwords differ", "The two passwords do not match.", parent=self)
            return
        try:
            self.app.auth_svc.register_lecturer(v["username"].strip(), v["full_name"], v["password"])
        except ValidationError as exc:
            messagebox.showerror("Cannot register", "\n".join(f"- {p}" for p in exc.problems), parent=self)
            return
        messagebox.showinfo("Registered", "Account created. You can now log in.", parent=self)
        self.destroy()


class CampusSelectFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.campuses = app.campus_svc.all()
        ttk.Label(self, text="Select a campus", style="Title.TLabel").pack(pady=(0, 10))
        self.listbox = tk.Listbox(self, height=6, width=50, font=("Segoe UI", 11), exportselection=False)
        names = [c.name for c in self.campuses]
        if app.user.role == "operator":
            names.append("All campuses (system wide)")
        for n in names:
            self.listbox.insert("end", n)
        self.listbox.pack()
        self.policy = ttk.Label(self, text="", wraplength=520, style="Banner.TLabel")
        self.policy.pack(fill="x", pady=10)
        self.listbox.bind("<<ListboxSelect>>", self.preview)
        ttk.Button(self, text="Continue", style="Accent.TButton", command=self.go).pack()
        self.listbox.selection_set(0)
        self.preview()

    def preview(self, _e=None):
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.campuses):
            c = self.campuses[sel[0]]
            self.policy.config(text="Policy: " + self.app.campus_svc.policy(c.id).describe())
        else:
            self.policy.config(text="Each campus keeps its own booking policy; you will see all campuses.")

    def go(self):
        sel = self.listbox.curselection()
        if sel:
            self.app.choose_campus(self.campuses[sel[0]] if sel[0] < len(self.campuses) else None)


# --------------------------------------------------------------------------- lecturer
class LecturerView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.book_tab, self.mine_tab = ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.book_tab, text="Book a resource")
        nb.add(self.mine_tab, text="My bookings")
        self._build_book()
        self._build_mine()
        self.refresh()

    def _build_book(self):
        left = ttk.LabelFrame(self.book_tab, text="Resources and live availability")
        left.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        cols = [("code", "ID"), ("name", "Name"), ("type", "Type"), ("cap", "Capacity"), ("status", "Status now")]
        frame, self.res_tree = make_tree(left, cols, {"code": 90, "name": 150, "type": 130, "cap": 65, "status": 110}, 14)
        frame.pack(fill="both", expand=True, padx=6, pady=6)
        self.res_tree.bind("<<TreeviewSelect>>", lambda _e: self.update_slot_info())
        self.day_busy = tk.Listbox(left, height=5, font=("Consolas", 9))
        ttk.Label(left, text="Existing bookings for the chosen resource and date:").pack(anchor="w", padx=6)
        self.day_busy.pack(fill="x", padx=6, pady=(0, 6))

        right = ttk.LabelFrame(self.book_tab, text="New booking")
        right.pack(side="right", fill="y", padx=6, pady=6)
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.date_var, self.start_var = tk.StringVar(value=tomorrow), tk.StringVar(value="09:00")
        self.dur_var, self.purpose_var = tk.StringVar(value="60"), tk.StringVar(value=PURPOSES[0])
        times = [f"{h:02d}:{m:02d}" for h in range(6, 22) for m in (0, 15, 30, 45)]
        for i, (label, widget) in enumerate([
                ("Date (YYYY-MM-DD)", ttk.Entry(right, textvariable=self.date_var, width=16)),
                ("Start time", ttk.Combobox(right, textvariable=self.start_var, values=times, width=14, state="readonly")),
                ("Duration (minutes)", ttk.Combobox(right, textvariable=self.dur_var, values=[str(x) for x in range(30, 301, 30)], width=14)),
                ("Purpose", ttk.Combobox(right, textvariable=self.purpose_var, values=PURPOSES, width=14, state="readonly"))]):
            ttk.Label(right, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=6)
            widget.grid(row=i, column=1, padx=8)
            widget.bind("<<ComboboxSelected>>", lambda _e: self.update_slot_info())
            widget.bind("<FocusOut>", lambda _e: self.update_slot_info())
        self.slot_info = ttk.Label(right, text="Select a resource.", wraplength=230, justify="left")
        self.slot_info.grid(row=4, column=0, columnspan=2, padx=8, pady=8, sticky="w")
        ttk.Button(right, text="Book resource", style="Accent.TButton", command=self.book).grid(row=5, column=0, columnspan=2, padx=8, pady=8, sticky="we")

    def _build_mine(self):
        cols = [("id", "#"), ("campus", "Campus"), ("res", "Resource"), ("start", "Start"), ("end", "End"), ("purpose", "Purpose")]
        top = ttk.LabelFrame(self.mine_tab, text="Active bookings (future)")
        top.pack(fill="both", expand=True, padx=6, pady=6)
        f1, self.active_tree = make_tree(top, cols, {"id": 40, "campus": 110, "res": 200, "start": 130, "end": 130, "purpose": 100}, 7)
        f1.pack(fill="both", expand=True, padx=6, pady=6)
        ttk.Button(top, text="Cancel selected booking", command=self.cancel).pack(anchor="e", padx=6, pady=(0, 6))
        bottom = ttk.LabelFrame(self.mine_tab, text="Booking history (past and cancelled)")
        bottom.pack(fill="both", expand=True, padx=6, pady=6)
        f2, self.hist_tree = make_tree(bottom, cols + [("status", "Status")], {"id": 40, "campus": 110, "res": 200, "start": 130, "end": 130, "purpose": 100, "status": 90}, 7)
        f2.pack(fill="both", expand=True, padx=6, pady=6)

    # --- behaviour
    def refresh(self):
        app = self.app
        campus_id = app.campus.id if app.campus else None
        rows = []
        for r in app.resource_svc.list(campus_id):
            status, until = app.booking_svc.availability_now(r.id)
            rows.append((r.id, (r.code, r.name, r.type, r.capacity, "Available" if status == "Available" else f"In use until {until}")))
        keep = self.res_tree.selection()
        fill(self.res_tree, rows)
        if keep and self.res_tree.exists(keep[0]):
            self.res_tree.selection_set(keep[0])
        fmt = lambda b: (b["id"], (b["id"], b["campus_name"], f"{b['code']} {b['resource_name']}", b["start_ts"], b["end_ts"], b["purpose"]))
        fill(self.active_tree, [fmt(b) for b in app.booking_svc.for_lecturer(app.user, "active")])
        fill(self.hist_tree, [(b["id"], fmt(b)[1] + (b["status"].title(),)) for b in app.booking_svc.for_lecturer(app.user, "history")])
        self.update_slot_info()

    def _parse(self):
        try:
            start = datetime.strptime(f"{self.date_var.get().strip()} {self.start_var.get()}", TS_FORMAT)
            dur = int(self.dur_var.get())
        except ValueError:
            return None, None
        return start, dur

    def update_slot_info(self):
        sel = self.res_tree.selection()
        self.day_busy.delete(0, "end")
        start, dur = self._parse()
        if not sel:
            self.slot_info.config(text="Select a resource.")
            return
        if start is None:
            self.slot_info.config(text="Enter the date as YYYY-MM-DD and a whole number of minutes.")
            return
        rid = int(sel[0])
        for s, e in self.app.booking_svc.busy_slots(rid, start):
            self.day_busy.insert("end", f"{s:%H:%M} - {e:%H:%M}")
        if not self.day_busy.size():
            self.day_busy.insert("end", "(no bookings on this date)")
        free = self.app.booking_svc.is_free(rid, start, dur)
        self.slot_info.config(text="This slot is FREE." if free else "This slot is NOT available (overlap).",
                              foreground="#0a6b2a" if free else "#a40000")

    def book(self):
        sel = self.res_tree.selection()
        start, dur = self._parse()
        if not sel or start is None:
            messagebox.showwarning("Incomplete", "Choose a resource and enter a valid date, time and duration.")
            return
        try:
            bid = self.app.booking_svc.create(self.app.user, int(sel[0]), start, dur, self.purpose_var.get())
        except (ValidationError, PermissionDenied) as exc:
            self.app.error(exc)
            return
        messagebox.showinfo("Booked", f"Booking #{bid} confirmed.")
        self.refresh()

    def cancel(self):
        sel = self.active_tree.selection()
        if not sel:
            messagebox.showwarning("Select a booking", "Select an active booking first.")
            return
        if not messagebox.askyesno("Confirm", "Cancel this booking?"):
            return
        try:
            self.app.booking_svc.cancel(self.app.user, int(sel[0]))
        except (ValidationError, PermissionDenied) as exc:
            self.app.error(exc)
            return
        self.refresh()


# --------------------------------------------------------------------------- administrator
class AdminView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.res_tab, self.book_tab, self.use_tab = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.res_tab, text="Resources")
        nb.add(self.book_tab, text="Campus bookings")
        nb.add(self.use_tab, text="Availability and usage")
        self._build()
        self.refresh()

    def _build(self):
        cols = [("code", "ID"), ("name", "Name"), ("type", "Type"), ("cap", "Capacity"), ("status", "Status now")]
        f, self.res_tree = make_tree(self.res_tab, cols, {"code": 100, "name": 200, "type": 160, "cap": 70, "status": 130}, 12)
        f.pack(fill="both", expand=True, padx=8, pady=8)
        self.res_tree.bind("<<TreeviewSelect>>", self.load_selected)
        form = ttk.LabelFrame(self.res_tab, text="Add, update or remove")
        form.pack(fill="x", padx=8, pady=6)
        self.v = {k: tk.StringVar() for k in ("code", "name", "type", "cap")}
        self.v["type"].set(RESOURCE_TYPES[0])
        widgets = [("Resource ID", ttk.Entry(form, textvariable=self.v["code"], width=14)),
                   ("Name", ttk.Entry(form, textvariable=self.v["name"], width=22)),
                   ("Type", ttk.Combobox(form, textvariable=self.v["type"], values=RESOURCE_TYPES, state="readonly", width=20)),
                   ("Capacity", ttk.Entry(form, textvariable=self.v["cap"], width=8))]
        for i, (lbl, w) in enumerate(widgets):
            ttk.Label(form, text=lbl).grid(row=0, column=i * 2, padx=(8, 2), pady=8)
            w.grid(row=0, column=i * 2 + 1, padx=(0, 8))
        self.code_entry = widgets[0][1]
        ttk.Button(form, text="Add", style="Accent.TButton", command=self.add).grid(row=1, column=1, pady=6)
        ttk.Button(form, text="Update selected", command=self.update).grid(row=1, column=3)
        ttk.Button(form, text="Remove selected", command=self.remove).grid(row=1, column=5)

        bcols = [("id", "#"), ("res", "Resource"), ("who", "Lecturer"), ("start", "Start"), ("end", "End"), ("purpose", "Purpose"), ("status", "Status")]
        f2, self.bk_tree = make_tree(self.book_tab, bcols, {"id": 40, "res": 210, "who": 160, "start": 130, "end": 130, "purpose": 90, "status": 80}, 20)
        f2.pack(fill="both", expand=True, padx=8, pady=8)

        ucols = [("code", "ID"), ("name", "Name"), ("n", "Bookings"), ("h", "Hours booked")]
        f3, self.use_tree = make_tree(self.use_tab, ucols, {"code": 100, "name": 220, "n": 90, "h": 110}, 8)
        f3.pack(fill="x", padx=8, pady=8)
        self.canvas = tk.Canvas(self.use_tab, width=620, height=240, bg="white", highlightthickness=1, highlightbackground="#ccc")
        self.canvas.pack(pady=8)

    def refresh(self):
        a = self.app
        rows = []
        for r in a.resource_svc.list(a.campus.id):
            st, until = a.booking_svc.availability_now(r.id)
            rows.append((r.id, (r.code, r.name, r.type, r.capacity, "Available" if st == "Available" else f"In use until {until}")))
        fill(self.res_tree, rows)
        fill(self.bk_tree, [(b["id"], (b["id"], f"{b['code']} {b['resource_name']}", b["lecturer_name"], b["start_ts"], b["end_ts"], b["purpose"], b["status"].title()))
                            for b in a.booking_svc.for_campus(a.user)])
        fill(self.use_tree, [(i, (r["code"], r["name"], r["bookings"], f"{r['hours']:.1f}")) for i, r in enumerate(a.report_svc.usage_by_resource(a.user))])
        bar_chart(self.canvas, a.report_svc.usage_by_weekday(a.user), "Booked hours by weekday (usage trend)")

    def load_selected(self, _e=None):
        sel = self.res_tree.selection()
        if not sel:
            return
        vals = self.res_tree.item(sel[0], "values")
        for k, val in zip(("code", "name", "type", "cap"), vals[:4]):
            self.v[k].set(val)

    def _capacity(self):
        try:
            return int(self.v["cap"].get())
        except ValueError:
            return 0

    def add(self):
        self._run(lambda: self.app.resource_svc.add(self.app.user, self.v["code"].get(), self.v["name"].get(),
                                                    self.v["type"].get(), self._capacity(), self.app.campus.id))

    def update(self):
        sel = self.res_tree.selection()
        if not sel:
            return messagebox.showwarning("Select a resource", "Select a resource to update.")
        self._run(lambda: self.app.resource_svc.update(self.app.user, int(sel[0]), self.v["name"].get(), self.v["type"].get(), self._capacity()))

    def remove(self):
        sel = self.res_tree.selection()
        if not sel:
            return messagebox.showwarning("Select a resource", "Select a resource to remove.")
        if messagebox.askyesno("Confirm", "Remove this resource? Its history is kept."):
            self._run(lambda: self.app.resource_svc.remove(self.app.user, int(sel[0]), datetime.now()))

    def _run(self, action):
        try:
            action()
        except (ValidationError, PermissionDenied) as exc:
            self.app.error(exc)
            return
        self.refresh()


# --------------------------------------------------------------------------- system operator
class OperatorView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.b_tab, self.r_tab, self.c_tab = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(self.b_tab, text="Bookings")
        nb.add(self.r_tab, text="Resources")
        nb.add(self.c_tab, text="Comparative report")
        bcols = [("id", "#"), ("campus", "Campus"), ("res", "Resource"), ("who", "Lecturer"), ("start", "Start"), ("end", "End"), ("status", "Status")]
        f, self.bk_tree = make_tree(self.b_tab, bcols, {"id": 40, "campus": 110, "res": 210, "who": 150, "start": 130, "end": 130, "status": 80}, 22)
        f.pack(fill="both", expand=True, padx=8, pady=8)
        rcols = [("campus", "Campus"), ("code", "ID"), ("name", "Name"), ("type", "Type"), ("cap", "Capacity"), ("status", "Status now")]
        f2, self.res_tree = make_tree(self.r_tab, rcols, {"campus": 120, "code": 100, "name": 190, "type": 150, "cap": 70, "status": 130}, 22)
        f2.pack(fill="both", expand=True, padx=8, pady=8)
        ccols = [("campus", "Campus"), ("res", "Resources"), ("n", "Bookings"), ("h", "Hours"), ("avg", "Avg minutes"), ("lec", "Lecturers"), ("can", "Cancelled")]
        f3, self.cmp_tree = make_tree(self.c_tab, ccols, {k: 105 for k, _ in ccols}, 5)
        f3.pack(fill="x", padx=8, pady=8)
        self.canvas = tk.Canvas(self.c_tab, width=620, height=240, bg="white", highlightthickness=1, highlightbackground="#ccc")
        self.canvas.pack(pady=8)
        self.refresh()

    def refresh(self):
        a = self.app
        cid = a.campus.id if a.campus else None
        fill(self.bk_tree, [(b["id"], (b["id"], b["campus_name"], f"{b['code']} {b['resource_name']}", b["lecturer_name"], b["start_ts"], b["end_ts"], b["status"].title()))
                            for b in a.booking_svc.for_campus(a.user, cid)])
        names = {c.id: c.name for c in a.campus_svc.all()}
        rows = []
        for r in a.resource_svc.list(cid):
            st, until = a.booking_svc.availability_now(r.id)
            rows.append((r.id, (names[r.campus_id], r.code, r.name, r.type, r.capacity, "Available" if st == "Available" else f"In use until {until}")))
        fill(self.res_tree, rows)
        comp = a.report_svc.comparative(a.user)
        fill(self.cmp_tree, [(i, (r["campus"], r["resources"], r["bookings"], f"{r['hours']:.1f}", r["avg_minutes"], r["lecturers"], r["cancelled"])) for i, r in enumerate(comp)])
        bar_chart(self.canvas, [(r["campus"], round(r["hours"], 1)) for r in comp], "Booked hours per campus")
