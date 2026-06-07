from setuptools import setup, find_packages
from glob import glob

package_name = "susumu_agent"

setup(
    name=package_name,
    version="0.0.0",
    packages=find_packages(exclude=["tests*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.py")),
        (f"share/{package_name}/config", ["config.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Sato Susumu",
    maintainer_email="75652942+sato-susumu@users.noreply.github.com",
    description="自然言語でロボットを制御するシステム（Google ADK + Gemini / Claude on Vertex AI）",
    license="MIT",
    tests_require=["pytest<8.0.0"],
    entry_points={
        "console_scripts": [
            "susumu_agent_node = susumu_agent.cli.main:main_entry",
            "susumu_agent_debug = susumu_agent.cli.debug_tools:main",
            "susumu_agent_demo = susumu_agent.demo.demo_node:main",
        ],
    },
)
