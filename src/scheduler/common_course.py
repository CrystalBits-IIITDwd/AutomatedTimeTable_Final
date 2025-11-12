"""
src/scheduler/common_courses.py
===============================
Handles courses common to multiple sections (CSE A + B).
"""

class CommonCourseManager:
    def __init__(self):
        self.schedule = {}  # dept -> sem -> {code: [(day, slot)]}

    def save(self, dept, sem, code, slots):
        self.schedule.setdefault(dept, {}).setdefault(sem, {})[code] = slots

    def copy(self, dept, sem):
        """Return saved schedule for reuse in Section B."""
        return self.schedule.get(dept, {}).get(sem, {})
