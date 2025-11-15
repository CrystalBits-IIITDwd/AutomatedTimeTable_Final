"""
src/models/course.py
====================
Dataclass model for Course representation.
"""

from dataclasses import dataclass

@dataclass
class Course:
    code: str
    name: str
    branch: str
    semester: int
    LTPSC: str
    faculty: str
    strength: int
    course_type: str  # core, elective, minor
    basket: str = None  # For electives

    def parse_ltpsc(self):
        """Convert LTPSC like '3-1-2-0-4' into integers (L,T,P,S,C)."""
        if not self.LTPSC or not isinstance(self.LTPSC, str):
            return 0, 0, 0, 0, 0
        parts = [p.strip() for p in self.LTPSC.split('-')]
        while len(parts) < 5:
            parts.append("0")
        try:
            L, T, P, S, C = map(int, parts[:5])
        except Exception:
            L, T, P, S, C = 0, 0, 0, 0, 0
        return L, T, P, S, C

    def get_session_requirements(self):
        """
        Get session requirements as a list of sessions where each session is
        {"type": "Lecture"/"Tutorial"/"Lab", "duration": minutes}
        Duration convention:
            Lecture = 90 min (1.5 hr)
            Tutorial = 60 min (1 hr)
            Lab = 120 min (2 hr)
        """
        L, T, P, _, _ = self.parse_ltpsc()
        sessions = []
        for _ in range(L):
            sessions.append({"type": "Lecture", "duration": 90})
        for _ in range(T):
            sessions.append({"type": "Tutorial", "duration": 60})
        for _ in range(P):
            sessions.append({"type": "Lab", "duration": 120})
        return sessions

    def is_elective(self):
        return str(self.course_type).strip().lower() in ['elective', 'minor']
