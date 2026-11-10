import shutil
from pathlib import Path

base = Path(__file__).resolve().parent.parent / "dist" / "入库单生成器" / "_internal"
remove_dirs = [
    "pandas",
    "pandas.libs",
    "openpyxl",
    "lxml",
    "certifi",
    "setuptools",
    "dateutil",
    "tzdata",
    "pymupdf/mupdf-devel",
    "pythonwin",
]
remove_files = [
    "cv2/opencv_videoio_ffmpeg500_64.dll",
    "opencv_videoio_ffmpeg500_64.dll",
    "sqlite3.dll",
]
for rel in remove_dirs:
    p = base / rel
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
for rel in remove_files:
    p = base / rel
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
print(base)
