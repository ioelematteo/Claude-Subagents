"""Cost ceiling with pre-flight reservation.

Before every model call the engine reserves the worst-case cost of that attempt (estimated input +
the tier's reserved output). If the reservation does not fit under the ceiling the attempt never starts,
so the budget cannot be overshot by jobs running in parallel. After the call the reservation is settled
with the real cost. All methods run on the event loop without awaiting, so they are atomic.
"""
from dataclasses import dataclass

from swarm.config import Tier

CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def worst_case_cost(tier: Tier, prompt: str, system: str) -> float:
    return tier.cost(estimate_tokens(prompt) + estimate_tokens(system), tier.reserve_out)


@dataclass
class Budget:
    limit_usd: float
    spent_usd: float = 0.0
    reserved_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        return self.limit_usd - self.spent_usd - self.reserved_usd

    def reserve(self, amount: float) -> bool:
        if amount > self.remaining_usd:
            return False
        self.reserved_usd += amount
        return True

    def settle(self, reserved: float, actual: float) -> None:
        self.reserved_usd = max(0.0, self.reserved_usd - reserved)
        self.spent_usd += actual

    def status(self) -> dict:
        return {
            "limit_usd": round(self.limit_usd, 4),
            "spent_usd": round(self.spent_usd, 5),
            "reserved_usd": round(self.reserved_usd, 5),
            "remaining_usd": round(self.remaining_usd, 5),
        }
