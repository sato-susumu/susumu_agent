"""ROS2 パッケージとして使う場合の setup.py。"""
from setuptools import setup, find_packages
import os
from glob import glob

package_name = "robot_nl_controller"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["tests*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
        (f"share/{package_name}/config", ["config.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="your_name",
    maintainer_email="your_email@example.com",
    description="自然言語でロボットを制御するシステム（Google ADK + Claude on Vertex AI）",
    license="MIT",
    entry_points={
        "console_scripts": [
            "robot_nl_main = robot_nl_controller.main:main_entry",
        ],
    },
)
