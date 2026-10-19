"""Fixed-size buffer holding the most recent samples."""

import numpy as np


class RingBuffer:
    """Keeps the last `capacity` values in one preallocated array.

    Appending overwrites the oldest value, so memory is fixed at creation and
    never grows with run length.
    """

    def __init__(self, capacity: int) -> None:
        self._values = np.zeros(capacity)
        self._next_index = 0
        self._count = 0

    @property
    def capacity(self) -> int:
        return len(self._values)

    @property
    def is_full(self) -> bool:
        return self._count == self.capacity

    def append(self, value: float) -> None:
        self._values[self._next_index] = value
        self._next_index = (self._next_index + 1) % self.capacity
        self._count = min(self._count + 1, self.capacity)

    def get_snapshot(self) -> np.ndarray:
        """Return a copy of the stored values, oldest first."""
        if not self.is_full:
            return self._values[: self._count].copy()
        # The oldest value sits where the next write will go.
        return np.roll(self._values, -self._next_index)
