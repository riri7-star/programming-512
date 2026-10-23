# Smart Campus Resource Booking System

Programming 512 Assignment

## What this program does

This program lets lecturers book shared things at their campus, such as computer labs, projectors, seminar rooms and presentation equipment. Each campus has its own booking rules. The program saves everything in a database, so nothing is lost when you close it.

## What you need

- Python 3.8 or newer
- Nothing else to install. Tkinter and SQLite come with Python.

## How to run it

Open a terminal in the project folder and type:

    python main.py

The first time you run it, the program creates a file called `smart_campus.db` and adds some sample data. After that it uses the same file each time.

To run the tests, type:

    python -m unittest -v test_logic

## Log in details for testing

Every account below uses the same password: `Campus#2026!`

| Role | Username |
|---|---|
| Lecturer | t.mokoena, l.naidoo, a.vandermerwe |
| Campus administrator | admin_jhb, admin_dbn, admin_cpt, admin_cnt |
| System operator | operator |

## What each user can do

**Lecturer**
- Register a new account and log in
- See which resources are free right now
- Book a resource
- Cancel a booking that has not started yet
- See their current bookings and their past bookings

**Campus administrator**
- Add, change and remove resources, but only at their own campus
- See all bookings at their campus
- See how much each resource is used, with a bar chart of hours booked on each day of the week

**System operator**
- See bookings and resources for all campuses
- Compare the campuses in a report and a bar chart

## Other things the program does

- After logging in, you choose a campus. Administrators go straight to their own campus.
- The screen refreshes by itself every 30 seconds.
- Two resources cannot have the same ID. Capital letters and small letters count as the same.
- Two bookings cannot overlap on the same resource.
- Removing a resource does not delete it. It is hidden, so the booking history stays. You cannot remove a resource that still has future bookings.

## Booking rules for each campus

| Campus | Days | Hours | Longest booking | Book up to | Extra rule |
|---|---|---|---|---|---|
| Johannesburg | Mon to Fri | 07:00 to 18:00 | 3 hours | 30 days ahead | Computer labs must finish by 16:00 |
| Centurion | Mon to Fri | 07:00 to 18:00 | 3 hours | 30 days ahead | None |
| Durban | Mon to Sat | 08:00 to 17:00 | 2 hours | 14 days ahead | Seminar rooms are closed on Saturdays |
| Cape Town | Every day | 07:00 to 21:00 | 4 hours | 21 days ahead | Assessment bookings of labs can be made 60 days ahead |

## The files in this project

| File | What it does |
|---|---|
| main.py | Starts the program |
| gui.py | The windows and buttons the user sees |
| services.py | The main rules: login, resources, bookings and reports |
| policies.py | The booking rules for each campus |
| models.py | The user roles, campuses and resources |
| db.py | Connects to the SQLite database and creates the tables |
| seed.py | Adds the starting campuses, resources, users and sample bookings |
| test_logic.py | The tests |

## How it is built

- **User roles:** There is one `User` class. `Lecturer`, `CampusAdministrator` and `SystemOperator` are built from it. Each role has its own list of things it is allowed to do.
- **Adding a new campus rule:** Write one new class in `policies.py` and register it. No other file needs to change.
- **Passwords:** Passwords are never saved as plain text. They are scrambled (hashed) with a random salt. An account is locked for 5 minutes after 5 wrong passwords. A password must have at least 10 characters.
- **Safe database use:** The SQL uses placeholders, so a user cannot trick the database by typing code into a box.
- **No double bookings:** The program checks for a clash and saves the booking in one step, so two people cannot book the same slot at the same time.
- **Separate parts:** The rules in `services.py` do not use Tkinter, so they can be tested without opening a window.

## Tests

`test_logic.py` has 28 tests. They check:
- logging in, locking and registering
- what each role is allowed to do
- the resource rules
- overlapping bookings and each campus rule
- cancelling bookings
- the reports
- adding a new campus rule
- data still being there after the program is closed and opened again
