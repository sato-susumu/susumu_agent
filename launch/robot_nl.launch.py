"""ROS2 launch ファイル。

使い方:
    ros2 launch robot_nl_controller robot_nl.launch.py
    ros2 launch robot_nl_controller robot_nl.launch.py config_path:=/path/to/config.yaml
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config_path_arg = DeclareLaunchArgument(
        "config_path",
        default_value=PathJoinSubstitution(
            [FindPackageShare("robot_nl_controller"), "config", "config.yaml"]
        ),
        description="設定ファイルのパス",
    )

    robot_nl_node = Node(
        package="robot_nl_controller",
        executable="robot_nl_main",
        name="robot_nl_controller",
        output="screen",
        emulate_tty=True,
        parameters=[
            {"config_path": LaunchConfiguration("config_path")}
        ],
    )

    return LaunchDescription([
        config_path_arg,
        LogInfo(msg="robot_nl_controller を起動します..."),
        robot_nl_node,
    ])
