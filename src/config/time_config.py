"""
src/config/time_config.py
=========================
Defines working hours and strict time slots for lectures, tutorials, labs, and minors.
"""

def get_active_config():
    config = {
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],

        # Lecture slots (90 minutes)
        "lecture_slots": [
            ("09:00", "10:30"),
            ("10:45", "12:15"),
            ("14:00", "15:30"),
            ("15:40", "17:10")
        ],

        # Tutorial slots (60 minutes)
        "tutorial_slots": [
            ("12:15", "13:15"),
            ("17:30", "18:30")
        ],

        # Lab slots (120 minutes)
        "lab_slots": [
            ("09:00", "11:00"),
            ("11:00", "13:00"),
            ("14:00", "16:00")
        ],

        # Minor slots (either morning or evening)
        "minor_slots": [
            ("07:30", "09:00"),   # Morning Minor
            ("18:30", "20:00")    # Evening Minor
        ],

        # lunch break (used for any extra checks if needed)
        "lunch_break": ("13:15", "14:00"),
    }
    return config
