from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from pulsepay.core.config import settings


@dataclass
class TokenBucket:
	tokens: float
	last_refill: float
	capacity: float
	refill_rate: float


# This module-level in-memory store is not safe for multi-process deployments; production should use Redis with a Lua script for atomic token consumption.
_buckets: dict[str, TokenBucket] = {}


class RateLimitStore:
	def __init__(self) -> None:
		cfg = settings()
		self._refill_rate = float(cfg.API_RATE_LIMIT_PER_MINUTE) / 60.0
		burst_tokens = float(cfg.API_BURST_LIMIT_PER_SECOND)
		capacity_seconds = burst_tokens / self._refill_rate
		self._capacity = self._refill_rate * capacity_seconds

	def consume(self, api_key: str, tokens: float = 1.0) -> tuple[bool, float]:
		now = monotonic()
		bucket = _buckets.get(api_key)
		if bucket is None:
			bucket = TokenBucket(
				tokens=self._capacity,
				last_refill=now,
				capacity=self._capacity,
				refill_rate=self._refill_rate,
			)
			_buckets[api_key] = bucket

		elapsed = max(0.0, now - bucket.last_refill)
		bucket.tokens = min(bucket.capacity, bucket.tokens + (elapsed * bucket.refill_rate))
		bucket.last_refill = now

		if bucket.tokens >= tokens:
			bucket.tokens -= tokens
			return True, 0.0

		missing_tokens = tokens - bucket.tokens
		retry_after_seconds = missing_tokens / bucket.refill_rate
		return False, max(0.0, retry_after_seconds)


rate_limit_store = RateLimitStore()
