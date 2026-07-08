#!/usr/bin/env python3
"""列出所有音频设备和串口 (CLI 工具)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.audio_device import print_devices

if __name__ == "__main__":
    print_devices()
