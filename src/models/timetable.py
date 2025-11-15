"""
src/scheduler/timetable_scheduler.py
Smart scheduling: strict slot pools, core-no-collisions for branch+sem,
electives grouped, minors grouped (morning or evening), global room/faculty conflict checks.
"""

import random
import pandas as pd

class TimetableScheduler:
    def __init__(self, config):
        self.config = config
        self.days = config.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])

        # slots separated by session type
        self.lecture_slots = [f"{s[0]}-{s[1]}" for s in config.get("lecture_slots", [])]
        self.tutorial_slots = [f"{s[0]}-{s[1]}" for s in config.get("tutorial_slots", [])]
        self.lab_slots = [f"{s[0]}-{s[1]}" for s in config.get("lab_slots", [])]
        self.minor_slots = [f"{s[0]}-{s[1]}" for s in config.get("minor_slots", [])]

        # combined ordered list for book-keeping (rooms & faculty)
        self.ordered_slots = self.lecture_slots + self.tutorial_slots + self.lab_slots + self.minor_slots

        self.lunch_break = config.get("lunch_break", ("13:15", "14:00"))
        self.day_order = {d: i for i, d in enumerate(self.days)}
        self.slot_order = {slot: i for i, slot in enumerate(self.ordered_slots)}

        # durations (minutes)
        self.durations = {"Lecture": 90, "Tutorial": 60, "Lab": 120}

    # ---------- helpers ----------
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

    def _to_int(self, v, default=0):
        try:
            return int(float(v))
        except Exception:
            return default

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

    def _choose_room(self, classrooms, is_lab, strength):
        # prefer lab rooms for labs; otherwise classroom
        candidates = []
        for r in classrooms:
            if r["capacity"] < strength:
                continue
            if is_lab and "lab" not in r["type"].lower():
                continue
            candidates.append(r)
        if not candidates:
            candidates = [r for r in classrooms if r["capacity"] >= strength]
        if not candidates:
            return {"name": "UNDEF", "capacity": 0, "type": "Classroom"}
        candidates.sort(key=lambda x: x["capacity"])
        return random.choice(candidates[:min(3, len(candidates))])

    def _slot_duration_matches(self, slot, required_minutes):
        try:
            start, end = slot.split("-")
            to_min = lambda t: int(t.split(":")[0]) * 60 + int(t.split(":")[1])
            s, e = to_min(start), to_min(end)
            return abs((e - s) - required_minutes) <= 5
        except Exception:
            return False

    # ---------- main scheduling ----------
    def generate_all(self, courses_df_or_path, classrooms_list=None):
        # read DataFrame or CSV
        if isinstance(courses_df_or_path, str):
            df = pd.read_csv(courses_df_or_path)
        elif isinstance(courses_df_or_path, pd.DataFrame):
            df = courses_df_or_path.copy()
        else:
            raise ValueError("courses_df_or_path must be DataFrame or CSV path")

        df.columns = [c.strip() for c in df.columns]
        # Simple canonicalization (accept common variants)
        rename_map = {}
        for c in df.columns:
            low = c.lower()
            if low in ("course code", "code"):
                rename_map[c] = "Course Code"
            if low in ("course title", "course name", "title", "name"):
                rename_map[c] = "Course Title"
            if low in ("department", "dept", "branch"):
                rename_map[c] = "Department"
            if low in ("semester", "sem"):
                rename_map[c] = "Semester"
            if low in ("ltpsc", "l-t-p-s-c"):
                rename_map[c] = "LTPSC"
            if low in ("faculty", "teacher"):
                rename_map[c] = "Faculty"
            if low in ("strength", "capacity", "students"):
                rename_map[c] = "Strength"
            if low in ("type", "course type"):
                rename_map[c] = "Type"
            if low in ("section",):
                rename_map[c] = "Section"
        if rename_map:
            df = df.rename(columns=rename_map)

        # safe defaults
        for col in ["Course Code", "Course Title", "Department", "Semester", "LTPSC", "Faculty", "Strength", "Type"]:
            if col not in df.columns:
                df[col] = ""

        # normalize dept & section
        def normalize_dept(raw):
            s = str(raw).strip().upper()
            if "CSE" in s:
                # keep as CSE; section parsed separately
                return "CSE"
            if "DSAI" in s or "DATA SCIENCE" in s or "DS-AI" in s:
                return "DSAI"
            if "ECE" in s:
                return "ECE"
            if s == "ALL":
                return "ALL"
            return s or "UNKNOWN"

        df["Dept_canonical"] = df["Department"].apply(normalize_dept)
        # Section column if present else empty
        if "Section" not in df.columns:
            df["Section"] = ""

        df["Semester"] = df["Semester"].apply(lambda x: self._to_int(x, 0))

        classrooms = self._normalize_classrooms(classrooms_list or [])
        if not classrooms:
            classrooms = [{"name": "C004", "capacity": 300, "type": "Classroom"}]

        result = {}

        # global resource booking (prevent double-booking rooms/faculty campus-wide)
        used_rooms = {d: {slot: set() for slot in self.ordered_slots} for d in self.days}
        faculty_used = {d: {slot: set() for slot in self.ordered_slots} for d in self.days}

        # student occupancy: prevent core-core collision for same branch+sem
        # structure: student_used[branch][sem][day][slot] = True/False
        student_used = {}
        branches_list = []  # collect branch names we'll output (CSE-A, CSE-B, DSAI, ECE...)
        # we'll decide branches dynamically per Dept_canonical
        for dept in sorted(df["Dept_canonical"].unique()):
            if dept == "CSE":
                branches_list.extend(["CSE-A", "CSE-B"])
            else:
                branches_list.append(dept)

        # prepare student_used structure
        for b in branches_list:
            student_used[b] = {}
            # semesters present in data for relevant dept
            # we cannot get sems per branch until we loop; we'll lazily init when needed

        # iterate departments and sems
        for dept in sorted(df["Dept_canonical"].unique()):
            dept_rows = df[df["Dept_canonical"] == dept].copy()

            target_branches = ["CSE-A", "CSE-B"] if dept == "CSE" else [dept]

            for sem in sorted(dept_rows["Semester"].dropna().unique()):
                sem_rows = dept_rows[dept_rows["Semester"] == sem].copy()

                # split combined vs section-specific (if Section contains 'COMBINED' or 'ALL' or Department has 'ALL')
                combined_mask = sem_rows["Section"].astype(str).str.upper().str.contains("COMBINED|ALL") | sem_rows["Department"].astype(str).str.upper().str.contains("COMBINED|ALL")
                combined_rows = sem_rows[combined_mask]
                separate_rows = sem_rows[~combined_mask]

                # create per-branch DataFrame copying rows as appropriate
                per_branch_rows = {b: pd.DataFrame(columns=sem_rows.columns) for b in target_branches}
                # separate_rows routed based on Section column if A/B present; else copied to both
                for _, row in separate_rows.iterrows():
                    sec = str(row.get("Section", "")).strip().upper()
                    if sec == "A" and "CSE-A" in per_branch_rows:
                        per_branch_rows["CSE-A"] = per_branch_rows["CSE-A"].append(row, ignore_index=True)
                    elif sec == "B" and "CSE-B" in per_branch_rows:
                        per_branch_rows["CSE-B"] = per_branch_rows["CSE-B"].append(row, ignore_index=True)
                    else:
                        for b in per_branch_rows:
                            per_branch_rows[b] = per_branch_rows[b].append(row, ignore_index=True)

                for _, row in combined_rows.iterrows():
                    for b in per_branch_rows:
                        per_branch_rows[b] = per_branch_rows[b].append(row, ignore_index=True)

                # schedule per branch
                for branch_name, branch_df in per_branch_rows.items():
                    result.setdefault(branch_name, {})
                    # init student_used for this branch+sem if not already
                    student_used.setdefault(branch_name, {})
                    if str(int(sem)) not in student_used[branch_name]:
                        student_used[branch_name][str(int(sem))] = {d: {slot: False for slot in self.ordered_slots} for d in self.days}

                    timetable_rows = []

                    # classify courses
                    branch_df["Type_norm"] = branch_df["Type"].astype(str).str.strip().str.lower()
                    electives = branch_df[branch_df["Type_norm"] == "elective"]
                    minors = branch_df[branch_df["Type_norm"] == "minor"]
                    cores = branch_df[~branch_df["Type_norm"].isin(["elective", "minor"])]

                    # ---------- ELECTIVES ----------
                    # For electives: for each session-type choose a single slot (from that session-type pool)
                    # that is free for branch+sem (no student core allocation) and that does not conflict room/faculty.
                    # Then assign that same slot for that session-type to all electives.
                    if not electives.empty:
                        # build list of elective sessions by type for the semester (we will allocate per session type)
                        # For each elective, figure sessions like ["Lecture","Tutorial","Lab"...]
                        elective_sessions_by_type = {"Lecture": [], "Tutorial": [], "Lab": []}
                        for _, row in electives.iterrows():
                            L, T, P = self._parse_ltpsc(row.get("LTPSC", ""))
                            elective_sessions_by_type["Lecture"].extend([row] * L)
                            elective_sessions_by_type["Tutorial"].extend([row] * T)
                            elective_sessions_by_type["Lab"].extend([row] * P)

                        # For each session type, pick one slot from the appropriate pool
                        # and assign to all electives that need that session type.
                        for session_type, rows_list in elective_sessions_by_type.items():
                            if not rows_list:
                                continue
                            pool = self.lecture_slots if session_type == "Lecture" else (self.tutorial_slots if session_type == "Tutorial" else self.lab_slots)
                            # find a slot in pool that is free for students and can host all electives (rooms/faculty check)
                            chosen = None
                            # shuffle pool to vary assignments
                            candidate_slots = pool.copy()
                            random.shuffle(candidate_slots)
                            for slot in candidate_slots:
                                # check duration sanity
                                if not self._slot_duration_matches(slot, self.durations.get(session_type, 90)):
                                    continue
                                slot_ok = True
                                for _, course in electives.iterrows():
                                    fac = str(course.get("Faculty","")).strip()
                                    strength = self._to_int(course.get("Strength", 0))
                                    # students must be free in this branch+sem at this slot
                                    if student_used[branch_name][str(int(sem))][self.days[0]].get(slot, False):
                                        # but we must check per day — we need a (day,slot) candidate; we try across days
                                        pass
                                # We need to choose (day,slot), not just slot — so iterate days
                                # We'll handle days iteration below
                                chosen = None
                                break  # break because we will try per (day,slot) pairs below

                            # try each (day,slot)
                            placed_for_all = False
                            for day in self.days:
                                for slot in pool:
                                    if not self._slot_duration_matches(slot, self.durations.get(session_type,90)):
                                        continue
                                    # students must be free at (day,slot)
                                    if student_used[branch_name][str(int(sem))][day][slot]:
                                        continue
                                    # rooms and faculties must be available for all elective courses at (day,slot)
                                    conflict = False
                                    for _, course in electives.iterrows():
                                        fac = str(course.get("Faculty","")).strip()
                                        strength = self._to_int(course.get("Strength", 0))
                                        # faculty global conflict?
                                        if fac and fac in faculty_used[day][slot]:
                                            conflict = True
                                            break
                                        # room availability: at least one room capable needs to be free
                                        room_possible = False
                                        for r in classrooms:
                                            if r["capacity"] >= strength and (not (session_type=="Lab" and "lab" not in r["type"].lower())):
                                                if r["name"] not in used_rooms[day][slot]:
                                                    room_possible = True
                                                    break
                                        if not room_possible:
                                            conflict = True
                                            break
                                    if conflict:
                                        continue
                                    # if reached here, (day,slot) is valid for this session type for all electives
                                    # place all electives' this session type into (day,slot)
                                    for _, course in electives.iterrows():
                                        code = course.get("Course Code","")
                                        title = course.get("Course Title","")
                                        fac = str(course.get("Faculty","")).strip()
                                        strength = self._to_int(course.get("Strength", 0))
                                        room = self._choose_room(classrooms, is_lab=(session_type=="Lab"), strength=strength)
                                        used_rooms[day][slot].add(room["name"])
                                        if fac:
                                            faculty_used[day][slot].add(fac)
                                        timetable_rows.append({
                                            "Day": day,
                                            "Slot": slot,
                                            "Course": f"{code} - {title} (Elective {session_type})",
                                            "Faculty": fac,
                                            "Room": room["name"]
                                        })
                                    # mark students occupied for this branch+sem at (day,slot)
                                    student_used[branch_name][str(int(sem))][day][slot] = True
                                    placed_for_all = True
                                    break
                                if placed_for_all:
                                    break
                            # if not placed_for_all, record unscheduled entries
                            if not placed_for_all:
                                # record unscheduled for each elective (this session type)
                                for _, course in electives.iterrows():
                                    timetable_rows.append({
                                        "Day": "UNSCHEDULED",
                                        "Slot": "N/A",
                                        "Course": f"{course.get('Course Code','')} - {course.get('Course Title','')} (Elective {session_type})",
                                        "Faculty": course.get("Faculty",""),
                                        "Room": "N/A"
                                    })

                    # ---------- MINORS ----------
                    # schedule minors together: choose one minor window (morning or evening) that fits branch+sem (no core collision)
                    if not minors.empty:
                        chosen_minor_day_slot = None
                        # Try morning first then evening (could also pick based on fit)
                        for minor_slot in self.minor_slots:
                            placed = False
                            for day in self.days:
                                # students must be free at this (day,minor_slot)
                                if student_used[branch_name][str(int(sem))][day][minor_slot]:
                                    continue
                                # faculty/room availability check for all minors offerings (similar to electives)
                                conflict = False
                                for _, course in minors.iterrows():
                                    fac = str(course.get("Faculty","")).strip()
                                    strength = self._to_int(course.get("Strength",0))
                                    if fac and fac in faculty_used[day][minor_slot]:
                                        conflict = True
                                        break
                                    room_ok = False
                                    for r in classrooms:
                                        if r["capacity"] >= strength and r["name"] not in used_rooms[day][minor_slot]:
                                            room_ok = True
                                            break
                                    if not room_ok:
                                        conflict = True
                                        break
                                if conflict:
                                    continue
                                # assign all minors into this (day,minor_slot)
                                for _, course in minors.iterrows():
                                    code = course.get("Course Code","")
                                    title = course.get("Course Title","")
                                    fac = str(course.get("Faculty","")).strip()
                                    strength = self._to_int(course.get("Strength",0))
                                    room = self._choose_room(classrooms, is_lab=False, strength=strength)
                                    used_rooms[day][minor_slot].add(room["name"])
                                    if fac:
                                        faculty_used[day][minor_slot].add(fac)
                                    timetable_rows.append({
                                        "Day": day,
                                        "Slot": minor_slot,
                                        "Course": f"{code} - {title} (Minor)",
                                        "Faculty": fac,
                                        "Room": room["name"]
                                    })
                                student_used[branch_name][str(int(sem))][day][minor_slot] = True
                                placed = True
                                break
                            if placed:
                                chosen_minor_day_slot = minor_slot
                                break
                        # if not placed, mark unscheduled minors
                        if chosen_minor_day_slot is None:
                            for _, course in minors.iterrows():
                                timetable_rows.append({
                                    "Day": "UNSCHEDULED",
                                    "Slot": "N/A",
                                    "Course": f"{course.get('Course Code','')} - {course.get('Course Title','')} (Minor)",
                                    "Faculty": course.get("Faculty",""),
                                    "Room": "N/A"
                                })

                    # ---------- CORE courses ----------
                    for _, course in cores.iterrows():
                        code = course.get("Course Code","")
                        title = course.get("Course Title","")
                        fac = str(course.get("Faculty","")).strip()
                        strength = self._to_int(course.get("Strength", 0))
                        L, T, P = self._parse_ltpsc(course.get("LTPSC",""))
                        sessions = (["Lecture"] * L) + (["Tutorial"] * T) + (["Lab"] * P)
                        if not sessions:
                            sessions = ["Lecture"]
                        for session in sessions:
                            # pick pool based on session type
                            pool = self.lecture_slots if session == "Lecture" else (self.tutorial_slots if session == "Tutorial" else self.lab_slots)
                            placed = False
                            # try random day+slot combinations
                            days_shuf = self.days[:]
                            random.shuffle(days_shuf)
                            for day in days_shuf:
                                slot_candidates = pool[:]
                                random.shuffle(slot_candidates)
                                for slot in slot_candidates:
                                    # duration match
                                    if not self._slot_duration_matches(slot, self.durations.get(session, 90)):
                                        continue
                                    # check global faculty & room conflicts
                                    if fac and fac in faculty_used[day][slot]:
                                        continue
                                    room = self._choose_room(classrooms, is_lab=(session=="Lab"), strength=strength)
                                    if room["name"] in used_rooms[day][slot]:
                                        continue
                                    # student (branch+sem) must be free at (day,slot) — prevent core-core collision
                                    if student_used[branch_name][str(int(sem))][day][slot]:
                                        continue
                                    # all good -> place
                                    used_rooms[day][slot].add(room["name"])
                                    if fac:
                                        faculty_used[day][slot].add(fac)
                                    student_used[branch_name][str(int(sem))][day][slot] = True
                                    timetable_rows.append({
                                        "Day": day,
                                        "Slot": slot,
                                        "Course": f"{code} - {title} ({session})",
                                        "Faculty": fac,
                                        "Room": room["name"]
                                    })
                                    placed = True
                                    break
                                if placed:
                                    break
                            if not placed:
                                # couldn't place this session respecting core-non-collision rule
                                timetable_rows.append({
                                    "Day": "UNSCHEDULED",
                                    "Slot": "N/A",
                                    "Course": f"{code} ({session})",
                                    "Faculty": fac,
                                    "Room": "N/A"
                                })

                    # final sort & save for branch+sem
                    timetable_rows.sort(key=lambda r: (self.day_order.get(r["Day"], 999),
                                                       self.slot_order.get(r["Slot"], 999),
                                                       r["Course"]))
                    result[branch_name][str(int(sem))] = timetable_rows

        return result
