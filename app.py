import os
import sys
import traceback
from pathlib import Path


def _write_error_log(text: str):
    try:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Invoice2RKD"
        base.mkdir(parents=True, exist_ok=True)
        with open(base / "error.log", "a", encoding="utf-8") as f:
            f.write(text)
            f.write("\n" + "=" * 80 + "\n")
    except Exception:
        pass


def main():
    try:
        from invoice2rkd.cli import main as cli_main

        return cli_main()
    except Exception:
        text = traceback.format_exc()
        _write_error_log(text)
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "程序出错",
                "程序遇到错误，已写入日志：\n"
                + str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Invoice2RKD" / "error.log")
                + "\n\n"
                + text[-2000:],
            )
            root.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
