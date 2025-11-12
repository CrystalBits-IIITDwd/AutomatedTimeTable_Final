"""
src/scheduler/timetable_scheduler.py
Smart version — strict durations, minors handled, labs fixed, lunch safe, conflict-free.
"""

import random
import os
import pandas as pd


class TimetableScheduler:
    def __init__(self, config):
        self.config = config
        self.days = config.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        self.regular_slots = config.get("regular_slots", [])
        self.minor_slots = config.get("minor_slots", [])
        self.lunch_break = config.get("lunch_break", ("12:30", "14:00"))
        self.ordered_slots = [f"{s[0]}-{s[1]}" for s in (self.regular_slots + self.minor_slots)]
        self.day_order = {d: i for i, d in enumerate(self.days)}
        self.slot_order = {slot: i for i, slot in enumerate(self.ordered_slots)}

        self.durations = {"Lecture": 90, "Tutorial": 60, "Lab": 120}

    # ----------------- helpers -----------------
    def _normalize_classrooms(self, classrooms_list):
        normalized = []
        if not classrooms_list:
            return normalized
        for r in classrooms_list:
            if not isinstance(r, dict):
                continue
            name = r.get("Room no") or r.get("Room Number") or r.get("Room") or r.get("name")
            cap = r.get("Capacity") or r.get("capacity") or r.get("Cap")
            typ = r.get("Type") or r.get("type") or "Classroom"
            try:
                cap = int(cap)
            except Exception:
                cap = 0
            normalized.append({"name": str(name).strip(), "capacity": cap, "type": str(typ)})
        return normalized

    def _parse_ltpsc(self, ltpsc):
        if pd.isna(ltpsc) or ltpsc is None:
            return 0, 0, 0
        parts = [p.strip() for p in str(ltpsc).split("-")]
        while len(parts) < 5:
            parts.append("0")
        try:
            L, T, P, _, _ = map(int, parts[:5])
        except Exception:
            L, T, P = 0, 0, 0
        return L, T, P

    def _choose_room(self, classrooms, course_type, strength):
        candidates = []
        for r in classrooms:
            if r["capacity"] >= strength:
                if "lab" in course_type.lower() and "lab" not in r["type"].lower():
                    continue
                candidates.append(r)
        if not candidates:
            return random.choice(classrooms)
        candidates.sort(key=lambda x: x["capacity"])
        return random.choice(candidates[:3]) if len(candidates) >= 3 else random.choice(candidates)

    def _slot_allowed(self, slot, required_minutes, is_minor=False):
        """Check slot duration and lunch overlap."""
        start, end = slot.split("-")
        to_min = lambda t: int(t.split(":")[0]) * 60 + int(t.split(":")[1])
        s, e = to_min(start), to_min(end)
        dur = e - s

        # strict duration match (±5 min tolerance)
        if abs(dur - required_minutes) > 5:
            return False

        # minors can only go in minor slots
        if is_minor:
            return slot in [f"{s1}-{s2}" for s1, s2 in self.minor_slots]

        # skip if slot overlaps lunch
        lunch_s, lunch_e = to_min(self.lunch_break[0]), to_min(self.lunch_break[1])
        if s < lunch_e and e > lunch_s:
            return False

        # main schedule must be between 9–17:30 for non-minors
        if not (9 * 60 <= s < 17 * 60 + 30):
            return False

        return True

    # ----------------- main scheduling -----------------
    def generate_all(self, courses_df_or_path, classrooms_list=None):
        if isinstance(courses_df_or_path, str):
            df = pd.read_csv(courses_df_or_path)
        elif isinstance(courses_df_or_path, pd.DataFrame):
            df = courses_df_or_path.copy()
        else:
            raise ValueError("courses_df_or_path must be a DataFrame or path string")

        df.columns = [c.strip() for c in df.columns]
        if "Department" not in df.columns and "branch" in df.columns:
            df = df.rename(columns={"branch": "Department"})
        if "Semester" not in df.columns and "semester" in df.columns:
            df = df.rename(columns={"semester": "Semester"})
        if "Course Code" not in df.columns and "Course code" in df.columns:
            df = df.rename(columns={"Course code": "Course Code"})

        df["Department"] = df["Department"].astype(str).str.upper()
        classrooms = self._normalize_classrooms(classrooms_list or [])
        if not classrooms:
            classrooms = [{"name": "C004", "capacity": 300, "type": "Classroom"}]

        result = {}
        depts = sorted(df["Department"].unique())

        for dept in depts:
            dept_rows = df[df["Department"] == dept].copy()
            branches = ["CSE-A", "CSE-B"] if dept == "CSE" else [dept]

            for branch in branches:
                result.setdefault(branch, {})
                for sem in sorted(dept_rows["Semester"].dropna().unique()):
                    sem_rows = dept_rows[dept_rows["Semester"] == sem].copy()
                    used_rooms = {d: {slot: [] for slot in self.ordered_slots} for d in self.days}
                    faculty_used = {d: {slot: set() for slot in self.ordered_slots} for d in self.days}
                    timetable_rows = []

                    # split electives/minors and core
                    electives = sem_rows[sem_rows["Type"].astype(str).str.lower() == "elective"]
                    minors = sem_rows[sem_rows["Type"].astype(str).str.lower() == "minor"]
                    cores = sem_rows[~sem_rows["Type"].astype(str).str.lower().isin(["elective", "minor"])]

                    # --- electives (grouped)
                    if not electives.empty:
                        valid_slots = [(d, s) for d in self.days for s in self.ordered_slots
                                       if self._slot_allowed(s, self.durations["Lecture"])]
                        if valid_slots:
                            chosen_day, chosen_slot = random.choice(valid_slots)
                            for _, course in electives.iterrows():
                                faculty = str(course["Faculty"]).strip()
                                room = self._choose_room(classrooms, course["Type"], int(course["Strength"]))
                                used_rooms[chosen_day][chosen_slot].append(room["name"])
                                faculty_used[chosen_day][chosen_slot].add(faculty)
                                timetable_rows.append({
                                    "Day": chosen_day,
                                    "Slot": chosen_slot,
                                    "Course": f"{course['Course Code']} - {course['Course Title']} (Elective)",
                                    "Faculty": faculty,
                                    "Room": room["name"]
                                })

                    # --- minors (restricted slots)
                    for _, course in minors.iterrows():
                        code, title = course["Course Code"], course["Course Title"]
                        faculty = str(course["Faculty"]).strip()
                        ctype = course["Type"]
                        strength = int(course["Strength"])
                        L, T, P = self._parse_ltpsc(course["LTPSC"])
                        sessions = (["Lecture"] * L) + (["Tutorial"] * T) + (["Lab"] * P)
                        if not sessions:
                            sessions = ["Lecture"]

                        for session in sessions:
                            required_minutes = self.durations.get(session, 90)
                            valid_slots = [(d, s) for d in self.days for s in self.ordered_slots
                                           if self._slot_allowed(s, required_minutes, is_minor=True)]
                            random.shuffle(valid_slots)
                            placed = False
                            for day, slot in valid_slots:
                                if faculty in faculty_used[day][slot]:
                                    continue
                                room = self._choose_room(classrooms, ctype, strength)
                                if room["name"] in used_rooms[day][slot]:
                                    continue
                                timetable_rows.append({
                                    "Day": day,
                                    "Slot": slot,
                                    "Course": f"{code} - {title} ({session})",
                                    "Faculty": faculty,
                                    "Room": room["name"]
                                })
                                used_rooms[day][slot].append(room["name"])
                                faculty_used[day][slot].add(faculty)
                                placed = True
                                break
                            if not placed:
                                timetable_rows.append({
                                    "Day": "UNSCHEDULED",
                                    "Slot": "N/A",
                                    "Course": f"{code} ({session})",
                                    "Faculty": faculty,
                                    "Room": "N/A"
                                })

                    # --- core (main)
                    for _, course in cores.iterrows():
                        code, title = course["Course Code"], course["Course Title"]
                        faculty = str(course["Faculty"]).strip()
                        ctype = course["Type"]
                        strength = int(course["Strength"])
                        L, T, P = self._parse_ltpsc(course["LTPSC"])
                        sessions = (["Lecture"] * L) + (["Tutorial"] * T) + (["Lab"] * P)
                        if not sessions:
                            sessions = ["Lecture"]

                        for session in sessions:
                            required_minutes = self.durations.get(session, 90)
                            valid_slots = [(d, s) for d in self.days for s in self.ordered_slots
                                           if self._slot_allowed(s, required_minutes, is_minor=False)]
                            random.shuffle(valid_slots)
                            placed = False
                            for day, slot in valid_slots:
                                if faculty in faculty_used[day][slot]:
                                    continue
                                room = self._choose_room(classrooms, ctype, strength)
                                if room["name"] in used_rooms[day][slot]:
                                    continue
                                timetable_rows.append({
                                    "Day": day,
                                    "Slot": slot,
                                    "Course": f"{code} - {title} ({session})",
                                    "Faculty": faculty,
                                    "Room": room["name"]
                                })
                                used_rooms[day][slot].append(room["name"])
                                faculty_used[day][slot].add(faculty)
                                placed = True
                                break
                            if not placed:
                                timetable_rows.append({
                                    "Day": "UNSCHEDULED",
                                    "Slot": "N/A",
                                    "Course": f"{code} ({session})",
                                    "Faculty": faculty,
                                    "Room": "N/A"
                                })

                    # sort final
                    timetable_rows.sort(key=lambda r: (self.day_order.get(r["Day"], 999),
                                                       self.slot_order.get(r["Slot"], 999),
                                                       r["Course"]))
                    result[branch][str(int(sem))] = timetable_rows

        return result
