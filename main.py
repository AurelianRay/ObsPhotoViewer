"""
OBS 图片浏览器 — 入口
"""

import sys
import os

# 确保项目目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import App


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
