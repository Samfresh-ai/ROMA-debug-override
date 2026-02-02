"""Setup configuration for roma-debug."""

from setuptools import setup, find_packages

setup(
    name="roma-debug",
    version="0.1.0",
    description="Standalone CLI debugging tool powered by Gemini",
    author="ROMA Team",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "click>=8.0.0",
        "pydantic>=2.5.0",
        "google-genai>=1.0.0",
        "rich>=13.0.0",
        "fastapi>=0.109.0",
        "uvicorn>=0.27.0",
        "python-dotenv>=1.0.0",
        # V2: Multi-language support
        "tree-sitter>=0.23.0",
        "tree-sitter-python>=0.23.0",
        "tree-sitter-javascript>=0.23.0",
        "tree-sitter-typescript>=0.23.0",
        "tree-sitter-go>=0.23.0",
        "tree-sitter-rust>=0.23.0",
        "tree-sitter-java>=0.23.0",
    ],
    entry_points={
        "console_scripts": [
            "roma=roma_debug.main:cli",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
