# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['D:\\obs'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'boto3',
        'botocore',
        'yaml',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 科学计算（绝不依赖）
        'matplotlib', 'numpy', 'scipy', 'pandas',
        # 测试/文档
        'tkinter.test', 'unittest', 'test', 'lib2to3', 'pydoc', 'doctest', 'pdb',
        # 开发工具
        'pip', 'setuptools', 'wheel', 'distutils',
        # 第三方日志（不用）
        'loguru',
        # 不需要的 GUI
        'turtle', 'idlelib',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OBSImageBrowser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='x86_64',
    codesign_identity=None,
    entitlements_file=None,
)
