"""Tests for the Brier Score calibration tracker."""

import pytest

from app.engine.calibration import (
    CalibrationTracker,
    Prediction,
    Backtester,
)


class TestBrierScore:
    def setup_method(self):
        self.tracker = CalibrationTracker()

    def test_perfect_predictions(self):
        brier = self.tracker.brier_score([1.0, 0.0, 1.0], [1, 0, 1])
        assert brier == pytest.approx(0.0)

    def test_worst_predictions(self):
        brier = self.tracker.brier_score([0.0, 1.0, 0.0], [1, 0, 1])
        assert brier == pytest.approx(1.0)

    def test_always_50_percent(self):
        brier = self.tracker.brier_score([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0])
        assert brier == pytest.approx(0.25)

    def test_good_model(self):
        # Model A from gemchange thread example
        brier = self.tracker.brier_score([0.7, 0.3, 0.9, 0.1], [1, 0, 1, 0])
        assert brier == pytest.approx(0.05)

    def test_lower_is_better(self):
        good = self.tracker.brier_score([0.8, 0.2], [1, 0])
        bad = self.tracker.brier_score([0.6, 0.4], [1, 0])
        assert good < bad


class TestCalibrationTracker:
    def setup_method(self):
        self.tracker = CalibrationTracker()

    def test_record_and_resolve(self):
        pred = Prediction(
            event_id="ev1", sport="baseball_mlb", outcome="Yankees",
            predicted_prob=0.60, sharp_prob=0.55, ensemble_prob=0.58,
        )
        self.tracker.record_prediction(pred)
        assert len(self.tracker.predictions) == 1

        resolved = self.tracker.resolve_prediction("ev1", "Yankees", 1)
        assert resolved is True
        assert self.tracker.predictions[0].actual_outcome == 1

    def test_resolve_nonexistent_returns_false(self):
        assert self.tracker.resolve_prediction("fake", "Team", 1) is False

    def test_generate_report_empty(self):
        report = self.tracker.generate_report()
        assert report.n_predictions == 0
        assert report.n_resolved == 0
        assert report.brier_ensemble is None

    def test_generate_report_with_data(self):
        # Create and resolve several predictions
        for i, (prob, outcome) in enumerate([
            (0.70, 1), (0.30, 0), (0.80, 1), (0.20, 0), (0.60, 1),
        ]):
            pred = Prediction(
                event_id=f"ev{i}", sport="baseball_mlb", outcome="Team",
                predicted_prob=prob, sharp_prob=prob - 0.05,
                ensemble_prob=prob,
            )
            self.tracker.record_prediction(pred)
            self.tracker.resolve_prediction(f"ev{i}", "Team", outcome)

        report = self.tracker.generate_report()
        assert report.n_resolved == 5
        assert report.brier_ensemble is not None
        assert report.brier_ensemble < 0.25  # Better than random

    def test_sport_breakdown(self):
        for sport in ["baseball_mlb", "mma_mixed_martial_arts"]:
            pred = Prediction(
                event_id=f"ev_{sport}", sport=sport, outcome="A",
                predicted_prob=0.60, sharp_prob=0.55, ensemble_prob=0.58,
            )
            self.tracker.record_prediction(pred)
            self.tracker.resolve_prediction(f"ev_{sport}", "A", 1)

        report = self.tracker.generate_report()
        assert "baseball_mlb" in report.sport_breakdown
        assert "mma_mixed_martial_arts" in report.sport_breakdown

    def test_rolling_brier_insufficient_data(self):
        assert self.tracker.rolling_brier(window=100) is None

    def test_should_increase_model_weight_insufficient_data(self):
        assert self.tracker.should_increase_model_weight() is False


class TestBacktester:
    def test_run_backtest(self):
        predictions = []
        for i in range(100):
            pred = Prediction(
                event_id=f"ev{i}", sport="baseball_mlb", outcome="Team",
                predicted_prob=0.60, sharp_prob=0.55, ensemble_prob=0.58,
                actual_outcome=1 if i % 2 == 0 else 0,  # 50% win rate
            )
            predictions.append(pred)

        bt = Backtester()
        results = bt.run_backtest(predictions, window_size=20, step_size=5)
        assert len(results) > 0
        assert all("brier_score" in r for r in results)

    def test_backtest_summary(self):
        predictions = [
            Prediction(
                event_id=f"ev{i}", sport="baseball_mlb", outcome="Team",
                predicted_prob=0.65, sharp_prob=0.60, ensemble_prob=0.63,
                actual_outcome=1 if i < 65 else 0,
            )
            for i in range(100)
        ]

        bt = Backtester()
        bt.run_backtest(predictions, window_size=20, step_size=5)
        summary = bt.summary()
        assert "mean_brier" in summary
        assert "calibrated" in summary
