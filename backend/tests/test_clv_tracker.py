"""Tests for the CLV (Closing Line Value) tracker."""

import pytest

from app.engine.clv_tracker import CLVTracker, CLVRecord, BookmakerProfile


class TestCLVRecording:
    def test_record_signal(self):
        tracker = CLVTracker()
        record = tracker.record_signal(
            event_id="evt_1", sport="baseball_mlb",
            bookmaker="bet365", outcome="Yankees",
            signal_odds=2.10, signal_model_prob=0.55,
            signal_edge=0.05, sharp_odds=1.95,
        )
        assert record.event_id == "evt_1"
        assert record.signal_implied_prob == pytest.approx(1 / 2.10, abs=0.001)
        assert len(tracker.records) == 1

    def test_record_closing_line(self):
        tracker = CLVTracker()
        tracker.record_signal(
            event_id="evt_1", sport="baseball_mlb",
            bookmaker="bet365", outcome="Yankees",
            signal_odds=2.10, signal_model_prob=0.55,
            signal_edge=0.05,
        )
        tracker.record_closing_line(
            event_id="evt_1", bookmaker="bet365",
            outcome="Yankees", closing_odds=1.95,
        )
        record = tracker.records[0]
        assert record.closing_odds == 1.95
        assert record.clv is not None


class TestCLVCalculation:
    def test_positive_clv(self):
        """Line shortened after signal = we caught real value."""
        tracker = CLVTracker()
        tracker.record_signal(
            event_id="evt_1", sport="baseball_mlb",
            bookmaker="bet365", outcome="Yankees",
            signal_odds=2.20, signal_model_prob=0.55,
            signal_edge=0.05,
        )
        # Line shortened (odds dropped = more likely)
        tracker.record_closing_line("evt_1", "bet365", "Yankees", closing_odds=2.00)

        record = tracker.records[0]
        # Closing implied (0.50) > signal implied (0.4545) → positive CLV
        assert record.clv > 0

    def test_negative_clv(self):
        """Line lengthened after signal = we were wrong."""
        tracker = CLVTracker()
        tracker.record_signal(
            event_id="evt_1", sport="baseball_mlb",
            bookmaker="bet365", outcome="Yankees",
            signal_odds=2.00, signal_model_prob=0.55,
            signal_edge=0.05,
        )
        # Line lengthened (odds increased = less likely)
        tracker.record_closing_line("evt_1", "bet365", "Yankees", closing_odds=2.30)

        record = tracker.records[0]
        assert record.clv < 0

    def test_clv_pct(self):
        tracker = CLVTracker()
        tracker.record_signal(
            event_id="evt_1", sport="baseball_mlb",
            bookmaker="bet365", outcome="Yankees",
            signal_odds=2.00, signal_model_prob=0.55,
            signal_edge=0.05,
        )
        tracker.record_closing_line("evt_1", "bet365", "Yankees", closing_odds=1.80)

        record = tracker.records[0]
        assert record.clv_pct is not None
        assert record.clv_pct > 0

    def test_clv_none_when_unclosed(self):
        tracker = CLVTracker()
        tracker.record_signal(
            event_id="evt_1", sport="baseball_mlb",
            bookmaker="bet365", outcome="Yankees",
            signal_odds=2.00, signal_model_prob=0.55,
            signal_edge=0.05,
        )
        assert tracker.records[0].clv is None


class TestBookmakerProfile:
    def test_profile_tracks_signals(self):
        tracker = CLVTracker()
        for i in range(5):
            tracker.record_signal(
                event_id=f"evt_{i}", sport="baseball_mlb",
                bookmaker="bet365", outcome="Yankees",
                signal_odds=2.10, signal_model_prob=0.55,
                signal_edge=0.04 + i * 0.01,
            )
        profile = tracker.bookmaker_profiles["bet365"]
        assert profile.total_signals == 5
        assert profile.mean_edge_offered > 0

    def test_softness_score_increases_with_positive_clv(self):
        tracker = CLVTracker()
        for i in range(5):
            tracker.record_signal(
                event_id=f"evt_{i}", sport="baseball_mlb",
                bookmaker="bet365", outcome="Yankees",
                signal_odds=2.20, signal_model_prob=0.55,
                signal_edge=0.05,
            )
            # All lines shorten → positive CLV
            tracker.record_closing_line(f"evt_{i}", "bet365", "Yankees", closing_odds=2.00)

        profile = tracker.bookmaker_profiles["bet365"]
        assert profile.positive_clv_count == 5
        assert profile.softness_score > 0.3


class TestCLVReport:
    def test_empty_report(self):
        tracker = CLVTracker()
        report = tracker.generate_report()
        assert report.total_signals == 0
        assert report.mean_clv is None

    def test_report_with_closed_signals(self):
        tracker = CLVTracker()
        tracker.record_signal(
            event_id="evt_1", sport="baseball_mlb",
            bookmaker="bet365", outcome="Yankees",
            signal_odds=2.20, signal_model_prob=0.55,
            signal_edge=0.05,
        )
        tracker.record_closing_line("evt_1", "bet365", "Yankees", closing_odds=2.00)

        report = tracker.generate_report()
        assert report.total_signals == 1
        assert report.signals_with_closing == 1
        assert report.mean_clv is not None
        assert report.positive_clv_pct is not None

    def test_softest_bookmakers_ranking(self):
        tracker = CLVTracker()
        # bet365 has 10 signals, all positive CLV
        for i in range(10):
            tracker.record_signal(
                event_id=f"a_{i}", sport="baseball_mlb",
                bookmaker="bet365", outcome="A",
                signal_odds=2.20, signal_model_prob=0.55,
                signal_edge=0.06,
            )
            tracker.record_closing_line(f"a_{i}", "bet365", "A", closing_odds=2.00)

        # fanduel has 10 signals, all negative CLV
        for i in range(10):
            tracker.record_signal(
                event_id=f"b_{i}", sport="baseball_mlb",
                bookmaker="fanduel", outcome="A",
                signal_odds=2.00, signal_model_prob=0.55,
                signal_edge=0.03,
            )
            tracker.record_closing_line(f"b_{i}", "fanduel", "A", closing_odds=2.20)

        softest = tracker.get_softest_bookmakers(min_signals=5)
        assert len(softest) == 2
        assert softest[0].bookmaker == "bet365"  # bet365 is softer
