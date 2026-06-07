"""turtlesim エージェントデモ用 launch ファイル。

turtlesim_node を起動し、エージェント（LLM）を使った自動デモを実行する。
デモ完了後に turtlesim を終了しプロセス全体も終了する。

使い方:
    ros2 launch susumu_agent turtlesim_demo.launch.py
    ros2 launch susumu_agent turtlesim_demo.launch.py debug:=true
    ros2 launch susumu_agent turtlesim_demo.launch.py debug:=true debug_dir:=/tmp/mydbg
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
    debug_arg = DeclareLaunchArgument(
        "debug",
        default_value="false",
        description="true にするとログをファイルに保存し turtlesim 画面を録画する",
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

    # ダミーカメラ: image_tools/cam2image の burger_mode（著作権フリーのアニメ画像）を
    # /camera/image_raw にリマップして配信する
    dummy_camera_node = Node(
        package="image_tools",
        executable="cam2image",
        name="dummy_camera",
        output="screen",
        parameters=[{"burger_mode": True, "publish_rate": 10.0}],
        remappings=[("/image", "/camera/image_raw")],
    )

    demo_node = Node(
        package="susumu_agent",
        executable="susumu_agent_demo",
        name="susumu_agent_demo",
        output="screen",
        parameters=[{
            "config_path": LaunchConfiguration("config_path"),
            "env_file":    LaunchConfiguration("env_file"),
            "debug":       LaunchConfiguration("debug"),
            "debug_dir":   LaunchConfiguration("debug_dir"),
        }],
    )

    # デモ完了後に全プロセスを終了
    shutdown_on_demo_exit = RegisterEventHandler(
        OnProcessExit(
            target_action=demo_node,
            on_exit=[
                LogInfo(msg="デモ完了。turtlesim を終了します。"),
                EmitEvent(event=Shutdown()),
            ],
        )
    )

    return LaunchDescription([
        config_path_arg,
        env_file_arg,
        debug_arg,
        debug_dir_arg,
        LogInfo(msg="turtlesim エージェントデモを起動します..."),
        turtlesim_node,
        dummy_camera_node,
        TimerAction(
            period=2.0,
            actions=[
                LogInfo(msg="エージェントデモを開始します..."),
                demo_node,
            ],
        ),
        shutdown_on_demo_exit,
    ])
