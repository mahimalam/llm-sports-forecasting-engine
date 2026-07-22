"""Tests for AI core: circuit breaker + schema validation."""
import pytest
from pydantic import ValidationError
from core.ai_core import MatchAnalysis, CircuitBreaker


def test_circuit_breaker_opens_after_3_failures():
    b = CircuitBreaker(max_failures=3)
    assert not b.is_open
    b.record_failure()
    b.record_failure()
    assert not b.is_open
    b.record_failure()
    assert b.is_open


def test_circuit_breaker_resets_on_success():
    b = CircuitBreaker(max_failures=3)
    b.record_failure()
    b.record_failure()
    b.record_success()
    assert not b.is_open
    assert b.failures == 0


def test_circuit_breaker_normalize():
    b = CircuitBreaker()
    result = b.normalize_prediction(50, 30, 20)
    assert result["home_win"] + result["draw"] + result["away_win"] == 100.0


def test_match_analysis_rejects_bad_sum():
    with pytest.raises(ValidationError):
        MatchAnalysis(
            match_id=1, headline="Test", summary="Test summary",
            home_win=50.0, draw=30.0, away_win=30.0,  # sum=110
            key_factors=["pace"], predicted_scoreline="2-1",
        )


def test_match_analysis_accepts_valid():
    m = MatchAnalysis(
        match_id=1, headline="Brazil vs Germany", summary="Close match expected",
        home_win=45.0, draw=25.0, away_win=30.0,
        key_factors=["home advantage", "key player return"],
        predicted_scoreline="2-1",
    )
    assert m.home_win + m.draw + m.away_win == 100.0


def test_key_factors_truncated_to_5():
    m = MatchAnalysis(
        match_id=1, headline="T", summary="S",
        home_win=40.0, draw=30.0, away_win=30.0,
        key_factors=["a", "b", "c", "d", "e", "f", "g"],
        predicted_scoreline="1-0",
    )
    assert len(m.key_factors) == 5
