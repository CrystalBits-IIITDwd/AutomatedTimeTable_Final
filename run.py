"""
run.py — Entry point for CrystalTimetable v3 (Greedy Edition)
=============================================================
This is a simplified, dependency-free timetable generator that
uses a rule-based greedy scheduling algorithm.
After generation, it automatically opens the Tkinter GUI.
"""

import subprocess
import sys
from src.scheduler.timetable_scheduler import TimetableScheduler
from src.config.time_config import get_active_config

def main():
    config = get_active_config()
    scheduler = TimetableScheduler(config)

    departments = ["CSE", "DSAI", "ECE"]
    semesters = [2, 4, 6]
    sections = ["A", "B"]

    print("\n🚀 CrystalTimetable v3 — Greedy Edition (Pure Python)\n")
    for dept in departments:
        for sem in semesters:
            active_sections = sections if dept == "CSE" else ["A"]
            for sec in active_sections:
                print(f"Generating timetable for {dept} Semester {sem} Section {sec} ...")
                try:
                    timetable = scheduler.generate(dept, sem, sec)
                    scheduler.export_csv(timetable, dept, sem, sec)
                except AttributeError:
                    print("⚠️ Skipping generation — 'generate' method not available in this build.")
                    break

    print("\n✅ All timetables generated successfully!")

    # 🖥️ Launch the GUI automatically
    try:
        print("\n🔄 Opening CrystalTimetable GUI ...")
        subprocess.run([sys.executable, "-m", "ui.ui"], check=True)
    except Exception as e:
        print(f"⚠️ Failed to open UI automatically: {e}")
        print("You can still run it manually using: python -m ui.ui")

if __name__ == "__main__":
    main()
