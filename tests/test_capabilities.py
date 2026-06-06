import math
import pytest
from susumu_agent.capabilities import (
    SPEED_MAP, clamp_duration, clamp_angle,
    angle_to_duration, MAX_DURATION_SEC, MAX_ANGLE_DEG,
)


def test_speed_map_values():
    assert SPEED_MAP["low"]["linear"] == pytest.approx(0.1)
    assert SPEED_MAP["medium"]["linear"] == pytest.approx(0.3)
    assert SPEED_MAP["high"]["linear"] == pytest.approx(0.5)


def test_clamp_duration_upper():
    assert clamp_duration(99.0) == MAX_DURATION_SEC


def test_clamp_duration_lower():
    assert clamp_duration(0.0) == pytest.approx(0.1)


def test_clamp_angle_upper():
    assert clamp_angle(720.0) == MAX_ANGLE_DEG


def test_clamp_angle_lower():
    assert clamp_angle(-720.0) == -MAX_ANGLE_DEG


def test_angle_to_duration_90():
    dur = angle_to_duration(90.0, "medium")
    expected = math.radians(90) / SPEED_MAP["medium"]["angular"]
    assert dur == pytest.approx(expected, rel=1e-3)


def test_angle_to_duration_180():
    dur = angle_to_duration(180.0, "medium")
    expected = math.radians(180) / SPEED_MAP["medium"]["angular"]
    assert dur == pytest.approx(expected, rel=1e-3)
