"""Domain model: users and roles (OOP), plus small value objects."""
from dataclasses import dataclass


class PermissionDenied(Exception):
    pass


class User:
    """Base class for every account. Role behaviour comes from subclasses."""
    role = "user"
    permissions = frozenset()

    def __init__(self, user_id, username, full_name, campus_id=None):
        self._id = user_id            # encapsulated: exposed read-only through properties
        self._username = username
        self._full_name = full_name
        self._campus_id = campus_id

    id = property(lambda self: self._id)
    username = property(lambda self: self._username)
    full_name = property(lambda self: self._full_name)
    campus_id = property(lambda self: self._campus_id)

    def can(self, permission):
        return permission in self.permissions

    def require(self, permission):
        if not self.can(permission):
            raise PermissionDenied(f"{self.role} accounts may not perform '{permission}'.")

    @property
    def can_switch_campus(self):
        return True

    def __repr__(self):
        return f"<{self.__class__.__name__} {self._username}>"


class Lecturer(User):
    role = "lecturer"
    permissions = frozenset({"book", "view_own_bookings", "cancel_own_booking", "view_resources"})


class CampusAdministrator(User):
    role = "admin"
    permissions = frozenset({"manage_resources", "view_campus_bookings", "view_usage", "view_resources"})

    @property
    def can_switch_campus(self):
        return False  # locked to the home campus


class SystemOperator(User):
    role = "operator"
    permissions = frozenset({"view_all", "view_campus_bookings", "view_usage", "view_resources",
                             "comparative_reports"})


ROLE_CLASSES = {c.role: c for c in (Lecturer, CampusAdministrator, SystemOperator)}


def build_user(row):
    """Factory: database row -> correct subclass."""
    return ROLE_CLASSES[row["role"]](row["id"], row["username"], row["full_name"], row["campus_id"])


@dataclass(frozen=True)
class Campus:
    id: int
    name: str
    policy_key: str


@dataclass(frozen=True)
class Resource:
    id: int
    code: str
    name: str
    type: str
    capacity: int
    campus_id: int
    active: bool = True


RESOURCE_TYPES = ("Computer Lab", "Projector", "Seminar Room", "Presentation Equipment")
PURPOSES = ("Teaching", "Assessment", "Event", "Presentation")
