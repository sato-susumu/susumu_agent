"""turtlesim シミュレーターデバッグモード launch ファイル。

turtlesim.launch.py の debug:=true 固定版。
ログを debug/ フォルダに保存する。

使い方:
    ros2 launch susumu_agent turtlesim_debug.launch.py
    ros2 launch susumu_agent turtlesim_debug.launch.py debug_dir:=/tmp/mydbg
    ros2 launch susumu_agent turtlesim_debug.launch.py cmd_vel_stamped:=false

cmd_vel_stamped は false がデフォルト（turtlesim 用 Twist）。
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
    cmd_vel_stamped_arg = DeclareLaunchArgument(
        "cmd_vel_stamped",
        default_value="false",
        description="true の場合 cmd_vel に TwistStamped を使う",
    )
    debug_dir_arg = DeclareLaunchArgument(
        "debug_dir",
        default_value=_DEBUG_DIR,
        description="ログの出力先ディレクトリ",
    )

    turtlesim_node = Node(
        package="turtlesim",
        executable="turtlesim_node",
        name="turtlesim",
        output="screen",
    )

    agent_node = Node(
        package="susumu_agent",
        executable="susumu_agent_node",
        name="susumu_agent",
        output="screen",
        emulate_tty=True,
        parameters=[{
            "config_path": LaunchConfiguration("config_path"),
            "robot_mode":  "real",
            "cmd_vel_stamped": LaunchConfiguration("cmd_vel_stamped"),
            "env_file":    LaunchConfiguration("env_file"),
            "debug":       True,
            "debug_dir":   LaunchConfiguration("debug_dir"),
        }],
        remappings=[
            ("/cmd_vel", "/turtle1/cmd_vel"),
        ],
    )

    return LaunchDescription([
        config_path_arg,
        env_file_arg,
        cmd_vel_stamped_arg,
        debug_dir_arg,
        LogInfo(msg="susumu_agent を起動します（turtlesim デバッグモード）..."),
        turtlesim_node,
        agent_node,
    ])
