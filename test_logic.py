"""Unit tests for the business rules. Run:  python -m unittest -v test_logic"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from db import Database
from models import CampusAdministrator, Lecturer, PermissionDenied, SystemOperator
from policies import BookingPolicy, JohannesburgPolicy, register_policy, POLICY_REGISTRY
from seed import seed
from services import (AuthService, BookingService, CampusService, ReportService, ResourceService, ValidationError)

FIXED_NOW = datetime(2026, 10, 19, 9, 0)    
FAST = 1000                              


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "t.db")
        self.db = Database(self.path)
        seed(self.db, with_demo_bookings=False, iterations=FAST)
        self.clock = lambda: FIXED_NOW
        self.auth = AuthService(self.db, clock=self.clock, iterations=FAST)
        self.campuses = CampusService(self.db)
        self.resources = ResourceService(self.db)
        self.bookings = BookingService(self.db, self.campuses, clock=self.clock)
        self.reports = ReportService(self.db)
        self.lecturer = self.auth.login("t.mokoena", "Campus#2026!")
        self.admin_jhb = self.auth.login("admin_jhb", "Campus#2026!")
        self.admin_cnt = self.auth.login("admin_cnt", "Campus#2026!")
        self.operator = self.auth.login("operator", "Campus#2026!")
        self.rid = lambda code: self.db.one("SELECT id FROM resources WHERE code=?", (code,))["id"]

    def tearDown(self):
        self.db.close()


class AuthTests(Base):
    def test_roles_are_subclasses(self):
        self.assertIsInstance(self.lecturer, Lecturer)
        self.assertIsInstance(self.admin_jhb, CampusAdministrator)
        self.assertIsInstance(self.admin_cnt, CampusAdministrator)
        self.assertIsInstance(self.operator, SystemOperator)

    def test_password_not_stored_in_plain_text(self):
        row = self.db.one("SELECT * FROM users WHERE username='t.mokoena'")
        self.assertNotIn(b"Campus#2026!", bytes(row["pw_hash"]))
        self.assertEqual(len(row["salt"]), 16)

    def test_wrong_password_and_unknown_user_same_message(self):
        for u, p in (("t.mokoena", "wrong"), ("nobody", "x")):
            with self.assertRaises(ValidationError) as cm:
                self.auth.login(u, p)
            self.assertEqual(cm.exception.problems, ["Invalid username or password."])

    def test_lockout_after_five_failures(self):
        for _ in range(5):
            with self.assertRaises(ValidationError):
                self.auth.login("t.mokoena", "bad")
        with self.assertRaises(ValidationError) as cm:
            self.auth.login("t.mokoena", "Campus#2026!")
        self.assertIn("Too many", cm.exception.problems[0])

    def test_registration_validation_and_duplicates(self):
        with self.assertRaises(ValidationError):
            self.auth.register_lecturer("ab", "", "short")
        self.auth.register_lecturer("new.lecturer", "New Lecturer", "a long passphrase here")
        with self.assertRaises(ValidationError):
            self.auth.register_lecturer("NEW.LECTURER", "Again", "a long passphrase here")  # case insensitive

    def test_sql_injection_string_is_harmless(self):
        with self.assertRaises(ValidationError):
            self.auth.login("' OR 1=1 --", "x")


class ResourceTests(Base):
    def test_duplicate_rejected_case_insensitive(self):
        cid = self.admin_jhb.campus_id
        with self.assertRaises(ValidationError) as cm:
            self.resources.add(self.admin_jhb, "jhb-lab1", "Copy", "Computer Lab", 10, cid)
        self.assertIn("Duplicate", cm.exception.problems[-1])

    def test_admin_cannot_manage_other_campus(self):
        other = self.campuses.all()[0].id if self.campuses.all()[0].id != self.admin_jhb.campus_id else self.campuses.all()[1].id
        with self.assertRaises(PermissionDenied):
            self.resources.add(self.admin_jhb, "XYZ-001", "Room", "Seminar Room", 10, other)

    def test_lecturer_cannot_add_resource(self):
        with self.assertRaises(PermissionDenied):
            self.resources.add(self.lecturer, "XYZ-001", "Room", "Seminar Room", 10, 1)

    def test_add_update_remove(self):
        cid = self.admin_jhb.campus_id
        rid = self.resources.add(self.admin_jhb, "JHB-NEW1", "Extra Projector", "Projector", 1, cid)
        self.resources.update(self.admin_jhb, rid, "Extra Projector B", "Projector", 2)
        self.assertEqual(self.db.one("SELECT name, capacity FROM resources WHERE id=?", (rid,))["capacity"], 2)
        self.resources.remove(self.admin_jhb, rid, FIXED_NOW)
        self.assertNotIn("JHB-NEW1", [r.code for r in self.resources.list(cid)])
        with self.assertRaises(ValidationError):   
            self.resources.add(self.admin_jhb, "JHB-NEW1", "Again", "Projector", 1, cid)

    def test_remove_blocked_by_future_booking(self):
        self.bookings.create(self.lecturer, self.rid("JHB-PRJ1"), datetime(2026, 10, 20, 9, 0), 60)
        with self.assertRaises(ValidationError):
            self.resources.remove(self.admin_jhb, self.rid("JHB-PRJ1"), FIXED_NOW)


class BookingTests(Base):
    def book(self, code, start, minutes=60, purpose="Teaching"):
        return self.bookings.create(self.lecturer, self.rid(code), start, minutes, purpose)

    def test_successful_booking_links_lecturer_and_campus(self):
        bid = self.book("JHB-LAB1", datetime(2026, 10, 20, 9, 0))
        row = self.db.one("SELECT * FROM bookings WHERE id=?", (bid,))
        self.assertEqual(row["lecturer_id"], self.lecturer.id)
        self.assertEqual(row["campus_id"], self.admin_jhb.campus_id)
        self.assertEqual(row["end_ts"], "2026-10-20 10:00")

    def test_overlap_rejected_adjacent_allowed(self):
        self.book("JHB-LAB1", datetime(2026, 10, 20, 9, 0), 60)
        with self.assertRaises(ValidationError):
            self.book("JHB-LAB1", datetime(2026, 10, 20, 9, 30), 60)
        with self.assertRaises(ValidationError):
            self.book("JHB-LAB1", datetime(2026, 10, 20, 8, 30), 60)
        with self.assertRaises(ValidationError):
            self.book("JHB-LAB1", datetime(2026, 10, 20, 8, 0), 180)   
        self.book("JHB-LAB1", datetime(2026, 10, 20, 10, 0), 60)     
        self.book("JHB-LAB2", datetime(2026, 10, 20, 9, 0), 60)      

    def test_cancelled_slot_can_be_rebooked(self):
        bid = self.book("JHB-LAB1", datetime(2026, 10, 20, 9, 0))
        self.bookings.cancel(self.lecturer, bid)
        self.book("JHB-LAB1", datetime(2026, 10, 20, 9, 0))

    def test_past_booking_rejected(self):
        with self.assertRaises(ValidationError):
            self.book("JHB-LAB1", datetime(2026, 10, 19, 8, 0))

    def test_jhb_policy_rules(self):
        with self.assertRaises(ValidationError) as cm:
            self.book("JHB-SEM1", datetime(2026, 10, 24, 9, 0))    
        self.assertIn("day of the week", cm.exception.problems[0])
        with self.assertRaises(ValidationError):
            self.book("JHB-SEM1", datetime(2026, 10, 20, 9, 0), 240)  
        with self.assertRaises(ValidationError):
            self.book("JHB-LAB1", datetime(2026, 10, 20, 15, 0), 90)   
        with self.assertRaises(ValidationError):
            self.book("JHB-SEM1", datetime(2026, 10, 20, 17, 30), 60)  

    def test_same_request_different_campus_different_outcome(self):
        start = datetime(2026, 10, 24, 9, 0) 
        with self.assertRaises(ValidationError):
            self.book("JHB-PRJ1", start)      
        self.book("DBN-PRJ1", start)             
        self.book("CPT-PRJ1", start)             
        self.book("CNT-PRJ1", start)            
        with self.assertRaises(ValidationError):
            self.book("DBN-SEM1", start + timedelta(hours=2)) 

    def test_durban_two_hour_cap_and_capetown_four(self):
        with self.assertRaises(ValidationError):
            self.book("DBN-LAB1", datetime(2026, 10, 20, 9, 0), 150)
        self.book("CPT-LAB1", datetime(2026, 10, 20, 9, 0), 240)

    def test_capetown_priority_assessment_window(self):
        far = FIXED_NOW + timedelta(days=45)
        far = far.replace(hour=9, minute=0)
        while far.weekday() > 6:
            far += timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.book("CPT-LAB1", far, 60, "Teaching")
        self.book("CPT-LAB1", far, 60, "Assessment")

    def test_only_owner_may_cancel_and_only_future(self):
        bid = self.book("JHB-LAB1", datetime(2026, 10, 20, 9, 0))
        other = self.auth.register_lecturer("other.user", "Other", "another long passphrase")
        other_user = self.auth.login("other.user", "another long passphrase")
        with self.assertRaises(PermissionDenied):
            self.bookings.cancel(other_user, bid)
        self.bookings.cancel(self.lecturer, bid)
        with self.assertRaises(ValidationError):
            self.bookings.cancel(self.lecturer, bid)       # already cancelled
        self.db.execute("INSERT INTO bookings (resource_id,lecturer_id,campus_id,start_ts,end_ts,duration_min,created_at) "
                        "VALUES (?,?,?,?,?,?,?)", (self.rid("JHB-LAB2"), self.lecturer.id, 1, "2026-10-18 09:00", "2026-10-18 10:00", 60, "x"))
        past = self.db.one("SELECT id FROM bookings WHERE start_ts='2026-10-18 09:00'")["id"]
        with self.assertRaises(ValidationError):
            self.bookings.cancel(self.lecturer, past)

    def test_views_active_vs_history(self):
        self.book("JHB-LAB1", datetime(2026, 10, 20, 9, 0))
        b2 = self.book("JHB-LAB2", datetime(2026, 10, 21, 9, 0))
        self.bookings.cancel(self.lecturer, b2)
        self.assertEqual(len(self.bookings.for_lecturer(self.lecturer, "active")), 1)
        self.assertEqual(len(self.bookings.for_lecturer(self.lecturer, "history")), 1)

    def test_availability_now(self):
        rid = self.rid("JHB-LAB1")
        self.assertEqual(self.bookings.availability_now(rid)[0], "Available")
        self.db.execute("INSERT INTO bookings (resource_id,lecturer_id,campus_id,start_ts,end_ts,duration_min,created_at) "
                        "VALUES (?,?,?,?,?,?,?)", (rid, self.lecturer.id, 1, "2026-10-19 08:30", "2026-10-19 10:00", 90, "x"))
        self.assertEqual(self.bookings.availability_now(rid), ("In use", "10:00"))

    def test_role_restrictions(self):
        with self.assertRaises(PermissionDenied):
            self.bookings.create(self.admin_jhb, self.rid("JHB-LAB1"), datetime(2026, 10, 20, 9), 60)
        with self.assertRaises(PermissionDenied):
            self.reports.comparative(self.lecturer)

    def test_admin_sees_only_own_campus(self):
        self.book("JHB-LAB1", datetime(2026, 10, 20, 9, 0))
        self.book("DBN-LAB1", datetime(2026, 10, 20, 9, 0))
        self.book("CNT-LAB1", datetime(2026, 10, 20, 9, 0))
        self.assertEqual(len(self.bookings.for_campus(self.admin_jhb, campus_id=99)), 1)
        self.assertEqual(len(self.bookings.for_campus(self.operator)), 3)

    def test_comparative_report_counts_not_inflated(self):
        self.book("JHB-LAB1", datetime(2026, 10, 20, 9, 0), 120)
        self.book("JHB-LAB2", datetime(2026, 10, 20, 9, 0), 60)
        self.book("CNT-LAB1", datetime(2026, 10, 20, 9, 0), 90)
        rows = {r["campus"]: r for r in self.reports.comparative(self.operator)}
        self.assertEqual(rows["Johannesburg"]["bookings"], 2)
        self.assertAlmostEqual(rows["Johannesburg"]["hours"], 3.0)
        self.assertEqual(rows["Durban"]["bookings"], 0)
        self.assertEqual(rows["Centurion"]["bookings"], 1)
        self.assertEqual(rows["Johannesburg"]["resources"], 5)
        self.assertEqual(rows["Centurion"]["resources"], 5)


class ExtensibilityTests(Base):
    def test_new_campus_with_new_rule_without_touching_existing_code(self):
        @register_policy("pretoria_test")
        class PretoriaPolicy(BookingPolicy):
            max_minutes = 60
            def extra_violations(self, start, duration_min, resource_type, purpose):
                return []
        try:
            cid = self.campuses.add("Pretoria", "pretoria_test")
            self.admin_pta = CampusAdministrator(0, "x", "x", cid)
            rid = self.resources.add(self.admin_pta, "PTA-LAB1", "Lab", "Computer Lab", 20, cid)
            with self.assertRaises(ValidationError):
                self.bookings.create(self.lecturer, rid, datetime(2026, 10, 20, 9, 0), 90)
            self.bookings.create(self.lecturer, rid, datetime(2026, 10, 20, 9, 0), 60)
        finally:
            POLICY_REGISTRY.pop("pretoria_test", None)

    def test_unknown_policy_key_refused(self):
        with self.assertRaises(ValueError):
            self.campuses.add("Nowhere", "does_not_exist")


class PersistenceTests(Base):
    def test_data_survives_reopen(self):
        self.bookings.create(self.lecturer, self.rid("JHB-LAB1"), datetime(2026, 10, 20, 9, 0), 60)
        self.db.close()
        db2 = Database(self.path)
        self.assertEqual(db2.one("SELECT COUNT(*) c FROM bookings")["c"], 1)
        self.assertFalse(seed(db2, iterations=FAST)) 
        db2.close()
        self.db = Database(self.path)


if __name__ == "__main__":
    unittest.main(verbosity=2)