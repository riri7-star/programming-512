"""Entry point:  python main.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from db import Database
from gui import App
from seed import seed


def main():
    db = Database(os.path.join(HERE, "smart_campus.db"))
    seed(db)                      # no-op when data already exists
    App(db).mainloop()


if __name__ == "__main__":
    main()
