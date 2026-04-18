"""
Tests for MC-252 (stale listing filter) and MC-254 (days-on-market badge + freshness sort).
"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import _days_ago_str, _days_ago_class, _normalize_row


class TestDaysAgoStr:
    """MC-254: days_ago badge string formatting."""
    def test_today(self):
        assert _days_ago_str(0) == 'TODAY'

    def test_one_day_ago(self):
        assert _days_ago_str(1) == '1d ago'

    def test_week(self):
        assert _days_ago_str(7) == '7d ago'

    def test_two_weeks(self):
        assert _days_ago_str(14) == '14d'

    def test_old(self):
        assert _days_ago_str(30) == '30d'

    def test_none(self):
        assert _days_ago_str(None) == '—'


class TestDaysAgoClass:
    """MC-254: colour-coded badge classes."""
    def test_fresh_up_to_3(self):
        assert _days_ago_class(0) == 'age-fresh'
        assert _days_ago_class(1) == 'age-fresh'
        assert _days_ago_class(3) == 'age-fresh'

    def test_medium_4_to_14(self):
        assert _days_ago_class(4) == 'age-medium'
        assert _days_ago_class(7) == 'age-medium'
        assert _days_ago_class(14) == 'age-medium'

    def test_stale_over_14(self):
        assert _days_ago_class(15) == 'age-stale'
        assert _days_ago_class(30) == 'age-stale'
        assert _days_ago_class(60) == 'age-stale'

    def test_none(self):
        assert _days_ago_class(None) == 'age-neutral'


class TestNormalizeRow:
    """MC-252: is_stale field correctly parsed and exposed."""
    def test_is_stale_true_string(self):
        row = {'is_stale': 'True', 'days_ago': '35'}
        result = _normalize_row(row)
        assert result['is_stale'] is True

    def test_is_stale_false_string(self):
        row = {'is_stale': 'False', 'days_ago': '5'}
        result = _normalize_row(row)
        assert result['is_stale'] is False

    def test_is_stale_1(self):
        row = {'is_stale': '1', 'days_ago': '40'}
        result = _normalize_row(row)
        assert result['is_stale'] is True

    def test_is_stale_0(self):
        row = {'is_stale': '0', 'days_ago': '2'}
        result = _normalize_row(row)
        assert result['is_stale'] is False

    def test_days_ago_int(self):
        row = {'is_stale': 'False', 'days_ago': '7'}
        result = _normalize_row(row)
        assert result['days_ago'] == 7

    def test_days_ago_str_normalized(self):
        row = {'is_stale': 'False', 'days_ago': '3'}
        result = _normalize_row(row)
        assert result['days_ago'] == 3
        assert result['days_ago_str'] == '3d ago'
        assert result['days_ago_class'] == 'age-fresh'

    def test_days_ago_10d(self):
        row = {'is_stale': 'False', 'days_ago': '10'}
        result = _normalize_row(row)
        assert result['days_ago'] == 10
        assert result['days_ago_str'] == '10d'
        assert result['days_ago_class'] == 'age-medium'

    def test_days_ago_20d(self):
        row = {'is_stale': 'False', 'days_ago': '20'}
        result = _normalize_row(row)
        assert result['days_ago'] == 20
        assert result['days_ago_class'] == 'age-stale'

    def test_is_stale_35d(self):
        row = {'is_stale': 'True', 'days_ago': '35'}
        result = _normalize_row(row)
        assert result['is_stale'] is True
        assert result['days_ago'] == 35
        assert result['days_ago_class'] == 'age-stale'

    def test_days_ago_missing(self):
        row = {'is_stale': 'False'}
        result = _normalize_row(row)
        assert result['days_ago'] is None
        assert result['days_ago_str'] == '—'
        assert result['days_ago_class'] == 'age-neutral'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
