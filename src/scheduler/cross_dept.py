"""
src/scheduler/cross_dept.py
===========================
Shared course synchronization between DSAI and ECE.
"""

import pandas as pd

class CrossDeptManager:
    def __init__(self):
        self.shared = {}  # semester -> {course_code: [slots]}

    def detect_shared_courses(self, df_dsai, df_ece, semester):
        dsai_codes = set(df_dsai[df_dsai['Semester'] == semester]['Course Code'].str.strip())
        ece_codes = set(df_ece[df_ece['Semester'] == semester]['Course Code'].str.strip())
        shared = dsai_codes.intersection(ece_codes)
        return list(shared)

    def register_schedule(self, semester, code, slots):
        if semester not in self.shared:
            self.shared[semester] = {}
        self.shared[semester][code] = slots

    def get_schedule(self, semester, code):
        return self.shared.get(semester, {}).get(code)
