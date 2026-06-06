"""実機用 launch ファイル（ROS2 必要）。

config.yaml の robot.mode を "real" に設定してから使用する。

使い方:
    ros2 launch susumu_agent real.launch.py
    ros2 launch susumu_agent real.launch.py config_path:=/path/to/config.yaml
"""
_DEBUG_DIR = '/home/taro/ros2_ws/src/susumu_agent/debug'
_ENV_FILE = '/home/taro/ros2_ws/src/susumu_agent/.env'

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_path_arg = DeclareLaunchArgument(
        "config_path",
        default_value=PathJoinSubstitution(
            [FindPackageShare("susumu_agent"), "config", "config.yaml"]
        ),
        description="設定ファイルのパス",
    )
    env_file_arg = DeclareLaunchArgument(
        "env_file",
        default_value=_ENV_FILE,
        description=".env ファイルのパス",
    )
    debug_arg = DeclareLaunchArgument(
        "debug",
        default_value="false",
        description="true にするとログをファイルに保存する",
    )
    debug_dir_arg = DeclareLaunchArgument(
        "debug_dir",
        default_value=_DEBUG_DIR,
        description="ログの出力先ディレクトリ",
    )

    agent_node = Node(
        package="susumu_agent",
        executable="susumu_agent_node",
        name="susumu_agent",
        output="screen",
        emulate_tty=True,
        parameters=[{
            "config_path": LaunchConfiguration("config_path"),
            "env_file":    LaunchConfiguration("env_file"),
            "debug":       LaunchConfiguration("debug"),
            "debug_dir":   LaunchConfiguration("debug_dir"),
        }],
    )

    return LaunchDescription([
        config_path_arg,
        env_file_arg,
        debug_arg,
        debug_dir_arg,
        LogInfo(msg="susumu_agent を起動します（実機モード）..."),
        agent_node,
    ])
