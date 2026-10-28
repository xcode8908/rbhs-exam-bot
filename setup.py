import os
import shutil
import subprocess
from setuptools import setup

# Build hook: Automatically install Node.js dependencies during Render build step
npm_bin = shutil.which("npm")
if npm_bin:
    print("==================================================================")
    print(" [BUILD HOOK] Installing Node.js WhatsApp Gateway dependencies... ")
    print("==================================================================")
    try:
        subprocess.run([npm_bin, "install", "--omit=dev"], check=False)
    except Exception as e:
        print(f"Warning during npm install: {e}")

setup(
    name="rbhs-exam-bot",
    version="1.0.0",
    py_modules=["app"],
    install_requires=[
        "Flask>=3.0.0",
        "gunicorn>=21.2.0",
        "requests>=2.31.0",
        "python-dotenv>=1.0.0"
    ]
)
