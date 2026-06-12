"""/from_human 送信 GUI を起動する launch ファイル。

使い方:
    ros2 launch susumu_agent gui.launch.py
    ros2 launch susumu_agent gui.launch.py from_human_topic:=/from_human
"""
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from launch import LaunchDescription


def generate_launch_description():
    args = [
        DeclareLaunchArgument("from_human_topic",  default_value="/from_human",  description="/from_human トピック名"),
        DeclareLaunchArgument("to_human_topic",    default_value="/to_human",    description="/to_human トピック名"),
        DeclareLaunchArgument("agent_event_topic", default_value="/agent_event", description="/agent_event トピック名"),
        DeclareLaunchArgument("stt_event_topic",   default_value="/stt_event",   description="/stt_event トピック名"),
    ]

    gui_node = Node(
        package="susumu_agent",
        executable="susumu_agent_gui",
        name="susumu_agent_gui",
        output="screen",
        emulate_tty=True,
        parameters=[{
            "from_human_topic":  LaunchConfiguration("from_human_topic"),
            "to_human_topic":    LaunchConfiguration("to_human_topic"),
            "agent_event_topic": LaunchConfiguration("agent_event_topic"),
            "stt_event_topic":   LaunchConfiguration("stt_event_topic"),
        }],
    )

    return LaunchDescription([*args, gui_node])
