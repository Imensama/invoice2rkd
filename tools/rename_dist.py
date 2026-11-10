import os
import shutil
import sys
from pathlib import Path

base = Path(__file__).resolve().parent.parent / "dist"
src = base / "Invoice2RKD"
dst = base / "入库单生成器"
if not src.exists():
    print("未找到 dist/Invoice2RKD")
    sys.exit(1)
if dst.exists():
    shutil.rmtree(dst)
src.rename(dst)
for f in list(dst.iterdir()):
    if f.is_file() and f.suffix.lower() == ".exe":
        f.rename(dst / "入库单生成器.exe")
print(dst)
