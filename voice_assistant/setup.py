from setuptools import setup, find_packages
import os
from glob import glob

package_name = "voice_assistant"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(include=["core", "core.*", "core.wake_up"]),
    py_modules=["voice_assistant", "voice_assistant_node", "voice_command"],
    data_files=[
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["config.yaml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="user",
    maintainer_email="user@example.com",
    description="M260C AI Voice Wake-up + Smart Dialogue Assistant",
    license="MIT",
    entry_points={
        "console_scripts": [
            "voice_assistant_node = voice_assistant_node:main",
        ],
    },
)
