"""Hidden tests for the TokenBucket task. Deterministic: time comes from a fake clock."""

import pytest

from solution import TokenBucket


class FakeClock:
    """Manually advanced clock: call it to read, `advance` to move forward."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_bucket(rate: float = 1.0, capacity: float = 10.0, start: float = 0.0):
    clock = FakeClock(start)
    return TokenBucket(rate, capacity, clock), clock


def test_starts_full():
    bucket, _ = make_bucket(rate=2.0, capacity=5.0)
    assert bucket.tokens == pytest.approx(5.0)


def test_allow_consumes_tokens_and_returns_true():
    bucket, _ = make_bucket(rate=1.0, capacity=10.0)
    assert bucket.allow(4.0) is True
    assert bucket.tokens == pytest.approx(6.0)
    assert bucket.allow(6.0) is True
    assert bucket.tokens == pytest.approx(0.0)


def test_allow_returns_false_when_tokens_are_insufficient_without_consuming():
    bucket, _ = make_bucket(rate=1.0, capacity=5.0)
    assert bucket.allow(4.0) is True
    assert bucket.allow(3.0) is False
    assert bucket.tokens == pytest.approx(1.0)


def test_no_refill_without_elapsed_time():
    bucket, _ = make_bucket(rate=100.0, capacity=2.0)
    assert bucket.allow(2.0) is True
    assert bucket.allow(0.0001) is False
    assert bucket.tokens == pytest.approx(0.0)


def test_refill_over_time():
    bucket, clock = make_bucket(rate=2.0, capacity=10.0)
    assert bucket.allow(10.0) is True
    assert bucket.tokens == pytest.approx(0.0)
    clock.advance(1.5)
    assert bucket.tokens == pytest.approx(3.0)
    clock.advance(0.5)
    assert bucket.allow(4.0) is True
    assert bucket.tokens == pytest.approx(0.0)


def test_refill_is_capped_at_capacity():
    bucket, clock = make_bucket(rate=1.0, capacity=4.0)
    assert bucket.allow(4.0) is True
    clock.advance(100.0)
    assert bucket.tokens == pytest.approx(4.0)
    assert bucket.allow(4.0) is True
    assert bucket.tokens == pytest.approx(0.0)


def test_tokens_property_does_not_double_count():
    bucket, clock = make_bucket(rate=1.0, capacity=10.0)
    assert bucket.allow(10.0) is True
    clock.advance(3.0)
    assert bucket.tokens == pytest.approx(3.0)
    assert bucket.tokens == pytest.approx(3.0)
    clock.advance(2.0)
    assert bucket.tokens == pytest.approx(5.0)


def test_cost_greater_than_capacity_is_always_false():
    bucket, clock = make_bucket(rate=1.0, capacity=5.0)
    assert bucket.allow(5.5) is False
    clock.advance(1000.0)
    assert bucket.allow(5.0 + 1e-6) is False
    assert bucket.tokens == pytest.approx(5.0)


def test_cost_equal_to_capacity_from_full_succeeds():
    bucket, _ = make_bucket(rate=1.0, capacity=7.5)
    assert bucket.allow(7.5) is True
    assert bucket.tokens == pytest.approx(0.0)


def test_cost_exactly_equal_to_available_tokens_succeeds():
    bucket, clock = make_bucket(rate=4.0, capacity=2.0)
    assert bucket.allow(2.0) is True
    clock.advance(0.5)  # refills exactly 2.0 tokens
    assert bucket.allow(2.0) is True
    assert bucket.tokens == pytest.approx(0.0)


def test_default_cost_is_one():
    bucket, _ = make_bucket(rate=1.0, capacity=3.0)
    assert bucket.allow() is True
    assert bucket.tokens == pytest.approx(2.0)


def test_partial_refill_accumulates_across_calls():
    bucket, clock = make_bucket(rate=0.5, capacity=10.0)
    assert bucket.allow(9.0) is True  # tokens: 1.0
    clock.advance(2.0)  # +1.0 -> 2.0
    assert bucket.allow(1.5) is True  # tokens: 0.5
    clock.advance(2.0)  # +1.0 -> 1.5
    assert bucket.tokens == pytest.approx(1.5)
    assert bucket.allow(2.0) is False
    assert bucket.tokens == pytest.approx(1.5)


def test_works_with_non_zero_start_time():
    clock = FakeClock(1000.0)
    bucket = TokenBucket(3.0, 9.0, clock)
    assert bucket.allow(9.0) is True
    clock.advance(1.0)
    assert bucket.tokens == pytest.approx(3.0)


@pytest.mark.parametrize("rate", [0.0, -1.0, -0.001])
def test_invalid_rate_raises_value_error(rate):
    with pytest.raises(ValueError):
        TokenBucket(rate, 1.0, FakeClock())


@pytest.mark.parametrize("capacity", [0.0, -5.0])
def test_invalid_capacity_raises_value_error(capacity):
    with pytest.raises(ValueError):
        TokenBucket(1.0, capacity, FakeClock())


@pytest.mark.parametrize("cost", [0.0, -1.0, -0.5])
def test_invalid_cost_raises_value_error(cost):
    bucket, _ = make_bucket()
    with pytest.raises(ValueError):
        bucket.allow(cost)


def test_invalid_cost_leaves_tokens_untouched():
    bucket, _ = make_bucket(rate=1.0, capacity=4.0)
    with pytest.raises(ValueError):
        bucket.allow(0.0)
    assert bucket.tokens == pytest.approx(4.0)
