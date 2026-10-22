from datetime import datetime, timedelta

from models import ROLE_CLASSES
from services import AuthService, BookingService, CampusService, ResourceService, TS_FORMAT

CAMPUSES = [("Johannesburg", "johannesburg"), ("Durban", "durban"), ("Cape Town", "cape_town"), ("Centurion", "centurion")]
RESOURCES = { 
    "Johannesburg": [("JHB-LAB1", "Computer Lab 1", "Computer Lab", 40), ("JHB-LAB2", "Computer Lab 2", "Computer Lab", 30),
                     ("JHB-PRJ1", "Portable Projector A", "Projector", 1), ("JHB-SEM1", "Seminar Room 1", "Seminar Room", 25),
                     ("JHB-PRS1", "Presentation Kit", "Presentation Equipment", 1)],
    "Centurion": [("CNT-LAB1", "Computer Lab 1", "Computer Lab", 40), ("CNT-LAB2", "Computer Lab 2", "Computer Lab", 30),
                  ("CNT-PRJ1", "Portable Projector A", "Projector", 1), ("CNT-SEM1", "Seminar Room 1", "Seminar Room", 25),
                  ("CNT-PRS1", "Presentation Kit", "Presentation Equipment", 1)],
    "Durban": [("DBN-LAB1", "Computer Lab 1", "Computer Lab", 35), ("DBN-PRJ1", "Portable Projector A", "Projector", 1),
               ("DBN-SEM1", "Seminar Room 1", "Seminar Room", 20), ("DBN-PRS1", "Presentation Kit", "Presentation Equipment", 1)],
    "Cape Town": [("CPT-LAB1", "Computer Lab 1", "Computer Lab", 45), ("CPT-LAB2", "Computer Lab 2", "Computer Lab", 45),
                  ("CPT-PRJ1", "Portable Projector A", "Projector", 1), ("CPT-SEM1", "Seminar Room 1", "Seminar Room", 30),
                  ("CPT-PRS1", "Presentation Kit", "Presentation Equipment", 1)],
}
DEMO_PASSWORD = "Campus#2026!" 


def seed(db, with_demo_bookings=True, iterations=None):
    if db.one("SELECT 1 FROM campuses"):
        return False
    kwargs = {"iterations": iterations} if iterations else {}
    auth, campuses, resources = AuthService(db, **kwargs), CampusService(db), ResourceService(db)
    ids = {name: campuses.add(name, key) for name, key in CAMPUSES}
    admin = {n: ROLE_CLASSES["admin"](0, "seed", "seed", ids[n]) for n in ids}
    for name, rows in RESOURCES.items():
        for code, rname, rtype, cap in rows:
            resources.add(admin[name], code, rname, rtype, cap, ids[name])
    slug = {"Johannesburg": "jhb", "Durban": "dbn", "Cape Town": "cpt", "Centurion": "cnt"}
    for name, cid in ids.items():
        auth.create_privileged_user(f"admin_{slug[name]}", f"{name} Administrator", DEMO_PASSWORD, "admin", cid)
    auth.create_privileged_user("operator", "Head Office Operator", DEMO_PASSWORD, "operator")
    lecturer_ids = [auth.register_lecturer(u, n, DEMO_PASSWORD) for u, n in
                    [("t.mokoena", "Thabo Mokoena"), ("l.naidoo", "Lerato Naidoo"), ("a.vandermerwe", "Anke van der Merwe")]]
    if with_demo_bookings:
        _demo_bookings(db, ids, lecturer_ids)
    return True


def _demo_bookings(db, campus_ids, lecturer_ids):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    res = {r["code"]: r for r in db.query("SELECT * FROM resources")}
    plan = [
        ("JHB-LAB1", 0, -10, 9, 120), ("JHB-LAB1", 1, -8, 13, 90), ("JHB-SEM1", 2, -6, 10, 60),
        ("CNT-LAB1", 0, -8, 9, 120), ("CNT-SEM1", 1, 2, 11, 90),
        ("DBN-LAB1", 0, -9, 8, 120), ("DBN-PRJ1", 1, -5, 9, 60), ("DBN-SEM1", 2, 4, 10, 60),
        ("CPT-LAB1", 2, -7, 8, 240), ("CPT-LAB2", 0, -4, 14, 180), ("CPT-SEM1", 1, -3, 11, 90),
        ("JHB-LAB2", 1, 3, 9, 120), ("CPT-PRS1", 0, 5, 15, 60), ("CPT-LAB1", 1, 6, 9, 120)
    ]
    for code, who, offset, hour, minutes in plan:
        start = today + timedelta(days=offset, hours=hour)
        r = res[code]
        db.execute("INSERT INTO bookings (resource_id,lecturer_id,campus_id,start_ts,end_ts,duration_min,purpose,created_at) "
                   "VALUES (?,?,?,?,?,?,?,?)",
                   (r["id"], lecturer_ids[who], r["campus_id"], start.strftime(TS_FORMAT),
                    (start + timedelta(minutes=minutes)).strftime(TS_FORMAT), minutes, "Teaching",
                    (start - timedelta(days=2)).strftime(TS_FORMAT)))