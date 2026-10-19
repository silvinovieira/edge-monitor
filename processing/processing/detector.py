"""Anomaly detector: z-scores against a baseline learned during warm-up."""

from dataclasses import asdict

from processing.features import Features


class RunningStats:
    """Mean and standard deviation updated one value at a time (Welford)."""

    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self._sum_of_squares = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self._sum_of_squares += delta * (value - self.mean)

    @property
    def std(self) -> float:
        return (self._sum_of_squares / self.count) ** 0.5 if self.count else 0.0

    def get_z_score(self, value: float) -> float:
        return (value - self.mean) / self.std if self.std > 0 else 0.0


class Detector:
    """Flags a window when any feature is far from its warm-up baseline.

    The first `warmup_windows` windows only build the baseline, which then
    stays frozen so a slow fault can't become the new normal. A window is
    anomalous once `consecutive_windows` windows in a row have any |z| above
    `z_threshold`; one noisy window alone is not enough.
    """

    def __init__(
        self, warmup_windows: int, z_threshold: float, consecutive_windows: int
    ) -> None:
        self._warmup_windows_left = warmup_windows
        self._z_threshold = z_threshold
        self._consecutive_windows = consecutive_windows
        self._baseline: dict[str, RunningStats] = {}
        self._outlier_streak = 0

    def check(self, features: Features) -> bool:
        """Return True if this window is anomalous."""
        values = asdict(features)
        if self._warmup_windows_left > 0:
            self._learn(values)
            return False
        if self._is_outlier(values):
            self._outlier_streak += 1
        else:
            self._outlier_streak = 0
        return self._outlier_streak >= self._consecutive_windows

    def _learn(self, values: dict[str, float]) -> None:
        for name, value in values.items():
            self._baseline.setdefault(name, RunningStats()).add(value)
        self._warmup_windows_left -= 1

    def _is_outlier(self, values: dict[str, float]) -> bool:
        return any(
            abs(self._baseline[name].get_z_score(value)) > self._z_threshold
            for name, value in values.items()
        )
