"""
src/scheduler/timetable_scheduler.py

Final ready-to-paste scheduler.
- deterministic lab-first placement (reduce unscheduled labs)
- greedy main pass (electives/minors/cores)
- salvage pass that re-tries unscheduled sessions (Option C)
- only forbids repeated LECTURE of same course on same day
- preserves rooms/faculty/student conflict checks
- sorted output: day order + chronological slot order
"""

import random
import math
import pandas as pd
from collections import defaultdict
from copy import deepcopy

# ------------------- time helpers -------------------
def time_to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def slot_to_range(slot):
    # "HH:MM-HH:MM"
    start, end = slot.split("-")
    return time_to_min(start), time_to_min(end)

def ranges_overlap(a, b):
    # a=(s1,e1), b=(s2,e2)
    return not (a[1] <= b[0] or b[1] <= a[0])


# ------------------- scheduler -------------------
class TimetableScheduler:
    def __init__(self, config, seed=None):
        self.config = config
        self.days = config.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])

        # read slot pools from config (expected tuples list)
        self.lecture_slots = [f"{s[0]}-{s[1]}" for s in config.get("lecture_slots", [])]
        self.tutorial_slots = [f"{s[0]}-{s[1]}" for s in config.get("tutorial_slots", [])]
        self.lab_slots = [f"{s[0]}-{s[1]}" for s in config.get("lab_slots", [])]
        self.minor_slots = [f"{s[0]}-{s[1]}" for s in config.get("minor_slots", [])]

        # durations (minutes)
        self.durations = {"Lecture": 90, "Tutorial": 60, "Lab": 120}

        # ordered slots for pretty output sorted by start time
        def start_minutes(slot):
            start, _ = slot.split("-")
            h, m = map(int, start.split(":"))
            return h * 60 + m

        self.ordered_slots = sorted(
            (self.lecture_slots + self.tutorial_slots + self.lab_slots + self.minor_slots),
            key=start_minutes
        )
        self.slot_index = {s: i for i, s in enumerate(self.ordered_slots)}
        self.day_index = {d: i for i, d in enumerate(self.days)}

        if seed is not None:
            random.seed(seed)

    # ---------- normalization/helpers ----------
    def _normalize_classrooms(self, classrooms_list):
        normalized = []
        for r in (classrooms_list or []):
            if not isinstance(r, dict):
                continue
            name = r.get("Room no") or r.get("Room Number") or r.get("Room") or r.get("name")
            cap = r.get("Capacity") or r.get("capacity") or r.get("Cap") or 0
            typ = r.get("Type") or r.get("type") or "Classroom"
            try:
                cap = int(cap)
            except Exception:
                cap = 0
            normalized.append({"name": str(name).strip(), "capacity": cap, "type": str(typ)})
        return normalized

    def _to_int(self, v, default=0):
        try:
            return int(float(v))
        except Exception:
            return default

    def _parse_ltpsc(self, ltpsc):
        """
        Returns L_hours, T_hours, P_hours as integers
        (LTPSC fields are HOURS per week)
        """
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

    def _slots_needed(self, L_hours, T_hours, P_hours):
        lec_slots = math.ceil((L_hours * 60) / self.durations["Lecture"]) if L_hours > 0 else 0
        tut_slots = math.ceil((T_hours * 60) / self.durations["Tutorial"]) if T_hours > 0 else 0
        lab_slots = math.ceil((P_hours * 60) / self.durations["Lab"]) if P_hours > 0 else 0
        return lec_slots, tut_slots, lab_slots

    # ---------- booking helpers ----------
    def _init_bookings(self, classrooms):
        bookings = {d: [] for d in self.days}        # list of booking dicts by day
        rooms_state = {r["name"]: [] for r in classrooms}
        return bookings, rooms_state

    def _room_free(self, room_bookings_for_day, cand_range):
        for br in room_bookings_for_day:
            if ranges_overlap(br['range'], cand_range):
                return False
        return True

    def _faculty_free(self, bookings_for_day, fac, cand_range):
        if not fac:
            return True
        for br in bookings_for_day:
            if br['faculty'] == fac and ranges_overlap(br['range'], cand_range):
                return False
        return True

    def _students_free(self, student_bookings_for_day, cand_range):
        # student_bookings_for_day: list of (s,e)
        for rng in student_bookings_for_day:
            if ranges_overlap(rng, cand_range):
                return False
        return True

    def _choose_room_for_session(self, classrooms, rooms_state, day, cand_range, is_lab, strength, rooms_already_used=None):
        """
        Choose a room that fits & free. rooms_already_used is a set (avoid scheduling multiple sessions
        of different electives into same room in grouped elective placement).
        If no dedicated lab room fits a lab session, fall back to any large enough non-lab room.
        """
        if rooms_already_used is None:
            rooms_already_used = set()

        candidates = []
        for r in classrooms:
            if r["name"] in rooms_already_used:
                continue
            if r["capacity"] < strength:
                continue
            if is_lab and "lab" not in r["type"].lower():
                continue
            bookings_for_room = [b for b in rooms_state.get(r["name"], []) if b['day'] == day]
            if self._room_free(bookings_for_room, cand_range):
                candidates.append(r)
        if not candidates:
            # fallback: if this is a lab and no lab rooms available, allow any room that fits (classrooms)
            if is_lab:
                for r in classrooms:
                    if r["name"] in rooms_already_used:
                        continue
                    if r["capacity"] < strength:
                        continue
                    bookings_for_room = [b for b in rooms_state.get(r["name"], []) if b['day'] == day]
                    if self._room_free(bookings_for_room, cand_range):
                        candidates.append(r)
        if not candidates:
            return None
        candidates.sort(key=lambda x: x["capacity"])
        return candidates[0]

    def _add_booking(self, bookings, rooms_state, day, slot, rng, room_name, faculty, branch, sem, course, session_type):
        entry = {'slot': slot, 'range': rng, 'room': room_name, 'faculty': faculty,
                 'branch': branch, 'sem': sem, 'course': course, 'type': session_type, 'day': day}
        bookings[day].append(entry)
        rooms_state.setdefault(room_name, []).append(entry)

    def _same_course_same_day_conflict(self, bookings, day, branch, sem, code, session_type):
        """
        Lecture sessions cannot repeat same day for same course.
        Tutorials and Labs are allowed on the lecture's day.
        """
        sem = str(int(sem))
        todays = [b for b in bookings[day] if b["branch"] == branch and b["sem"] == sem and b["course"] == code]
        if session_type == "Lecture":
            return any(b["type"] == "Lecture" for b in todays)
        return False

    # ---------- export ----------
    def export_per_branch_sem(self, timetable_dict, output_dir="timetable_outputs"):
        import os
        os.makedirs(output_dir, exist_ok=True)
        for branch in timetable_dict:
            branch_dir = os.path.join(output_dir, branch)
            os.makedirs(branch_dir, exist_ok=True)
            for sem in timetable_dict[branch]:
                rows = timetable_dict[branch][sem]
                df = pd.DataFrame(rows)
                path = os.path.join(branch_dir, f"Sem{sem}.csv")
                df.to_csv(path, index=False, encoding="utf-8")
                print(f"Saved {path}")

    # ---------- Salvage helper ----------
    def _salvage_unscheduled(self, unscheduled_list, bookings, rooms_state, student_bookings, course_day_presence, classrooms, branch_name, sem):
        """
        Try to place each unscheduled session by checking all days -> slots -> rooms of matching pool.
        Returns (placed_rows, remaining_unscheduled_list).
        """
        placed_rows = []
        still_unscheduled = []

        pool_map = {
            "Lecture": (self.lecture_slots, self.durations["Lecture"]),
            "Tutorial": (self.tutorial_slots, self.durations["Tutorial"]),
            "Lab": (self.lab_slots, self.durations["Lab"]),
            "Minor": (self.minor_slots, None)
        }

        for s in unscheduled_list:
            code = s["code"]
            title = s["title"]
            session_type = s["session_type"]
            faculty = s["faculty"]
            strength = s["strength"]

            slot_pool, expected_dur = pool_map.get(session_type, ([], None))
            placed = False

            # deterministic try order: days in configured order, slots in natural order
            for day in self.days:
                if placed:
                    break
                for slot in slot_pool:
                    rng = slot_to_range(slot)
                    if expected_dur is not None and abs((rng[1] - rng[0]) - expected_dur) > 5:
                        continue
                    if not self._students_free(student_bookings[branch_name][str(int(sem))][day], rng):
                        continue
                    if self._same_course_same_day_conflict(bookings, day, branch_name, str(int(sem)), code, session_type):
                        continue
                    if not self._faculty_free(bookings[day], faculty, rng):
                        continue
                    is_lab = (session_type == "Lab")
                    room = self._choose_room_for_session(classrooms, rooms_state, day, rng, is_lab, strength, rooms_already_used=None)
                    if not room:
                        continue
                    # place it
                    self._add_booking(bookings, rooms_state, day, slot, rng, room['name'], faculty, branch_name, str(int(sem)), code, session_type)
                    student_bookings[branch_name][str(int(sem))][day].append(rng)
                    course_day_presence[branch_name][str(int(sem))][day].add(code)
                    placed_rows.append({"Day": day, "Slot": slot, "Course": f"{code} - {title} ({session_type})", "Faculty": faculty, "Room": room['name'], "code": code, "title": title, "session_type": session_type, "strength": strength})
                    placed = True
                    break
                if placed:
                    break

            if not placed:
                still_unscheduled.append(s)

        return placed_rows, still_unscheduled

    # ---------- main algorithm ----------
    def generate_all(self, courses_df_or_path, classrooms_list=None, seed=None):
        if seed is not None:
            random.seed(seed)

        # load dataframe
        if isinstance(courses_df_or_path, str):
            df = pd.read_csv(courses_df_or_path)
        elif isinstance(courses_df_or_path, pd.DataFrame):
            df = courses_df_or_path.copy()
        else:
            raise ValueError("courses_df_or_path must be DataFrame or CSV path")

        df.columns = [c.strip() for c in df.columns]
        rename_map = {}
        for c in df.columns:
            low = c.lower()
            if low in ("course code", "code"): rename_map[c] = "Course Code"
            if low in ("course title", "course name", "title", "name"): rename_map[c] = "Course Title"
            if low in ("department", "dept", "branch"): rename_map[c] = "Department"
            if low in ("semester", "sem"): rename_map[c] = "Semester"
            if low in ("ltpsc", "l-t-p-s-c"): rename_map[c] = "LTPSC"
            if low in ("faculty", "teacher", "lecturer"): rename_map[c] = "Faculty"
            if low in ("strength", "capacity", "students"): rename_map[c] = "Strength"
            if low in ("type", "course type"): rename_map[c] = "Type"
            if low in ("section",): rename_map[c] = "Section"
        if rename_map:
            df = df.rename(columns=rename_map)

        for c in ["Course Code", "Course Title", "Department", "Semester", "LTPSC", "Faculty", "Strength", "Type"]:
            if c not in df.columns:
                df[c] = ""

        # normalize department names
        def normalize_dept(raw):
            s = str(raw).strip().upper()
            if "CSE" in s:
                return "CSE"
            if "DSAI" in s or "DATA SCIENCE" in s:
                return "DSAI"
            if "ECE" in s:
                return "ECE"
            if s == "ALL":
                return "ALL"
            return s or "UNKNOWN"
        df["Dept_canonical"] = df["Department"].apply(normalize_dept)
        if "Section" not in df.columns:
            df["Section"] = ""
        df["Semester"] = df["Semester"].apply(lambda x: self._to_int(x, 0))

        # prepare classrooms
        if isinstance(classrooms_list, pd.DataFrame):
            classrooms = classrooms_list.to_dict(orient="records")
        else:
            classrooms = classrooms_list or []
        classrooms = self._normalize_classrooms(classrooms)
        if not classrooms:
            classrooms = [{"name": "C004", "capacity": 300, "type": "Classroom"}]

        bookings, rooms_state = self._init_bookings(classrooms)
        student_bookings = defaultdict(lambda: defaultdict(lambda: {d: [] for d in self.days}))
        course_day_presence = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))

        result = {}

        for dept in sorted(df["Dept_canonical"].unique()):
            if dept == "UNKNOWN":
                continue
            dept_rows = df[df["Dept_canonical"] == dept].copy()
            target_branches = ["CSE-A", "CSE-B"] if dept == "CSE" else [dept]

            for sem in sorted(dept_rows["Semester"].dropna().unique()):
                sem_rows = dept_rows[dept_rows["Semester"] == sem].copy()

                combined_mask = sem_rows["Section"].astype(str).str.upper().str.contains("COMBINED|ALL") | sem_rows["Department"].astype(str).str.upper().str.contains("COMBINED|ALL")
                combined_rows = sem_rows[combined_mask]
                separate_rows = sem_rows[~combined_mask]

                per_branch_rows = {b: pd.DataFrame(columns=sem_rows.columns) for b in target_branches}

                # distribute separate rows (use pd.concat)
                for _, row in separate_rows.iterrows():
                    sec = str(row.get("Section", "")).strip().upper()
                    if sec == "A" and "CSE-A" in per_branch_rows:
                        per_branch_rows["CSE-A"] = pd.concat([per_branch_rows["CSE-A"], pd.DataFrame([row])], ignore_index=True)
                    elif sec == "B" and "CSE-B" in per_branch_rows:
                        per_branch_rows["CSE-B"] = pd.concat([per_branch_rows["CSE-B"], pd.DataFrame([row])], ignore_index=True)
                    else:
                        for b in per_branch_rows:
                            per_branch_rows[b] = pd.concat([per_branch_rows[b], pd.DataFrame([row])], ignore_index=True)

                # combined rows go to all branches
                for _, row in combined_rows.iterrows():
                    for b in per_branch_rows:
                        per_branch_rows[b] = pd.concat([per_branch_rows[b], pd.DataFrame([row])], ignore_index=True)

                # schedule per branch
                for branch_name, branch_df in per_branch_rows.items():
                    result.setdefault(branch_name, {})
                    timetable_rows = []

                    branch_df["Type_norm"] = branch_df["Type"].astype(str).str.strip().str.lower()
                    electives = branch_df[branch_df["Type_norm"] == "elective"].copy()
                    minors = branch_df[branch_df["Type_norm"] == "minor"].copy()
                    cores = branch_df[~branch_df["Type_norm"].isin(["elective", "minor"])].copy()

                    student_bookings[branch_name].setdefault(str(int(sem)), {d: [] for d in self.days})

                    # PHASE 1: CORE LABS  -- deterministic order to avoid starvation
                    core_lab_rows = []
                    for _, row in cores.iterrows():
                        L_hours, T_hours, P_hours = self._parse_ltpsc(row.get("LTPSC", ""))
                        lab_slots_needed = math.ceil((P_hours * 60) / self.durations["Lab"]) if P_hours > 0 else 0
                        for _ in range(lab_slots_needed):
                            core_lab_rows.append({
                                'code': row.get("Course Code", ""), 'title': row.get("Course Title", ""),
                                'faculty': str(row.get("Faculty", "")).strip(), 'strength': self._to_int(row.get("Strength", 0)),
                                'type': 'Lab'
                            })

                    # deterministic iteration (days in order, slots in order)
                    for lab in core_lab_rows:
                        placed = False
                        for day in self.days:
                            if placed:
                                break
                            for slot in self.lab_slots:
                                rng = slot_to_range(slot)
                                if abs((rng[1] - rng[0]) - self.durations['Lab']) > 5:
                                    continue
                                if not self._students_free(student_bookings[branch_name][str(int(sem))][day], rng):
                                    continue
                                if not self._faculty_free(bookings[day], lab['faculty'], rng):
                                    continue
                                room = self._choose_room_for_session(classrooms, rooms_state, day, rng, True, lab['strength'])
                                if not room:
                                    continue
                                # commit
                                self._add_booking(bookings, rooms_state, day, slot, rng, room['name'], lab['faculty'], branch_name, str(int(sem)), lab['code'], 'Lab')
                                student_bookings[branch_name][str(int(sem))][day].append(rng)
                                course_day_presence[branch_name][str(int(sem))][day].add(lab['code'])
                                timetable_rows.append({"Day": day, "Slot": slot, "Course": f"{lab['code']} - {lab['title']} (Lab)", "Faculty": lab['faculty'], "Room": room['name'], "code": lab['code'], "title": lab['title'], "session_type": "Lab", "strength": lab['strength']})
                                placed = True
                                break
                        if not placed:
                            timetable_rows.append({"Day": "UNSCHEDULED", "Slot": "N/A", "Course": f"{lab['code']} - {lab['title']} (Lab)", "Faculty": lab['faculty'], "Room": "N/A", "code": lab['code'], "title": lab['title'], "session_type": "Lab", "strength": lab['strength']})

                    # PHASE 2: ELECTIVES (grouped) - keep grouped placement
                    if not electives.empty:
                        elective_info = []
                        maxLslots = maxTslots = 0
                        for _, r in electives.iterrows():
                            L_hours, T_hours, P_hours = self._parse_ltpsc(r.get("LTPSC", ""))
                            L_slots = math.ceil((L_hours * 60) / self.durations["Lecture"]) if L_hours > 0 else 0
                            T_slots = math.ceil((T_hours * 60) / self.durations["Tutorial"]) if T_hours > 0 else 0
                            elective_info.append({'code': r.get("Course Code", ""), 'title': r.get("Course Title", ""),
                                                  'faculty': str(r.get("Faculty", "")).strip(), 'strength': self._to_int(r.get("Strength", 0)),
                                                  'L_slots': L_slots, 'T_slots': T_slots})
                            maxLslots = max(maxLslots, L_slots)
                            maxTslots = max(maxTslots, T_slots)

                        # group lecture indices
                        for i in range(1, maxLslots + 1):
                            needs = [e for e in elective_info if e['L_slots'] >= i]
                            if not needs:
                                continue
                            placed_group = False
                            days_shuf = self.days[:]; random.shuffle(days_shuf)
                            for day in days_shuf:
                                for slot in self.lecture_slots:
                                    rng = slot_to_range(slot)
                                    if abs((rng[1] - rng[0]) - self.durations['Lecture']) > 5:
                                        continue
                                    if not self._students_free(student_bookings[branch_name][str(int(sem))][day], rng):
                                        continue
                                    rooms_used_now = set()
                                    local_assign = []
                                    conflict = False
                                    for e in needs:
                                        if self._same_course_same_day_conflict(bookings, day, branch_name, str(int(sem)), e['code'], "Lecture"):
                                            conflict = True; break
                                        if not self._faculty_free(bookings[day], e['faculty'], rng):
                                            conflict = True; break
                                        room = self._choose_room_for_session(classrooms, rooms_state, day, rng, False, e['strength'], rooms_used_now)
                                        if not room:
                                            conflict = True; break
                                        rooms_used_now.add(room['name'])
                                        local_assign.append((e, room['name']))
                                    if conflict:
                                        continue
                                    for e, room_name in local_assign:
                                        self._add_booking(bookings, rooms_state, day, slot, rng, room_name, e['faculty'], branch_name, str(int(sem)), e['code'], 'Elective-Lecture')
                                        timetable_rows.append({"Day": day, "Slot": slot, "Course": f"{e['code']} - {e['title']} (Elective Lecture {i})", "Faculty": e['faculty'], "Room": room_name, "code": e['code'], "title": e['title'], "session_type": "Lecture", "strength": e['strength']})
                                        course_day_presence[branch_name][str(int(sem))][day].add(e['code'])
                                    student_bookings[branch_name][str(int(sem))][day].append(rng)
                                    placed_group = True
                                    break
                                if placed_group:
                                    break
                            if not placed_group:
                                for e in needs:
                                    timetable_rows.append({"Day": "UNSCHEDULED", "Slot": "N/A", "Course": f"{e['code']} - {e['title']} (Elective Lecture {i})", "Faculty": e['faculty'], "Room": "N/A", "code": e['code'], "title": e['title'], "session_type": "Lecture", "strength": e['strength']})

                        # tutorial indices
                        for j in range(1, maxTslots + 1):
                            needs = [e for e in elective_info if e['T_slots'] >= j]
                            if not needs:
                                continue
                            placed_group = False
                            days_shuf = self.days[:]; random.shuffle(days_shuf)
                            for day in days_shuf:
                                for slot in self.tutorial_slots:
                                    rng = slot_to_range(slot)
                                    if abs((rng[1] - rng[0]) - self.durations['Tutorial']) > 5:
                                        continue
                                    if not self._students_free(student_bookings[branch_name][str(int(sem))][day], rng):
                                        continue
                                    rooms_used_now = set()
                                    local_assign = []
                                    conflict = False
                                    for e in needs:
                                        if not self._faculty_free(bookings[day], e['faculty'], rng):
                                            conflict = True; break
                                        room = self._choose_room_for_session(classrooms, rooms_state, day, rng, False, e['strength'], rooms_used_now)
                                        if not room:
                                            conflict = True; break
                                        rooms_used_now.add(room['name'])
                                        local_assign.append((e, room['name']))
                                    if conflict:
                                        continue
                                    for e, room_name in local_assign:
                                        self._add_booking(bookings, rooms_state, day, slot, rng, room_name, e['faculty'], branch_name, str(int(sem)), e['code'], 'Elective-Tutorial')
                                        timetable_rows.append({"Day": day, "Slot": slot, "Course": f"{e['code']} - {e['title']} (Elective Tutorial {j})", "Faculty": e['faculty'], "Room": room_name, "code": e['code'], "title": e['title'], "session_type": "Tutorial", "strength": e['strength']})
                                        course_day_presence[branch_name][str(int(sem))][day].add(e['code'])
                                    student_bookings[branch_name][str(int(sem))][day].append(rng)
                                    placed_group = True
                                    break
                                if placed_group:
                                    break
                            if not placed_group:
                                for e in needs:
                                    timetable_rows.append({"Day": "UNSCHEDULED", "Slot": "N/A", "Course": f"{e['code']} - {e['title']} (Elective Tutorial {j})", "Faculty": e['faculty'], "Room": "N/A", "code": e['code'], "title": e['title'], "session_type": "Tutorial", "strength": e['strength']})

                    # PHASE 3: MINORS (grouped)
                    if not minors.empty:
                        placed_minor = False
                        for minor_slot in self.minor_slots:
                            rng = slot_to_range(minor_slot)
                            days_shuf = self.days[:]; random.shuffle(days_shuf)
                            for day in days_shuf:
                                if not self._students_free(student_bookings[branch_name][str(int(sem))][day], rng):
                                    continue
                                rooms_used_now = set()
                                local_assign = []
                                conflict = False
                                for _, r in minors.iterrows():
                                    fac = str(r.get("Faculty", "")).strip()
                                    strength = self._to_int(r.get("Strength", 0))
                                    if not self._faculty_free(bookings[day], fac, rng):
                                        conflict = True; break
                                    room = self._choose_room_for_session(classrooms, rooms_state, day, rng, False, strength, rooms_used_now)
                                    if not room:
                                        conflict = True; break
                                    rooms_used_now.add(room['name'])
                                    local_assign.append((r, room['name']))
                                if conflict:
                                    continue
                                for r, room_name in local_assign:
                                    code = r.get("Course Code", ""); title = r.get("Course Title", ""); fac = str(r.get("Faculty", "")).strip()
                                    self._add_booking(bookings, rooms_state, day, minor_slot, rng, room_name, fac, branch_name, str(int(sem)), code, 'Minor')
                                    timetable_rows.append({"Day": day, "Slot": minor_slot, "Course": f"{code} - {title} (Minor)", "Faculty": fac, "Room": room_name, "code": code, "title": title, "session_type": "Minor", "strength": self._to_int(r.get("Strength", 0))})
                                    course_day_presence[branch_name][str(int(sem))][day].add(code)
                                student_bookings[branch_name][str(int(sem))][day].append(rng)
                                placed_minor = True
                                break
                            if placed_minor:
                                break
                        if not placed_minor:
                            for _, r in minors.iterrows():
                                timetable_rows.append({"Day": "UNSCHEDULED", "Slot": "N/A", "Course": f"{r.get('Course Code','')} - {r.get('Course Title','')} (Minor)", "Faculty": r.get("Faculty",""), "Room": "N/A", "code": r.get("Course Code",""), "title": r.get("Course Title",""), "session_type": "Minor", "strength": self._to_int(r.get("Strength", 0))})

                    # PHASE 4: CORE LECTURES (hours -> slots)
                    core_lectures = []
                    core_tutorials = []
                    for _, row in cores.iterrows():
                        L_hours, T_hours, P_hours = self._parse_ltpsc(row.get("LTPSC", ""))
                        L_slots = math.ceil((L_hours * 60) / self.durations["Lecture"]) if L_hours > 0 else 0
                        T_slots = math.ceil((T_hours * 60) / self.durations["Tutorial"]) if T_hours > 0 else 0
                        for _ in range(L_slots):
                            core_lectures.append({'code': row.get("Course Code", ""), 'title': row.get("Course Title", ""), 'faculty': str(row.get("Faculty", "")).strip(), 'strength': self._to_int(row.get("Strength", 0))})
                        for _ in range(T_slots):
                            core_tutorials.append({'code': row.get("Course Code", ""), 'title': row.get("Course Title", ""), 'faculty': str(row.get("Faculty", "")).strip(), 'strength': self._to_int(row.get("Strength", 0))})

                    random.shuffle(core_lectures)
                    for lec in core_lectures:
                        placed = False
                        days_shuf = self.days[:]; random.shuffle(days_shuf)
                        for day in days_shuf:
                            for slot in self.lecture_slots:
                                rng = slot_to_range(slot)
                                if abs((rng[1] - rng[0]) - self.durations['Lecture']) > 5:
                                    continue
                                if not self._students_free(student_bookings[branch_name][str(int(sem))][day], rng):
                                    continue
                                if self._same_course_same_day_conflict(bookings, day, branch_name, str(int(sem)), lec['code'], "Lecture"):
                                    continue
                                if not self._faculty_free(bookings[day], lec['faculty'], rng):
                                    continue
                                room = self._choose_room_for_session(classrooms, rooms_state, day, rng, False, lec['strength'])
                                if not room:
                                    continue
                                # commit
                                self._add_booking(bookings, rooms_state, day, slot, rng, room['name'], lec['faculty'], branch_name, str(int(sem)), lec['code'], 'Lecture')
                                timetable_rows.append({"Day": day, "Slot": slot, "Course": f"{lec['code']} - {lec['title']} (Lecture)", "Faculty": lec['faculty'], "Room": room['name'], "code": lec['code'], "title": lec['title'], "session_type": "Lecture", "strength": lec['strength']})
                                student_bookings[branch_name][str(int(sem))][day].append(rng)
                                course_day_presence[branch_name][str(int(sem))][day].add(lec['code'])
                                placed = True
                                break
                            if placed:
                                break
                        if not placed:
                            timetable_rows.append({"Day":"UNSCHEDULED","Slot":"N/A","Course":f"{lec['code']} - {lec['title']} (Lecture)","Faculty":lec['faculty'],"Room":"N/A","code":lec['code'],"title":lec['title'],"session_type":"Lecture","strength":lec['strength']})

                    # PHASE 5: CORE TUTORIALS
                    random.shuffle(core_tutorials)
                    for tut in core_tutorials:
                        placed = False
                        days_shuf = self.days[:]; random.shuffle(days_shuf)
                        for day in days_shuf:
                            for slot in self.tutorial_slots:
                                rng = slot_to_range(slot)
                                if abs((rng[1] - rng[0]) - self.durations['Tutorial']) > 5:
                                    continue
                                if not self._students_free(student_bookings[branch_name][str(int(sem))][day], rng):
                                    continue
                                if not self._faculty_free(bookings[day], tut['faculty'], rng):
                                    continue
                                room = self._choose_room_for_session(classrooms, rooms_state, day, rng, False, tut['strength'])
                                if not room:
                                    continue
                                # commit
                                self._add_booking(bookings, rooms_state, day, slot, rng, room['name'], tut['faculty'], branch_name, str(int(sem)), tut['code'], 'Tutorial')
                                timetable_rows.append({"Day": day, "Slot": slot, "Course": f"{tut['code']} - {tut['title']} (Tutorial)", "Faculty": tut['faculty'], "Room": room['name'], "code": tut['code'], "title": tut['title'], "session_type": "Tutorial", "strength": tut['strength']})
                                student_bookings[branch_name][str(int(sem))][day].append(rng)
                                course_day_presence[branch_name][str(int(sem))][day].add(tut['code'])
                                placed = True
                                break
                            if placed:
                                break
                        if not placed:
                            timetable_rows.append({"Day":"UNSCHEDULED","Slot":"N/A","Course":f"{tut['code']} - {tut['title']} (Tutorial)","Faculty":tut['faculty'],"Room":"N/A","code":tut['code'],"title":tut['title'],"session_type":"Tutorial","strength":tut['strength']})

                    # ---------------- SALVAGE PASS ----------------
                    unscheduled_items = [r for r in timetable_rows if r.get("Day") == "UNSCHEDULED"]
                    timetable_rows = [r for r in timetable_rows if r.get("Day") != "UNSCHEDULED"]

                    salvage_list = []
                    for u in unscheduled_items:
                        code = u.get("code") or (str(u.get("Course","")).split(" - ")[0] if u.get("Course") else "")
                        # attempt to extract title more robustly
                        title = u.get("title")
                        if not title:
                            try:
                                title = str(u.get("Course","")).split(" - ", 1)[1]
                            except Exception:
                                title = u.get("Course","")
                        sess = u.get("session_type") or ("Lecture" if "Lecture" in str(u.get("Course","")) else ("Lab" if "Lab" in str(u.get("Course","")) else ("Tutorial" if "Tutorial" in str(u.get("Course","")) else "Lecture")))
                        salvage_list.append({
                            "code": code,
                            "title": title,
                            "session_type": sess,
                            "faculty": u.get("Faculty",""),
                            "strength": self._to_int(u.get("strength", u.get("Strength", 0)))
                        })

                    placed_rows, remaining = self._salvage_unscheduled(salvage_list, bookings, rooms_state, student_bookings, course_day_presence, classrooms, branch_name, sem)

                    # add placed
                    timetable_rows.extend(placed_rows)

                    # leftover -> keep as UNSCHEDULED entries
                    for r in remaining:
                        timetable_rows.append({"Day":"UNSCHEDULED","Slot":"N/A","Course":f"{r['code']} - {r['title']} ({r['session_type']})","Faculty":r.get("faculty",""),"Room":"N/A","code":r['code'],"title":r['title'],"session_type":r['session_type'],"strength":r['strength']})

                    # final sort: day order then chronological slot order; use .get("Slot","") to be robust
                    timetable_rows.sort(key=lambda r: (self.day_index.get(r.get("Day"), 999), self.slot_index.get(r.get("Slot",""), 999), r.get("Course","")))
                    result[branch_name][str(int(sem))] = timetable_rows

        return result
