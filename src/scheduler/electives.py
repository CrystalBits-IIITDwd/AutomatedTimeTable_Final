"""
src/scheduler/electives.py
==========================
Handles elective baskets, rotation, and global elective slot sync.
"""

class ElectiveManager:
    def __init__(self):
        self.global_slots = {}  # sem -> basket -> [(day, slot)]
        self.rotation = {
            2: ["B1", "B3", "E1"],
            4: ["B1", "B3", "Minor"],
            6: ["B1", "E1"]
        }

    def allowed_baskets(self, sem):
        return self.rotation.get(sem, [])

    def save_global(self, sem, basket, slots):
        self.global_slots.setdefault(sem, {})[basket] = slots

    def get_global(self, sem, basket):
        return self.global_slots.get(sem, {}).get(basket)
