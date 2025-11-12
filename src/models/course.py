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
        """Convert LTPSC into sessions with proper durations."""
        try:
            L, T, P, S, C = [int(x) for x in self.LTPSC.split('-')]
        except:
            L, T, P, S, C = 0, 0, 0, 0, 0
            
        return {
            "lectures": L,  # Number of lecture hours per week
            "tutorials": T, # Number of tutorial hours per week  
            "labs": P,      # Number of lab hours per week
            "credits": C
        }

    def get_session_requirements(self):
        """Get session requirements with proper durations."""
        requirements = self.parse_ltpsc()
        sessions = []
        
        # Lectures: 1 hour each
        for i in range(requirements["lectures"]):
            sessions.append({"type": "lecture", "duration": 60})
            
        # Tutorials: 1.5 hours each  
        for i in range(requirements["tutorials"]):
            sessions.append({"type": "tutorial", "duration": 90})
            
        # Labs: 2 hours each
        for i in range(requirements["labs"]):
            sessions.append({"type": "lab", "duration": 120})
            
        return sessions

    def is_elective(self):
        """Check if course is an elective."""
        return self.course_type.lower() in ['elective', 'minor']