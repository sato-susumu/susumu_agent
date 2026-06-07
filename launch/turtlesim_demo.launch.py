"""turtlesim エージェントデモ用 launch ファイル。

turtlesim_node を起動し、/from_human に流したデモ入力をエージェントが処理する。
デモ完了後に turtlesim を終了しプロセス全体も終了する。

使い方:
    ros2 launch susumu_agent turtlesim_demo.launch.py
    ros2 launch susumu_agent turtlesim_demo.launch.py debug:=true
    ros2 launch susumu_agent turtlesim_demo.launch.py debug:=true debug_dir:=/tmp/mydbg
    ros2 launch susumu_agent turtlesim_demo.launch.py cmd_vel_stamped:=false

cmd_vel_stamped は false がデフォルト（turtlesim 用 Twist）。
/from_human と /to_human は std_msgs/String。
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
    cmd_vel_stamped_arg = DeclareLaunchArgument(
        "cmd_vel_stamped",
        default_value="false",
        description="true の場合 cmd_vel に TwistStamped を使う",
    )
    from_human_topic_arg = DeclareLaunchArgument(
        "from_human_topic",
        default_value="/from_human",
        description="人間から ADK へ渡す入力トピック（std_msgs/String）",
    )
    to_human_topic_arg = DeclareLaunchArgument(
        "to_human_topic",
        default_value="/to_human",
        description="ADK 応答の人間向け文字列トピック（std_msgs/String）",
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
    final_hold_sec_arg = DeclareLaunchArgument(
        "final_hold_sec",
        default_value="5.0",
        description="最後の /to_human 応答後、turtlesim を終了するまで待つ秒数",
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
            "cmd_vel_stamped": LaunchConfiguration("cmd_vel_stamped"),
            "from_human_topic": LaunchConfiguration("from_human_topic"),
            "to_human_topic": LaunchConfiguration("to_human_topic"),
            "env_file":    LaunchConfiguration("env_file"),
            "debug":       LaunchConfiguration("debug"),
            "debug_dir":   LaunchConfiguration("debug_dir"),
        }],
    )

    demo_feeder_node = Node(
        package="susumu_agent",
        executable="susumu_agent_demo_feeder",
        name="susumu_agent_demo_feeder",
        output="screen",
        parameters=[{
            "from_human_topic": LaunchConfiguration("from_human_topic"),
            "to_human_topic": LaunchConfiguration("to_human_topic"),
            "final_hold_sec": LaunchConfiguration("final_hold_sec"),
        }],
    )

    # feeder が全デモ入力を流し終えたら全プロセスを終了
    shutdown_on_demo_exit = RegisterEventHandler(
        OnProcessExit(
            target_action=demo_feeder_node,
            on_exit=[
                LogInfo(msg="デモ完了。turtlesim を終了します。"),
                EmitEvent(event=Shutdown()),
            ],
        )
    )

    return LaunchDescription([
        config_path_arg,
        env_file_arg,
        cmd_vel_stamped_arg,
        from_human_topic_arg,
        to_human_topic_arg,
        debug_arg,
        debug_dir_arg,
        final_hold_sec_arg,
        LogInfo(msg="turtlesim エージェントデモを起動します..."),
        turtlesim_node,
        dummy_camera_node,
        TimerAction(
            period=2.0,
            actions=[
                LogInfo(msg="エージェントデモノードを開始します..."),
                demo_node,
            ],
        ),
        TimerAction(
            period=4.0,
            actions=[
                LogInfo(msg="/from_human へのデモ入力配信を開始します..."),
                demo_feeder_node,
            ],
        ),
        shutdown_on_demo_exit,
    ])
