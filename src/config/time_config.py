"""
src/config/time_config.py
=========================
Defines working hours and strict time slots for lectures, tutorials, labs, and minors.
"""

def get_active_config():
    config = {
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],

        # slot definitions: (start, end)
        # Labs (2 hr), Lectures (1.5 hr), Tutorials (1 hr)
        "regular_slots": [
            ("09:00", "10:30"),   # Lecture
            ("10:45", "12:15"),   # Lecture
            # lunch: 12:30 - 14:00
            ("14:00", "15:30"),   # Lecture
            ("15:30", "17:30"),   # Lab (2 hr slot)
        ],

        "minor_slots": [
            ("07:30", "09:00"),   # Morning Minor
            ("17:30", "19:00")    # Evening Minor
        ],

        "lunch_break": ("12:30", "14:00"),
    }
    return config
