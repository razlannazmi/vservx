"""Slowing down password guessing.

Sign-ins are counted per IP address and per email, and sign-ups per IP address. The counts are
kept in memory: vservx runs as one process, and a restart forgetting them does no harm. Past a
limit, requests are refused before any password is hashed, so a flood of them can't tie up the
CPU either. An attempt is counted before its password is checked, so many sent at once can't all
slip past the limit, and a sign-in that works gets its attempt back.
"""

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

SIGN_IN_WINDOW = 15 * 60.0
# One address guessing at any accounts.
SIGN_IN_FAILURES_PER_IP = 20
# Many addresses guessing at one account. Well above the per-address limit, so one address
# can't lock someone else out of their account.
SIGN_IN_FAILURES_PER_EMAIL = 100
SIGN_UP_WINDOW = 60 * 60.0
SIGN_UPS_PER_IP = 5

Clock = Callable[[], float]


class Attempts:
    """The latest `limit` attempts of each key, refused once `limit` of them fall within `window`
    seconds."""

    def __init__(self, limit: int, window: float, clock: Clock) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        # In order of each key's latest attempt, so keys with nothing recent are dropped from the front.
        self._times: OrderedDict[str, deque[float]] = OrderedDict()

    def wait(self, key: str) -> float:
        """Seconds until `key` may try again; 0 when it may now."""
        times = self._times.get(key)
        if times is None or len(times) < self._limit:
            return 0.0
        return max(0.0, times[0] + self._window - self._clock())

    def add(self, key: str) -> None:
        now = self._clock()
        times = self._times.get(key)
        if times is None:
            times = self._times[key] = deque(maxlen=self._limit)
        else:
            self._times.move_to_end(key)
        times.append(now)
        # Stops at the latest key at the latest, which was just added to.
        while next(iter(self._times.values()))[-1] <= now - self._window:
            self._times.popitem(last=False)

    def give_back(self, key: str) -> None:
        """Take back the latest attempt of `key`."""
        times = self._times.get(key)
        if times:
            times.pop()

    def clear(self, key: str) -> None:
        self._times.pop(key, None)


def _too_many(what: str, wait: float) -> HTTPException:
    minutes = max(1, math.ceil(wait / 60))
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many {what}. Try again in {minutes} minute{'s' if minutes > 1 else ''}.",
        headers={"Retry-After": str(max(1, math.ceil(wait)))},
    )


class SignInLimits:
    def __init__(
        self,
        *,
        failures_per_ip: int = SIGN_IN_FAILURES_PER_IP,
        failures_per_email: int = SIGN_IN_FAILURES_PER_EMAIL,
        sign_ups_per_ip: int = SIGN_UPS_PER_IP,
        clock: Clock = time.monotonic,
    ) -> None:
        self._by_ip = Attempts(failures_per_ip, SIGN_IN_WINDOW, clock)
        self._by_email = Attempts(failures_per_email, SIGN_IN_WINDOW, clock)
        self._sign_ups = Attempts(sign_ups_per_ip, SIGN_UP_WINDOW, clock)

    def attempt_sign_in(self, ip: str, email: str) -> None:
        """Count a sign-in as failed until it works, or raise 429 if there have been too many."""
        wait = max(self._by_ip.wait(ip), self._by_email.wait(email))
        if wait > 0:
            raise _too_many("failed sign-ins", wait)
        self._by_ip.add(ip)
        self._by_email.add(email)

    def sign_in_worked(self, ip: str, email: str) -> None:
        """The password was right: this attempt doesn't count, nor do the email's earlier ones."""
        self._by_ip.give_back(ip)
        self._by_email.clear(email)

    def attempt_sign_up(self, ip: str) -> None:
        """Count a sign-up, or raise 429 if this address has asked for too many."""
        wait = self._sign_ups.wait(ip)
        if wait > 0:
            raise _too_many("sign-ups from this address", wait)
        self._sign_ups.add(ip)


KEY_CHECK_WINDOW = 60.0
KEY_CHECKS_PER_MINUTE = 10


class KeyCheckLimits:
    """Check a key, at most 10 a minute per user, so a viewer can't use it to guess an API key.
    Every check counts, matches included."""

    def __init__(self, *, per_minute: int = KEY_CHECKS_PER_MINUTE, clock: Clock = time.monotonic) -> None:
        self._checks = Attempts(per_minute, KEY_CHECK_WINDOW, clock)

    def attempt(self, user_id: int) -> None:
        key = str(user_id)
        wait = self._checks.wait(key)
        if wait > 0:
            raise _too_many("key checks", wait)
        self._checks.add(key)


def client_ip(request: Request) -> str:
    # Behind a reverse proxy this is the proxy's address, unless uvicorn trusts its
    # X-Forwarded-For (the FORWARDED_ALLOW_IPS environment variable).
    return request.client.host if request.client else "unknown"


def _sign_in_limits(request: Request) -> SignInLimits:
    return request.app.state.sign_in_limits


SignInLimitsDep = Annotated[SignInLimits, Depends(_sign_in_limits)]


def _key_check_limits(request: Request) -> KeyCheckLimits:
    return request.app.state.key_check_limits


KeyCheckLimitsDep = Annotated[KeyCheckLimits, Depends(_key_check_limits)]
