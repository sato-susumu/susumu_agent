"""turtlesim エージェントデモ（デバッグモード）launch ファイル。

turtlesim_demo.launch.py の debug:=true 固定版。
ログ・ラベル・録画動画を debug/ フォルダに保存する。
デモ完了後に turtlesim を終了しプロセス全体も終了する。

使い方:
    ros2 launch susumu_agent turtlesim_demo_debug.launch.py
    ros2 launch susumu_agent turtlesim_demo_debug.launch.py debug_dir:=/tmp/mydbg
"""
_DEBUG_DIR = '/home/taro/ros2_ws/src/susumu_agent/debug'
_ENV_FILE = '/home/taro/ros2_ws/src/susumu_agent/.env'

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument, LogInfo, TimerAction,
    RegisterEventHandler, EmitEvent,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
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
    debug_dir_arg = DeclareLaunchArgument(
        "debug_dir",
        default_value=_DEBUG_DIR,
        description="ログ・動画の出力先ディレクトリ",
    )

    turtlesim_node = Node(
        package="turtlesim",
        executable="turtlesim_node",
        name="turtlesim",
        output="screen",
    )

    demo_node = Node(
        package="susumu_agent",
        executable="susumu_agent_demo",
        name="susumu_agent_demo",
        output="screen",
        parameters=[{
            "config_path": LaunchConfiguration("config_path"),
            "env_file":    LaunchConfiguration("env_file"),
            "debug":       "true",
            "debug_dir":   LaunchConfiguration("debug_dir"),
        }],
    )

    shutdown_on_demo_exit = RegisterEventHandler(
        OnProcessExit(
            target_action=demo_node,
            on_exit=[
                LogInfo(msg="デモ完了（デバッグ）。turtlesim を終了します。"),
                EmitEvent(event=Shutdown()),
            ],
        )
    )

    return LaunchDescription([
        config_path_arg,
        env_file_arg,
        debug_dir_arg,
        LogInfo(msg="turtlesim エージェントデモ（デバッグモード）を起動します..."),
        turtlesim_node,
        TimerAction(
            period=2.0,
            actions=[
                LogInfo(msg="エージェントデモ（デバッグモード）を開始します..."),
                demo_node,
            ],
        ),
        shutdown_on_demo_exit,
    ])
