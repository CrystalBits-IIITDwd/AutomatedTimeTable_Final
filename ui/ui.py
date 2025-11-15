"""
ui/ui.py — updated UI: use a single combined courses.csv; keep all features.
Put this file at ui/ui.py (replace existing), then run: python -m ui.ui
"""

import sys
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd

# make sure project root is on path so relative imports work when running ui/ui.py directly
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.scheduler.timetable_scheduler import TimetableScheduler
from src.config.time_config import get_active_config

class TimetableApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CrystalTimetable v3 — Greedy Edition")
        self.root.geometry("1100x650")
        self.root.configure(bg="#f0f3f7")

        self.courses_df = None       # combined courses DataFrame
        self.classrooms = []         # list of dicts
        self.timetable = {}          # produced timetable dict

        self.setup_styles()
        self.setup_ui()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#ffffff", foreground="#333333",
                        rowheight=28, fieldbackground="#ffffff", font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#0052cc", foreground="white",
                        font=("Segoe UI", 11, "bold"))

    def setup_ui(self):
        title_frame = tk.Frame(self.root, bg="#0052cc", height=60)
        title_frame.pack(fill="x")
        tk.Label(title_frame, text="📅 CrystalTimetable v3 — Greedy Edition",
                 bg="#0052cc", fg="white", font=("Segoe UI", 20, "bold")).pack(pady=10)

        btn_frame = tk.Frame(self.root, bg="#f0f3f7")
        btn_frame.pack(fill="x", pady=8)

        self.make_button(btn_frame, "📂 Load Classrooms CSV", self.load_classrooms, "#28a745").pack(side="left", padx=6)
        self.make_button(btn_frame, "📂 Load Combined Courses CSV", self.load_courses, "#007bff").pack(side="left", padx=6)
        self.make_button(btn_frame, "⚡ Generate Timetable", self.generate_timetable, "#17a2b8").pack(side="left", padx=6)
        self.make_button(btn_frame, "📖 Show Timetable", self.show_timetable, "#6f42c1").pack(side="left", padx=6)
        self.make_button(btn_frame, "📤 Export CSV", self.export_csv, "#e83e8c").pack(side="left", padx=6)

        # Filters area
        filter_frame = tk.Frame(self.root, bg="#f0f3f7")
        filter_frame.pack(fill="x", padx=10, pady=8)

        tk.Label(filter_frame, text="Branch:", font=("Segoe UI", 11, "bold"), bg="#f0f3f7").pack(side="left", padx=4)
        self.branch_var = tk.StringVar()
        self.branch_cb = ttk.Combobox(filter_frame, textvariable=self.branch_var,
                                      values=["CSE-A", "CSE-B", "DSAI", "ECE"], state="readonly", width=12)
        self.branch_cb.current(0)
        self.branch_cb.pack(side="left", padx=6)

        tk.Label(filter_frame, text="Semester:", font=("Segoe UI", 11, "bold"), bg="#f0f3f7").pack(side="left", padx=6)
        self.sem_var = tk.StringVar()
        self.sem_cb = ttk.Combobox(filter_frame, textvariable=self.sem_var,
                                   values=[str(i) for i in range(1, 9)], state="readonly", width=6)
        self.sem_cb.current(0)
        self.sem_cb.pack(side="left", padx=6)

        # Table
        table_frame = tk.Frame(self.root, bg="#f0f3f7")
        table_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.tree = ttk.Treeview(table_frame, columns=("Day", "Slot", "Course", "Faculty", "Room"),
                                 show="headings")
        for col, width in [("Day", 100), ("Slot", 140), ("Course", 360), ("Faculty", 180), ("Room", 100)]:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="center")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def make_button(self, parent, text, command, color):
        btn = tk.Label(parent, text=text, bg=color, fg="white", font=("Segoe UI", 11, "bold"),
                       padx=12, pady=8, cursor="hand2")
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.config(bg="#003d99"))
        btn.bind("<Leave>", lambda e: btn.config(bg=color))
        return btn

    # ---------------- CSV loaders ----------------
    def load_classrooms(self):
        path = filedialog.askopenfilename(title="Select Classrooms CSV", filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            df = pd.read_csv(path)
            # convert to list of dicts
            self.classrooms = df.to_dict(orient="records")
            messagebox.showinfo("Loaded", f"✅ Loaded {len(self.classrooms)} classrooms.")
        except Exception as e:
            messagebox.showerror("Error", f"❌ Could not load classrooms: {e}")

    def load_courses(self):
        path = filedialog.askopenfilename(title="Select Combined Courses CSV", filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            df = pd.read_csv(path)
            # normalize columns: accept 'branch' or 'Department' etc.
            df.columns = [c.strip() for c in df.columns]
            if "branch" in [c.lower() for c in df.columns] and "Department" not in df.columns:
                # find actual column name for branch
                for c in df.columns:
                    if c.lower() == "branch":
                        df = df.rename(columns={c: "Department"})
                        break
            # ensure Semester header present
            if "semester" in [c.lower() for c in df.columns] and "Semester" not in df.columns:
                for c in df.columns:
                    if c.lower() == "semester":
                        df = df.rename(columns={c: "Semester"})
                        break

            self.courses_df = df
            messagebox.showinfo("Loaded", "✅ Combined courses.csv loaded successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"❌ Could not load courses: {e}")

    # ---------------- Timetable actions ----------------
    def generate_timetable(self):
        if self.courses_df is None:
            messagebox.showwarning("Missing Data", "Please load the combined courses.csv")
            return
        # create scheduler and run
        try:
            config = get_active_config()
            scheduler = TimetableScheduler(config)
            # pass DataFrame and classrooms list
            self.timetable = scheduler.generate_all(self.courses_df, classrooms_list=self.classrooms)
            messagebox.showinfo("Success", "✅ Timetable generated (in-memory). You can now Show / Export.")
        except Exception as e:
            messagebox.showerror("Error", f"❌ Scheduler failed: {e}")

    def show_timetable(self):
        self.tree.delete(*self.tree.get_children())
        branch = self.branch_var.get()
        sem = self.sem_var.get()

        if not self.timetable:
            messagebox.showwarning("No Timetable", "Please generate the timetable first.")
            return
        if branch not in self.timetable:
            messagebox.showwarning("Not Found", f"No timetable found for {branch}.")
            return
        if sem not in self.timetable[branch]:
            messagebox.showwarning("Not Found", f"No timetable found for {branch} semester {sem}.")
            return

        rows = self.timetable[branch][sem]

        # -----------------------------
        # Sorting Logic (FIXED)
        # -----------------------------
        config = get_active_config()

        # Build slot start-time map
        def start_minutes(slot):
            start, _ = slot.split("-")
            hh, mm = map(int, start.split(":"))
            return hh * 60 + mm

        # Sort slots by start-time from ALL slot types
        ordered_slots = (
            config["lecture_slots"] +
            config["tutorial_slots"] +
            config["lab_slots"] +
            config["minor_slots"]
        )
        ordered_slots = [f"{s[0]}-{s[1]}" for s in ordered_slots]
        ordered_slots = sorted(ordered_slots, key=start_minutes)

        day_index = {d: i for i, d in enumerate(config["working_days"])}
        slot_index = {s: i for i, s in enumerate(ordered_slots)}

        def row_key(r):
            return (
                day_index.get(r["Day"], 999),
                slot_index.get(r["Slot"], 999),
                r["Course"]
            )

        rows_sorted = sorted(rows, key=row_key)

        # -----------------------------
        # Insert into TreeView
        # -----------------------------
        for r in rows_sorted:
            self.tree.insert(
                "",
                "end",
                values=(r["Day"], r["Slot"], r["Course"], r["Faculty"], r["Room"])
            )


    def export_csv(self):
        if not self.timetable:
            messagebox.showwarning("No Data", "Generate timetable first")
            return
        save_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not save_path:
            return
        # flatten all branches + semesters to rows
        data = []
        for branch in sorted(self.timetable.keys()):
            for sem in sorted(self.timetable[branch].keys(), key=lambda x: int(x)):
                for row in self.timetable[branch][sem]:
                    data.append({
                        "Branch": branch,
                        "Semester": sem,
                        **row
                    })
        pd.DataFrame(data).to_csv(save_path, index=False)
        messagebox.showinfo("Exported", f"✅ Timetable saved to {save_path}")

if __name__ == "__main__":
    root = tk.Tk()
    app = TimetableApp(root)
    root.mainloop()
