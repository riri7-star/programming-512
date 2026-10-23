"""Campus booking policies, kept apart from the core booking logic.

Adding a new rule set means writing one subclass and decorating it with
@register_policy("key"). No other module changes (open/closed principle).
"""
from abc import ABC, abstractmethod
from datetime import datetime, time, timedelta

POLICY_REGISTRY = {}  


def register_policy(key):
    def wrap(cls):
        cls.key = key
        POLICY_REGISTRY[key] = cls
        return cls
    return wrap


class BookingPolicy(ABC):
    """Base class. Subclasses return a list of human readable violations."""
    key = "base"
    max_minutes = 180
    open_time = time(7, 0)
    close_time = time(18, 0)
    open_days = frozenset({0, 1, 2, 3, 4}) 
    standard_advance_days = 30

    def describe(self):
        days = "Mon-Sun" if len(self.open_days) == 7 else (
            "Mon-Fri" if self.open_days == {0, 1, 2, 3, 4} else "Mon-Sat")
        return (f"Max {self.max_minutes / 60:g}h per session, {self.open_time:%H:%M}-"
                f"{self.close_time:%H:%M} {days}, book up to {self.standard_advance_days} days ahead"
                + self.extra_description())

    def extra_description(self):
        return ""

    def advance_limit_days(self, resource_type, purpose):
        return self.standard_advance_days

    def violations(self, start, duration_min, resource_type, purpose, now):
        end = start + timedelta(minutes=duration_min)
        problems = []
        if duration_min <= 0:
            problems.append("Duration must be positive.")
        if duration_min > self.max_minutes:
            problems.append(f"Maximum session length on this campus is {self.max_minutes} minutes.")
        if start.weekday() not in self.open_days:
            problems.append("This campus does not accept bookings on that day of the week.")
        if start.time() < self.open_time or end.time() > self.close_time or end.date() != start.date():
            problems.append(f"Bookings must fall between {self.open_time:%H:%M} and {self.close_time:%H:%M}.")
        if start <= now:
            problems.append("The start time must be in the future.")
        limit = self.advance_limit_days(resource_type, purpose)
        if start > now + timedelta(days=limit):
            problems.append(f"This booking is more than {limit} days ahead (limit for this type: {limit}).")
        problems.extend(self.extra_violations(start, duration_min, resource_type, purpose))
        return problems

    @abstractmethod
    def extra_violations(self, start, duration_min, resource_type, purpose):
        """Campus specific rules."""


@register_policy("johannesburg")
class JohannesburgPolicy(BookingPolicy):
    """Restricted hours rule: weekdays only, no lab sessions after 16:00."""
    max_minutes = 180
    open_time, close_time = time(7, 0), time(18, 0)

    def extra_description(self):
        return "; computer labs end by 16:00"

    def extra_violations(self, start, duration_min, resource_type, purpose):
        end = start + timedelta(minutes=duration_min)
        if resource_type == "Computer Lab" and end.time() > time(16, 0):
            return ["Computer labs on this campus must finish by 16:00 (maintenance window)."]
        return []


@register_policy("centurion")
class CenturionPolicy(BookingPolicy):
    """Centurion campus policy: standard hours, weekdays only."""
    max_minutes = 180
    open_time, close_time = time(7, 0), time(18, 0)
    open_days = frozenset({0, 1, 2, 3, 4})
    standard_advance_days = 30

    def extra_violations(self, start, duration_min, resource_type, purpose):
        return []


@register_policy("durban")
class DurbanPolicy(BookingPolicy):
    """Short session rule: 2 hour cap, Monday to Saturday."""
    max_minutes = 120
    open_time, close_time = time(8, 0), time(17, 0)
    open_days = frozenset({0, 1, 2, 3, 4, 5})
    standard_advance_days = 14

    def extra_violations(self, start, duration_min, resource_type, purpose):
        if start.weekday() == 5 and resource_type == "Seminar Room":
            return ["Seminar rooms are closed on Saturdays."]
        return []


@register_policy("cape_town")
class CapeTownPolicy(BookingPolicy):
    """Priority access rule: assessments may book computer labs 60 days ahead."""
    max_minutes = 240
    open_time, close_time = time(7, 0), time(21, 0)
    open_days = frozenset(range(7))
    standard_advance_days = 21

    def extra_description(self):
        return "; PRIORITY: Assessment bookings may reserve labs up to 60 days ahead"

    def advance_limit_days(self, resource_type, purpose):
        if purpose == "Assessment" and resource_type == "Computer Lab":
            return 60
        return self.standard_advance_days

    def extra_violations(self, start, duration_min, resource_type, purpose):
        return []


def policy_for(key):
    try:
        return POLICY_REGISTRY[key]()
    except KeyError as exc:
        raise ValueError(f"No booking policy registered under '{key}'.") from exc