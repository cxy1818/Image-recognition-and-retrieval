import tkinter as tk
from typing import List, Optional, Tuple
from pathlib import Path
from PIL import Image, ImageTk
import pyperclip

class ModernResultUI:
    def __init__(self, results: List[Tuple[str, float]], db_dir: Optional[Path] = None, show_thumb: bool = False, master: Optional[tk.Misc] = None):
        self._owns_mainloop = master is None
        self.root = tk.Tk() if self._owns_mainloop else tk.Toplevel(master)
        self.root.title("识别结果  作者：Mr. Chen")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0000ff")
        
        self.db_dir = db_dir
        self.show_thumb = show_thumb
        self.images = [] # Keep references

        self.container = tk.Frame(self.root, bg="#f0f0f5", padx=20, pady=20)
        self.container.pack(fill=tk.BOTH, expand=True)

        self.title_label = tk.Label(
            self.container,
            text="TOP 置信度",
            font=("Segoe UI", 14, "bold"),
            bg="#f0f0f5",
            fg="#002AE6"
        )
        self.title_label.pack(anchor="w", pady=(0, 12))

        self.buttons_frame = tk.Frame(self.container, bg="#f0f0f5")
        self.buttons_frame.pack(fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(
            self.container,
            text="",
            font=("Segoe UI", 10),
            bg="#f0f0f5",
            fg="green"
        )
        self.status_label.pack(anchor="w", pady=(10, 0))

        self.create_buttons(results)
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.center_window()
        if not self._owns_mainloop:
            self.root.lift()
        else:
            self.root.mainloop()

    def create_buttons(self, results: List[Tuple[str, float]]):
        for name, score in results:
            text = f"{name}    {score:.3f}"
            
            image = None
            if self.show_thumb and self.db_dir:
                try:
                    img_path = self.db_dir / "stickers" / name
                    if img_path.exists():
                        pil_img = Image.open(img_path)
                        pil_img.thumbnail((48, 48))
                        image = ImageTk.PhotoImage(pil_img)
                        self.images.append(image)
                except Exception:
                    pass

            btn = tk.Button(
                self.buttons_frame,
                text=text,
                image=image if image else "",
                compound="left" if image else "none",
                anchor="w",
                justify="left",
                padx=10,
                pady=6,
                bg="#ffffff",
                fg="#333333",
                relief="flat",
                font=("Segoe UI", 11),
                command=lambda n=name: self.copy_to_clipboard(n)
            )
            btn.pack(fill=tk.X, pady=4)
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#e6f0ff"))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg="#ffffff"))

    def copy_to_clipboard(self, text: str):
        pyperclip.copy(text)
        self.status_label.config(text=f"已复制 '{text}' 到剪贴板")

    def center_window(self):
        self.root.update_idletasks()
        w = max(360, self.root.winfo_width())
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")

def show_result(results: List[Tuple[str, float]], db_dir: Optional[Path] = None, show_thumb: bool = False):
    master = tk._default_root if tk._default_root is not None else None
    ModernResultUI(results, db_dir=db_dir, show_thumb=show_thumb, master=master)


# 测试
if __name__ == "__main__":
    demo_results = [("贴纸A", 0.987), ("贴纸B", 0.876), ("贴纸C", 0.765)]
    show_result(demo_results)
