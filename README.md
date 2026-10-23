# Smart Campus Resource Booking System

Programming 512 assignment. Python 3, Tkinter and SQLite.

**GitHub repository:** PASTE_PUBLIC_GITHUB_LINK_HERE

## What it does

Lecturers, campus administrators and system operators book and manage campus resources (labs, projectors, seminar rooms). Three campuses apply different booking policies, overlapping bookings are blocked, and all data persists in SQLite.

## Run

```
cd smart_campus
python main.py
```

No third party packages are needed. Tests: `python -m unittest discover -s smart_campus` (28 tests).

## Demo accounts (password `Campus#2026!`)

| Role | Usernames |
|---|---|
| Campus administrator | admin_jhb, admin_dbn, admin_cpt |
| System operator | operator |
| Lecturer | t.mokoena, l.naidoo, a.vandermerwe |

## Contents

- `smart_campus/`: source code and tests
- `screenshots/`: GUI screenshots used in the report
- Report: `Programming512_Assignment.md` (one folder up from `october-assignments`)
