"""シミュレーションモード専用 launch ファイル（ROS2 不要・開発確認用）。

ROS2 launch を使わず直接起動する場合:
    python3 main.py

ROS2 launch 経由で起動する場合:
    ros2 launch robot_nl_controller robot_nl_simulate.launch.py
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, LogInfo
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_path_arg = DeclareLaunchArgument(
        "config_path",
        default_value=PathJoinSubstitution(
            [FindPackageShare("robot_nl_controller"), "config", "config.yaml"]
        ),
        description="設定ファイルのパス",
    )

    # simulate モードは ROS2 Node ではなく通常 Python プロセスとして起動
    simulate_proc = ExecuteProcess(
        cmd=[
            "python3",
            PathJoinSubstitution([
                FindPackageShare("robot_nl_controller"), "robot_nl_controller", "main.py"
            ]),
            LaunchConfiguration("config_path"),
        ],
        output="screen",
        emulate_tty=True,
    )

    return LaunchDescription([
        config_path_arg,
        LogInfo(msg="robot_nl_controller をシミュレーションモードで起動します..."),
        simulate_proc,
    ])
