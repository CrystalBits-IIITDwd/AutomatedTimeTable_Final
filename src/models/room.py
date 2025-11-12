"""
src/models/room.py
==================
Room model + helper methods for capacity and type filtering.
"""

from dataclasses import dataclass

@dataclass
class Room:
    name: str
    capacity: int
    type: str  # "Classroom", "Software Lab", etc.

    def is_suitable_for(self, course_type: str, strength: int) -> bool:
        """Check capacity and type compatibility."""
        if self.capacity < strength:
            return False
        if "lab" in course_type.lower() and "lab" not in self.type.lower():
            return False
        return True
