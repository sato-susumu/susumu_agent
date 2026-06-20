import asyncio

from susumu_agent.agent.tools import RobotTools
from susumu_agent.business.shared_state import get_state


class _FakeRobot:
    async def move(self, direction, speed, duration_sec):
        return None

    async def rotate(self, angle_deg, speed, continuous=False, duration_sec=0.0):
        return None

    async def curve(self, direction, turn, speed, duration_sec):
        return None

    def stop(self):
        return None

    def get_status(self):
        return {}


class _FakeCamera:
    def get_latest_image(self):
        return {"status": "error", "reason": "not used"}


class _FakeSessionStore:
    def append_command_log(self, entry):
        return None


class _FakeMacroStore:
    def list_macros(self):
        return []

    def save_macro(self, name, steps):
        return None

    def delete_macro(self, name):
        return False

    def get_macro(self, name):
        return None


def test_execute_sequence_records_sequence_as_last_command():
    state = get_state()
    state.stop_event.clear()
    state.last_command = None
    tools = RobotTools(
        robot=_FakeRobot(),
        camera=_FakeCamera(),
        session_store=_FakeSessionStore(),
        macro_store=_FakeMacroStore(),
    )
    steps = [
        {"type": "move", "direction": "forward", "speed": "medium", "duration_sec": 1.0},
        {"type": "rotate", "angle_deg": -90.0, "speed": "medium"},
    ]

    result = asyncio.run(tools.execute_sequence(steps))

    assert result["status"] == "ok"
    assert state.last_command == {"tool": "execute_sequence", "steps": steps, "loop": False}
