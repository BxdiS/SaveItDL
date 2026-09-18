from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _UserState:
    last_msg: float = 0.0
    last_cb: float = 0.0
    window: deque = field(default_factory=deque)


class RateLimiter:
    """
    In-memory per-user rate limiter.
      - min interval between messages (stricter for new users)
      - burst window (N messages per M seconds)
      - callback throttle
    """

    def __init__(
        self,
        interval_s: float = 5.0,
        burst_max: int = 3,
        burst_window_s: float = 10.0,
        callback_interval_s: float = 2.0,
        new_user_interval_s: float = 10.0,
        new_user_age_s: float = 24 * 3600,
    ):
        self.interval_s = interval_s
        self.burst_max = burst_max
        self.burst_window_s = burst_window_s
        self.callback_interval_s = callback_interval_s
        self.new_user_interval_s = new_user_interval_s
        self.new_user_age_s = new_user_age_s
        self._users: dict[int, _UserState] = {}

    def _get(self, uid: int) -> _UserState:
        st = self._users.get(uid)
        if st is None:
            st = _UserState()
            self._users[uid] = st
        return st

    def check_message(
        self, user_id: int, first_seen: float | None = None
    ) -> tuple[bool, float]:
        now = time.time()
        st = self._get(user_id)

        interval = self.interval_s
        if first_seen is not None and (now - first_seen) < self.new_user_age_s:
            interval = max(interval, self.new_user_interval_s)

        if now - st.last_msg < interval:
            return False, interval - (now - st.last_msg)

        while st.window and now - st.window[0] > self.burst_window_s:
            st.window.popleft()
        if len(st.window) >= self.burst_max:
            oldest = st.window[0]
            return False, self.burst_window_s - (now - oldest)

        st.last_msg = now
        st.window.append(now)
        return True, 0.0

    def check_callback(self, user_id: int) -> tuple[bool, float]:
        now = time.time()
        st = self._get(user_id)
        if now - st.last_cb < self.callback_interval_s:
            return False, self.callback_interval_s - (now - st.last_cb)
        st.last_cb = now
        return True, 0.0

    def sweep(self, max_age_s: float = 3600) -> None:
        """Drop stale user entries. Call periodically."""
        now = time.time()
        stale = [
            uid for uid, st in self._users.items()
            if now - max(st.last_msg, st.last_cb) > max_age_s
        ]
        for uid in stale:
            self._users.pop(uid, None)
