"""Tests for Poisson prediction engine."""
import pytest
from core.poisson import predict_match


def test_probabilities_sum_to_100():
    """Core invariant: win/draw/loss must sum to exactly 100.0."""
    strengths = {
        1: {"attack": 1.5, "defense": 0.8},
        2: {"attack": 0.9, "defense": 1.2},
    }
    result = predict_match(1, 2, strengths)
    total = result["home_win"] + result["draw"] + result["away_win"]
    assert total == 100.0, f"Sum was {total}"


def test_stronger_team_favored():
    """Team with higher attack + lower opposition defense should win more."""
    strengths = {
        1: {"attack": 2.0, "defense": 0.5},  # strong team
        2: {"attack": 0.5, "defense": 2.0},  # weak team
    }
    result = predict_match(1, 2, strengths)
    assert result["home_win"] > result["away_win"]


def test_equal_teams_balanced():
    """Equal teams should produce roughly balanced outcome."""
    strengths = {
        1: {"attack": 1.0, "defense": 1.0},
        2: {"attack": 1.0, "defense": 1.0},
    }
    result = predict_match(1, 2, strengths)
    # Draw should be significant, no team heavily favored
    assert result["draw"] > 15.0
    assert abs(result["home_win"] - result["away_win"]) < 5.0


def test_expected_goals_positive():
    """Expected goals must always be positive."""
    strengths = {
        1: {"attack": 0.3, "defense": 2.0},
        2: {"attack": 0.3, "defense": 2.0},
    }
    result = predict_match(1, 2, strengths)
    assert result["exp_home_goals"] > 0
    assert result["exp_away_goals"] > 0


def test_default_strengths_when_missing():
    """Missing team defaults to 1.0/1.0 — should not crash."""
    result = predict_match(999, 888, strengths={})
    assert result["home_win"] + result["draw"] + result["away_win"] == 100.0
