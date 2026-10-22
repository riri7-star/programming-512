"""Business logic. No Tkinter imports here, so every rule can be unit tested."""
import hashlib
import hmac
import re
import secrets
from collections import defaultdict
from datetime import datetime, timedelta

from models import (Campus, PermissionDenied, Resource, build_user, RESOURCE_TYPES, PURPOSES)
from policies import policy_for

TS_FORMAT = "%Y-%m-%d %H:%M"
PBKDF2_ITERATIONS = 600_000   # OWASP minimum for PBKDF2-HMAC-SHA256


class ValidationError(Exception):
    """Carries a list of user readable problems."""

    def __init__(self, problems):
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        super().__init__("; ".join(self.problems))


# --------------------------------------------------------------------------- security
class PasswordHasher:
    @staticmethod
    def hash(password, salt=None, iterations=PBKDF2_ITERATIONS):
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return salt, digest, iterations

    @staticmethod
    def verify(password, salt, expected, iterations):
        _, digest, _ = PasswordHasher.hash(password, salt, iterations)
        return hmac.compare_digest(digest, expected)  # constant time comparison


class AuthService:
    USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
    MAX_ATTEMPTS, LOCK_MINUTES = 5, 5

    def __init__(self, db, clock=datetime.now, iterations=PBKDF2_ITERATIONS):
        self.db, self.clock, self.iterations = db, clock, iterations
        self._failures = defaultdict(list)    # dict of username -> list of failure times

    def register_lecturer(self, username, full_name, password, campus_id=None):
        problems = []
        if not self.USERNAME_RE.match(username or ""):
            problems.append("Username must be 3-30 letters, digits, dots, hyphens or underscores.")
        if not (full_name or "").strip():
            problems.append("Full name is required.")
        if len(password or "") < 10:
            problems.append("Password must be at least 10 characters (NIST SP 800-63B-4 allows long passphrases).")
        if problems:
            raise ValidationError(problems)
        return self._insert_user(username, full_name.strip(), password, "lecturer", campus_id)

    def create_privileged_user(self, username, full_name, password, role, campus_id=None):
        """Used by the seeding script only; the GUI never exposes this path."""
        if role not in ("admin", "operator"):
            raise ValueError("role must be 'admin' or 'operator'")
        return self._insert_user(username, full_name, password, role, campus_id)

    def _insert_user(self, username, full_name, password, role, campus_id):
        if self.db.one("SELECT 1 FROM users WHERE username = ?", (username,)):
            raise ValidationError("That username is already taken.")
        salt, digest, iters = PasswordHasher.hash(password, iterations=self.iterations)
        return self.db.execute(
            "INSERT INTO users (username, full_name, role, campus_id, salt, pw_hash, iterations, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (username, full_name, role, campus_id, salt, digest, iters, self.clock().strftime(TS_FORMAT)))

    def login(self, username, password):
        now = self.clock()
        recent = [t for t in self._failures[username.lower()] if now - t < timedelta(minutes=self.LOCK_MINUTES)]
        self._failures[username.lower()] = recent
        if len(recent) >= self.MAX_ATTEMPTS:
            raise ValidationError(f"Too many failed attempts. Try again in {self.LOCK_MINUTES} minutes.")
        row = self.db.one("SELECT * FROM users WHERE username = ?", (username,))
        # Always run one hash so response time does not reveal whether the user exists.
        if row is None:
            PasswordHasher.hash(password, b"\x00" * 16, self.iterations)
            ok = False
        else:
            ok = PasswordHasher.verify(password, row["salt"], row["pw_hash"], row["iterations"])
        if not ok:
            self._failures[username.lower()].append(now)
            raise ValidationError("Invalid username or password.")
        self._failures.pop(username.lower(), None)
        return build_user(row)


# --------------------------------------------------------------------------- campuses and resources
class CampusService:
    def __init__(self, db):
        self.db = db

    def all(self):
        return [Campus(r["id"], r["name"], r["policy_key"]) for r in self.db.query("SELECT * FROM campuses ORDER BY name")]

    def get(self, campus_id):
        r = self.db.one("SELECT * FROM campuses WHERE id = ?", (campus_id,))
        return Campus(r["id"], r["name"], r["policy_key"]) if r else None

    def add(self, name, policy_key):
        policy_for(policy_key)  # raises ValueError for an unknown rule set
        return self.db.execute("INSERT INTO campuses (name, policy_key) VALUES (?,?)", (name, policy_key))

    def policy(self, campus_id):
        return policy_for(self.get(campus_id).policy_key)


class ResourceService:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def _to_resource(r):
        return Resource(r["id"], r["code"], r["name"], r["type"], r["capacity"], r["campus_id"], bool(r["active"]))

    def list(self, campus_id=None, include_inactive=False):
        sql, params = "SELECT * FROM resources WHERE 1=1", []
        if campus_id is not None:
            sql += " AND campus_id = ?"; params.append(campus_id)
        if not include_inactive:
            sql += " AND active = 1"
        return [self._to_resource(r) for r in self.db.query(sql + " ORDER BY type, code", params)]

    def codes(self):
        """A set of every identifier ever issued; membership tests are O(1)."""
        return {r["code"].upper() for r in self.db.query("SELECT code FROM resources")}

    def add(self, actor, code, name, rtype, capacity, campus_id):
        actor.require("manage_resources")
        self._check_scope(actor, campus_id)
        code = (code or "").strip().upper()
        problems = []
        if not re.fullmatch(r"[A-Z0-9-]{3,15}", code):
            problems.append("Resource ID must be 3-15 letters, digits or hyphens.")
        if not (name or "").strip():
            problems.append("Name is required.")
        if rtype not in RESOURCE_TYPES:
            problems.append("Unknown resource type.")
        if not isinstance(capacity, int) or capacity < 1:
            problems.append("Capacity must be a whole number of at least 1.")
        if code in self.codes():
            problems.append(f"Duplicate rejected: resource ID {code} already exists.")
        if problems:
            raise ValidationError(problems)
        return self.db.execute("INSERT INTO resources (code,name,type,capacity,campus_id) VALUES (?,?,?,?,?)",
                               (code, name.strip(), rtype, capacity, campus_id))

    def update(self, actor, resource_id, name, rtype, capacity):
        actor.require("manage_resources")
        res = self._owned(actor, resource_id)
        if not (name or "").strip() or rtype not in RESOURCE_TYPES or not isinstance(capacity, int) or capacity < 1:
            raise ValidationError("Name, a valid type and a capacity of at least 1 are required.")
        self.db.execute("UPDATE resources SET name=?, type=?, capacity=? WHERE id=?",
                        (name.strip(), rtype, capacity, res.id))

    def remove(self, actor, resource_id, now):
        """Soft delete keeps booking history intact. Blocked while future bookings exist."""
        actor.require("manage_resources")
        res = self._owned(actor, resource_id)
        pending = self.db.one("SELECT COUNT(*) c FROM bookings WHERE resource_id=? AND status='active' AND start_ts>?",
                              (res.id, now.strftime(TS_FORMAT)))["c"]
        if pending:
            raise ValidationError(f"{pending} future booking(s) exist. Cancel or move them before removing this resource.")
        self.db.execute("UPDATE resources SET active=0 WHERE id=?", (res.id,))

    def _owned(self, actor, resource_id):
        r = self.db.one("SELECT * FROM resources WHERE id=?", (resource_id,))
        if r is None:
            raise ValidationError("Resource not found.")
        self._check_scope(actor, r["campus_id"])
        return self._to_resource(r)

    @staticmethod
    def _check_scope(actor, campus_id):
        if actor.role == "admin" and actor.campus_id != campus_id:
            raise PermissionDenied("Administrators may only manage their own campus.")


# --------------------------------------------------------------------------- bookings
class BookingService:
    def __init__(self, db, campuses, clock=datetime.now):
        self.db, self.campuses, self.clock = db, campuses, clock

    def create(self, lecturer, resource_id, start, duration_min, purpose="Teaching"):
        lecturer.require("book")
        if purpose not in PURPOSES:
            raise ValidationError("Unknown booking purpose.")
        end = start + timedelta(minutes=duration_min)
        with self.db.transaction() as conn:          # atomic check-then-insert
            res = conn.execute("SELECT * FROM resources WHERE id=?", (resource_id,)).fetchone()
            if res is None or not res["active"]:
                raise ValidationError("That resource is not available for booking.")
            policy = self.campuses.policy(res["campus_id"])
            problems = policy.violations(start, duration_min, res["type"], purpose, self.clock())
            if problems:
                raise ValidationError(problems)
            clash = conn.execute(
                "SELECT start_ts, end_ts FROM bookings WHERE resource_id=? AND status='active' "
                "AND start_ts < ? AND end_ts > ?",
                (resource_id, end.strftime(TS_FORMAT), start.strftime(TS_FORMAT))).fetchone()
            if clash:
                raise ValidationError(f"Overlaps an existing booking ({clash['start_ts']} to {clash['end_ts']}).")
            return conn.execute(
                "INSERT INTO bookings (resource_id,lecturer_id,campus_id,start_ts,end_ts,duration_min,purpose,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (resource_id, lecturer.id, res["campus_id"], start.strftime(TS_FORMAT), end.strftime(TS_FORMAT),
                 duration_min, purpose, self.clock().strftime(TS_FORMAT))).lastrowid

    def cancel(self, lecturer, booking_id):
        lecturer.require("cancel_own_booking")
        with self.db.transaction() as conn:
            b = conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
            if b is None or b["lecturer_id"] != lecturer.id:
                raise PermissionDenied("You can only cancel your own bookings.")
            if b["status"] != "active":
                raise ValidationError("That booking is already cancelled.")
            if b["start_ts"] <= self.clock().strftime(TS_FORMAT):
                raise ValidationError("Only future bookings can be cancelled.")
            conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))

    _SELECT = ("SELECT b.*, r.code, r.name AS resource_name, r.type AS resource_type, c.name AS campus_name, "
               "u.full_name AS lecturer_name FROM bookings b JOIN resources r ON r.id=b.resource_id "
               "JOIN campuses c ON c.id=b.campus_id JOIN users u ON u.id=b.lecturer_id ")

    def for_lecturer(self, lecturer, scope):
        """scope: 'active' (future, not cancelled) or 'history' (past or cancelled)."""
        lecturer.require("view_own_bookings")
        now = self.clock().strftime(TS_FORMAT)
        cond = ("b.status='active' AND b.start_ts > ?" if scope == "active"
                else "(b.status='cancelled' OR b.start_ts <= ?)")
        order = "ASC" if scope == "active" else "DESC"
        return self.db.query(f"{self._SELECT} WHERE b.lecturer_id=? AND {cond} ORDER BY b.start_ts {order}",
                             (lecturer.id, now))

    def for_campus(self, actor, campus_id=None):
        actor.require("view_campus_bookings")
        if actor.role == "admin":
            campus_id = actor.campus_id
        sql, params = self._SELECT + " WHERE 1=1", []
        if campus_id is not None:
            sql += " AND b.campus_id=?"; params.append(campus_id)
        return self.db.query(sql + " ORDER BY b.start_ts DESC", params)

    def busy_slots(self, resource_id, day):
        """List of (start, end) tuples for active bookings on a date."""
        rows = self.db.query("SELECT start_ts,end_ts FROM bookings WHERE resource_id=? AND status='active' "
                             "AND substr(start_ts,1,10)=? ORDER BY start_ts", (resource_id, day.strftime("%Y-%m-%d")))
        return [(datetime.strptime(r["start_ts"], TS_FORMAT), datetime.strptime(r["end_ts"], TS_FORMAT)) for r in rows]

    def availability_now(self, resource_id):
        """('Available', None) or ('In use', end_time) computed against the clock."""
        now = self.clock()
        row = self.db.one("SELECT end_ts FROM bookings WHERE resource_id=? AND status='active' "
                          "AND start_ts<=? AND end_ts>?", (resource_id, now.strftime(TS_FORMAT), now.strftime(TS_FORMAT)))
        return ("In use", row["end_ts"][11:]) if row else ("Available", None)

    def is_free(self, resource_id, start, duration_min):
        end = start + timedelta(minutes=duration_min)
        return self.db.one("SELECT 1 FROM bookings WHERE resource_id=? AND status='active' AND start_ts<? AND end_ts>?",
                           (resource_id, end.strftime(TS_FORMAT), start.strftime(TS_FORMAT))) is None


# --------------------------------------------------------------------------- reporting
class ReportService:
    def __init__(self, db):
        self.db = db

    def usage_by_resource(self, actor, campus_id=None):
        actor.require("view_usage")
        if actor.role == "admin":
            campus_id = actor.campus_id
        sql = ("SELECT r.code, r.name, r.type, COUNT(b.id) AS bookings, COALESCE(SUM(b.duration_min),0)/60.0 AS hours "
               "FROM resources r LEFT JOIN bookings b ON b.resource_id=r.id AND b.status='active' "
               "WHERE r.active=1 ")
        params = []
        if campus_id is not None:
            sql += "AND r.campus_id=? "; params.append(campus_id)
        return self.db.query(sql + "GROUP BY r.id ORDER BY hours DESC, r.code", params)

    def usage_by_weekday(self, actor, campus_id=None):
        actor.require("view_usage")
        if actor.role == "admin":
            campus_id = actor.campus_id
        sql, params = "SELECT start_ts, duration_min FROM bookings WHERE status='active'", []
        if campus_id is not None:
            sql += " AND campus_id=?"; params.append(campus_id)
        counts = defaultdict(float)
        for r in self.db.query(sql, params):
            counts[datetime.strptime(r["start_ts"], TS_FORMAT).strftime("%a")] += r["duration_min"] / 60
        return [(d, round(counts.get(d, 0), 1)) for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]

    def comparative(self, actor):
        actor.require("comparative_reports")
        act = "FROM bookings b WHERE b.campus_id=c.id AND b.status='active'"
        return self.db.query(
            "SELECT c.name AS campus, "
            "(SELECT COUNT(*) FROM resources r WHERE r.campus_id=c.id AND r.active=1) AS resources, "
            f"(SELECT COUNT(*) {act}) AS bookings, "
            f"(SELECT COALESCE(SUM(b.duration_min),0)/60.0 {act}) AS hours, "
            f"(SELECT ROUND(COALESCE(AVG(b.duration_min),0),1) {act}) AS avg_minutes, "
            f"(SELECT COUNT(DISTINCT b.lecturer_id) {act}) AS lecturers, "
            "(SELECT COUNT(*) FROM bookings b WHERE b.campus_id=c.id AND b.status='cancelled') AS cancelled "
            "FROM campuses c ORDER BY hours DESC")
