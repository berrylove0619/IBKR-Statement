from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.daily_position_review_service import DailyPositionReviewService


class TestRunParallel:
    @staticmethod
    def _run_parallel_target(*funcs: callable) -> tuple:
        return DailyPositionReviewService._run_parallel(*funcs)

    def test_preserves_order_when_second_finishes_first(self):
        def slow():
            import time

            time.sleep(0.05)
            return "slow_result"

        def fast():
            return "fast_result"

        a, b = self._run_parallel_target(slow, fast)
        assert a == "slow_result"
        assert b == "fast_result"

    def test_preserves_order_multiple_functions(self):
        def make_fn(label, delay):
            def fn():
                import time

                time.sleep(delay)
                return label

            return fn

        fns = [make_fn(f"fn{i}", 0.1 - i * 0.01) for i in range(4)]
        results = self._run_parallel_target(*fns)
        assert results == ("fn0", "fn1", "fn2", "fn3")

    def test_propagates_exception(self):
        def ok():
            return "ok"

        def boom():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            self._run_parallel_target(ok, boom)

    def test_exception_order_first(self):
        def boom():
            raise ValueError("first")

        def ok():
            return "second"

        with pytest.raises(ValueError, match="first"):
            self._run_parallel_target(boom, ok)

    def test_preserves_order_with_error_in_middle(self):
        def first():
            return "one"

        def second():
            raise ValueError("mid")

        def third():
            return "three"

        with pytest.raises(ValueError, match="mid"):
            self._run_parallel_target(first, second, third)