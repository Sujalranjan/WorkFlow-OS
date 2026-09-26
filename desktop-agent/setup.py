"""Desktop agent package configuration."""

from setuptools import setup, find_packages

setup(
    name="workflowos-desktop-agent",
    version="0.1.0",
    description="WorkFlowOS Desktop Activity Agent package",
    packages=find_packages(),
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "workflowos-agent=desktop_agent.agent:main",
        ],
    },
)
