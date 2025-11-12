"""
src/models/timetable.py
=======================
Stores timetable structure and handles CSV export.
"""

import pandas as pd
import os

class Timetable:
    def __init__(self, days, slots):
        self.days = days
        self.slots = [f"{s[0]}-{s[1]}" for s in slots]
        self.grid = {day: {slot: "Free" for slot in self.slots} for day in days}

    def assign(self, day, slot, label):
        self.grid[day][slot] = label

    def to_dataframe(self):
        return pd.DataFrame(self.grid).T

    def export(self, dept, sem, sec, output_dir="timetable_outputs"):
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{dept}_Sem{sem}_Sec{sec}_Timetable.csv"
        path = os.path.join(output_dir, filename)
        df = self.to_dataframe()
        df.to_csv(path, encoding="utf-8")
        print(f"🗂️  Saved: {path}")
