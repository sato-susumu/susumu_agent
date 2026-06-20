import json

from click.testing import CliRunner

from susumu_agent.cli.debug_tools import cli


def test_debug_tools_parse_direct_plan():
    result = CliRunner().invoke(cli, ["parse", "一メートル進んで"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "direct"
    assert payload["tool"] == "move_robot"
    assert payload["args"]["direction"] == "forward"


def test_debug_tools_parse_with_last_command():
    last_command = json.dumps(
        {"tool": "move_robot", "direction": "forward", "speed": "medium", "duration_sec": 2.0},
        ensure_ascii=False,
    )

    result = CliRunner().invoke(cli, ["parse", "逆方向", "--last-command", last_command])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "direct"
    assert payload["tool"] == "move_robot"
    assert payload["args"]["direction"] == "backward"
