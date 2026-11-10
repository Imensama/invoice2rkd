$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$pyArgs = @(
  "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "Invoice2RKD",
  "--add-data", "data;data",
  "--collect-all", "rapidocr_onnxruntime",
  "--collect-all", "tkinterdnd2",
  "--hidden-import", "tkinterdnd2",
  "--collect-binaries", "onnxruntime",
  "--collect-all", "zxingcpp",
  "--collect-all", "pypdfium2",
  "--collect-binaries", "pypdfium2_raw",
  "--hidden-import", "pypdfium2",
  "--hidden-import", "pypdfium2_raw",
  "--collect-all", "pdfplumber",
  "--collect-all", "pdfminer",
  "--collect-all", "charset_normalizer",
  "--hidden-import", "pdfplumber",
  "--collect-all", "cv2",
  "--exclude-module", "pandas",
  "--exclude-module", "openpyxl",
  "--exclude-module", "lxml",
  "--exclude-module", "certifi",
  "--exclude-module", "urllib3",
  "--exclude-module", "sqlite3",
  "--exclude-module", "setuptools",
  "--exclude-module", "dateutil",
  "--exclude-module", "tzdata",
  "--hidden-import", "xlwt",
  "--hidden-import", "xlrd",
  "--hidden-import", "win32com.client"
)
$cnDir = python -c "import charset_normalizer, pathlib; print(pathlib.Path(charset_normalizer.__file__).parent)"
if ($LASTEXITCODE -eq 0 -and $cnDir) {
  Get-ChildItem -LiteralPath $cnDir -Filter "*.pyd" | ForEach-Object {
    $pyArgs += "--add-binary"
    $pyArgs += ($_.FullName + ";charset_normalizer")
  }
}
$pyArgs += "app.py"
& python @pyArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
python tools\rename_dist.py
python tools\clean_dist.py
Write-Host "Build complete: $root\dist\入库单生成器\入库单生成器.exe"
