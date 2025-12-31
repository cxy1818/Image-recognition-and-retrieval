import io, os, queue, threading, time, tempfile
import sys
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path
from PIL import Image, ImageGrab
import torch

from gui_result import show_result
from search import find_sticker, switch_database
from build_index import build_index_gui

def get_console_window():
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    return kernel32.GetConsoleWindow()

def toggle_console(visible: bool):
    hwnd = get_console_window()
    if hwnd:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        SW_HIDE = 0
        SW_SHOW = 5
        user32.ShowWindow(hwnd, SW_SHOW if visible else SW_HIDE)

def _candidate_base_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
    dirs.append(Path.cwd())
    dirs.append(Path(__file__).resolve().parent)
    
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        s = str(d)
        if s not in seen:
            seen.add(s)
            out.append(d)
    return out

def resource_path(relative_path: str) -> Path:
    # 遍历候选目录查找文件
    for base in _candidate_base_dirs():
        p = base / relative_path
        if p.exists():
            return p
    # 如果找不到，返回第一个候选目录下的路径（报错用）
    return _candidate_base_dirs()[0] / relative_path

def check_license_or_exit() -> str:
    dll_path = resource_path("license_verify.dll")
    if not dll_path.exists():
        messagebox.showerror("授权错误", "未找到 license_verify.dll")
        sys.exit(1)
    try:
        dll = ctypes.WinDLL(str(dll_path))
    except OSError:
        messagebox.showerror("授权错误", "无法加载 license_verify.dll")
        sys.exit(1)

    try:
        verify = dll.VerifyLicense
        verify.argtypes = [ctypes.c_char_p, ctypes.c_int]
        verify.restype = ctypes.c_int
    except AttributeError:
        messagebox.showerror("授权错误", "DLL 接口不匹配")
        sys.exit(1)

    buf = ctypes.create_string_buffer(32)
    ret = verify(buf, len(buf))

    if ret == 0:
        # 授权成功
        expire = buf.value.decode(errors="ignore")
        print(f"License OK, expire at {expire}")
        return expire

    if ret == 1:
        messagebox.showerror("授权失败", "激活码无效或未授权")
        sys.exit(1)

    if ret == 2:
        expire = buf.value.decode(errors="ignore")
        messagebox.showerror("授权过期", f"授权已过期\n到期时间：{expire}")
        sys.exit(1)

    messagebox.showerror("授权错误", "未知授权状态")
    sys.exit(1)

tmp_img = str(Path(tempfile.gettempdir()) / "pic_recognize_tmp.png")
stop_flag = threading.Event()
pause_flag = threading.Event()
results_queue: "queue.Queue[list[tuple[str, float]]]" = queue.Queue()
search_lock = threading.Lock()
DB_DIR: Path = None

#检测设备
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
GPU_NAME = None
if DEVICE == "cuda":
    GPU_NAME = torch.cuda.get_device_name(0)
    print("正在使用NVIDIA CUDA加速")   
    print(f"使用的GPU: {GPU_NAME}")
else:
    print("正在使用CPU处理")


# 新建数据库流程
def create_new_db_from_gui(root, callback):
    if root is None:
        root = tk.Tk()
        root.withdraw()
    sticker_dir = filedialog.askdirectory(title="选择贴纸图片文件夹", parent=root)
    if not sticker_dir:
        messagebox.showerror("错误", "未选择文件夹！", parent=root)
        return

    db_name = simpledialog.askstring("数据库名称", "请输入数据库名称：", parent=root)
    if not db_name:
        messagebox.showerror("错误", "未输入数据库名称！", parent=root)
        return

    def build_task():
        try:
            db_dir = build_index_gui(Path(sticker_dir), db_name, device=DEVICE)
            root.after(0, lambda: callback(db_dir))
        except Exception as e:
            root.after(0, lambda: messagebox.showerror("错误", f"建库失败：{e}", parent=root))

    threading.Thread(target=build_task, daemon=True).start()

# 剪贴板监听线程
def clipboard_watcher():
    last_hash = None
    while not stop_flag.is_set():
        if pause_flag.is_set():
            time.sleep(0.2)
            continue
        try:
            img = ImageGrab.grabclipboard()
            if isinstance(img, Image.Image):
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                h = hash(buf.getvalue())
                if h != last_hash:
                    last_hash = h
                    img.save(tmp_img, 'PNG')
                    if DB_DIR is not None:
                        with search_lock:
                            matches = find_sticker(tmp_img, DB_DIR)
                        results_queue.put(matches)
            time.sleep(1)
        except Exception:
            pass

def open_folder():
    global DB_DIR
    if DB_DIR is None:
        messagebox.showerror("错误", "未选择数据库！")
        return
    sticker_dir = DB_DIR / "stickers"
    if sticker_dir.exists():
        os.startfile(sticker_dir)
    else:
        messagebox.showerror("错误", "贴纸文件夹不存在！")

class ControlPanelUI:
    def __init__(self, expire_date: str):
        self.expire_date = expire_date
        self.bg = "#f0f0f5"
        self.card_bg = "#ffffff"
        self.divider = "#d9d9de"
        self.text = "#333333"
        self.subtext = "#666666"

        self.root = tk.Tk()
        self.root.title("图片识别 作者 Mr. Chen")
        self.root.configure(bg=self.bg)
        self.root.resizable(True, True)

        self.show_thumb_var = tk.BooleanVar(value=False)

        container = tk.Frame(self.root, bg=self.bg, padx=20, pady=20)
        container.pack(fill="both", expand=True)

        topbar = tk.Frame(container, bg=self.bg)
        topbar.pack(fill="x")

        title = tk.Label(
            topbar,
            text="🏞️ Pic Recognize",
            font=("Segoe UI", 13, "bold"),
            bg=self.bg,
            fg=self.text,
        )
        title.pack(side="left")

        expire_label = tk.Label(
            topbar,
            text=f"授权到期：{self.expire_date}",
            font=("Segoe UI", 10),
            bg=self.bg,
            fg=self.subtext
        )
        expire_label.pack(side="right")

        self._add_divider(container)

        self._build_database_section(container)
        self._add_divider(container)
        self._build_listener_section(container)
        self._add_divider(container)
        self._build_device_section(container)
        self._add_divider(container)
        self._build_exit_section(container)

        self.root.bind("<Escape>", lambda e: self.quit_app())
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

        self._refresh_db_ui()
        self._refresh_listener_ui()
        self._center_window(min_w=420)

        self.root.after(200, self._poll_results)
        self.root.after(300, self._auto_open_db_selector)
        
        self.start_license_check_thread()

    def run(self):
        self.root.mainloop()

    def start_license_check_thread(self):
        def task():
            while not stop_flag.is_set():
                time.sleep(3600) #每1小时检测授权
                try:
                    check_license_or_exit()
                except SystemExit:
                    os._exit(1)
                except Exception:
                    pass
        threading.Thread(target=task, daemon=True).start()

    def _center_window(self, min_w: int = 360):
        self.root.update_idletasks()
        w = max(min_w, self.root.winfo_width())
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _add_divider(self, parent):
        tk.Frame(parent, bg=self.divider, height=1).pack(fill="x", pady=14)

    def _build_section_title(self, parent, text: str):
        tk.Label(parent, text=text, font=("Segoe UI", 11, "bold"), bg=self.bg, fg=self.text).pack(
            anchor="w", pady=(0, 8)
        )

    def _build_database_section(self, parent):
        self._build_section_title(parent, "📁 数据库面板")

        card = tk.Frame(parent, bg=self.card_bg, padx=14, pady=12)
        card.pack(fill="x")

        self.db_name_var = tk.StringVar(value="未选择")
        db_name_label = tk.Label(
            card,
            textvariable=self.db_name_var,
            font=("Segoe UI", 12),
            bg=self.card_bg,
            fg=self.text,
            anchor="w",
        )
        db_name_label.pack(fill="x")

        actions = tk.Frame(parent, bg=self.bg)
        actions.pack(fill="x", pady=(10, 0))

        switch_btn = tk.Button(
            actions,
            text="切换数据库",
            width=12,
            padx=10,
            pady=6,
            bg="#1976D2",
            fg="white",
            relief="flat",
            font=("Segoe UI", 11),
            command=self.open_database_selector,
        )
        switch_btn.pack(side="left")
        switch_btn.bind("<Enter>", lambda e: switch_btn.configure(bg="#1565C0"))
        switch_btn.bind("<Leave>", lambda e: switch_btn.configure(bg="#1976D2"))

        self.open_folder_btn = tk.Button(
            actions,
            text="打开文件夹",
            width=10,
            padx=10,
            pady=6,
            bg="#ffffff",
            fg=self.text,
            relief="flat",
            font=("Segoe UI", 11),
            command=open_folder,
        )
        self.open_folder_btn.pack(side="left", padx=(10, 0))
        self.open_folder_btn.bind("<Enter>", lambda e: self.open_folder_btn.configure(bg="#e6f0ff"))
        self.open_folder_btn.bind("<Leave>", lambda e: self.open_folder_btn.configure(bg="#ffffff"))

        new_btn = tk.Button(
            actions,
            text="新建",
            width=8,
            padx=10,
            pady=6,
            bg="#4CAF50",
            fg="white",
            relief="flat",
            font=("Segoe UI", 11),
            command=self.create_new_db,
        )
        new_btn.pack(side="left", padx=(10, 0))
        new_btn.bind("<Enter>", lambda e: new_btn.configure(bg="#45a049"))
        new_btn.bind("<Leave>", lambda e: new_btn.configure(bg="#4CAF50"))

        cb = tk.Checkbutton(
            parent,
            text="显示识别结果缩略图",
            variable=self.show_thumb_var,
            bg=self.bg,
            fg=self.text,
            activebackground=self.bg,
            activeforeground=self.text,
            font=("Segoe UI", 10),
            selectcolor="white"
        )
        cb.pack(anchor="w", pady=(8, 0))

        self.status_var = tk.StringVar(value="")
        tk.Label(parent, textvariable=self.status_var, font=("Segoe UI", 10), bg=self.bg, fg=self.subtext).pack(
            anchor="w", pady=(10, 0)
        )

    def _build_listener_section(self, parent):
        self._build_section_title(parent, "🔍 监听状态")

        row = tk.Frame(parent, bg=self.bg)
        row.pack(fill="x")

        self.listener_dot = tk.Label(row, text="●", font=("Segoe UI", 12), bg=self.bg, fg="#2e7d32")
        self.listener_dot.pack(side="left")

        self.listener_text_var = tk.StringVar(value="正在监听剪贴板")
        tk.Label(row, textvariable=self.listener_text_var, font=("Segoe UI", 11), bg=self.bg, fg=self.text).pack(
            side="left", padx=(8, 0)
        )

        self.pause_btn = tk.Button(
            parent,
            text="⏸ 暂停监听",
            width=14,
            padx=10,
            pady=6,
            bg="#ffffff",
            fg=self.text,
            relief="flat",
            font=("Segoe UI", 11),
            command=self.toggle_pause,
        )
        self.pause_btn.pack(anchor="w", pady=(10, 0))
        self.pause_btn.bind("<Enter>", lambda e: self.pause_btn.configure(bg="#e6f0ff"))
        self.pause_btn.bind("<Leave>", lambda e: self.pause_btn.configure(bg="#ffffff"))

    def _build_device_section(self, parent):
        self._build_section_title(parent, "⚛️计算设备")

        row = tk.Frame(parent, bg=self.bg)
        row.pack(fill="x")

        info_frame = tk.Frame(row, bg=self.bg)
        info_frame.pack(side="left")

        if DEVICE == "cuda":
            primary = "NVIDIA CUDA 加速"
            secondary = GPU_NAME or "GPU"
        else:
            primary = "正在使用CPU 处理"
            secondary = "🙂"

        tk.Label(info_frame, text=primary, font=("Segoe UI", 11), bg=self.bg, fg=self.text).pack(anchor="w")
        tk.Label(info_frame, text=secondary, font=("Segoe UI", 10), bg=self.bg, fg=self.subtext).pack(anchor="w", pady=(4, 0))

        self.console_visible = True
        def toggle_console_click():
            self.console_visible = not self.console_visible
            toggle_console(self.console_visible)
            console_btn.config(text="显示命令行" if not self.console_visible else "隐藏命令行")

        console_btn = tk.Button(
            row,
            text="隐藏命令行",
            width=10,
            padx=10,
            pady=6,
            bg="#ffffff",
            fg=self.text,
            relief="flat",
            font=("Segoe UI", 10),
            command=toggle_console_click
        )
        console_btn.pack(side="right", padx=(10, 0))
        console_btn.bind("<Enter>", lambda e: console_btn.configure(bg="#e6f0ff"))
        console_btn.bind("<Leave>", lambda e: console_btn.configure(bg="#ffffff"))

    def _build_exit_section(self, parent):
        quit_btn = tk.Button(
            parent,
            text="❌ 退出程序",
            width=18,
            padx=10,
            pady=8,
            bg="#D32F2F",
            fg="white",
            relief="flat",
            font=("Segoe UI", 11, "bold"),
            command=self.quit_app,
        )
        quit_btn.pack(anchor="w")
        quit_btn.bind("<Enter>", lambda e: quit_btn.configure(bg="#C62828"))
        quit_btn.bind("<Leave>", lambda e: quit_btn.configure(bg="#D32F2F"))

    def _poll_results(self):
        try:
            while True:
                results = results_queue.get_nowait()
                show_result(results, db_dir=DB_DIR, show_thumb=self.show_thumb_var.get())
        except queue.Empty:
            pass
        if not stop_flag.is_set():
            self.root.after(200, self._poll_results)

    def _auto_open_db_selector(self):
        if DB_DIR is not None:
            return
        db_root = resource_path("databases")
        if not db_root.exists():
            return
        if any(d.is_dir() for d in db_root.iterdir()):
            self.open_database_selector()

    def _refresh_db_ui(self):
        if DB_DIR is None:
            self.db_name_var.set("未选择")
            if hasattr(self, "open_folder_btn"):
                self.open_folder_btn.configure(state="disabled")
        else:
            self.db_name_var.set(DB_DIR.name)
            if hasattr(self, "open_folder_btn"):
                self.open_folder_btn.configure(state="normal")

    def _refresh_listener_ui(self):
        if pause_flag.is_set():
            self.listener_dot.configure(fg="#9e9e9e")
            self.listener_text_var.set("已暂停监听剪贴板")
            self.pause_btn.configure(text="▶ 恢复监听")
        else:
            self.listener_dot.configure(fg="#2e7d32")
            self.listener_text_var.set("正在监听剪贴板")
            self.pause_btn.configure(text="⏸ 暂停监听")

    def toggle_pause(self):
        if pause_flag.is_set():
            pause_flag.clear()
        else:
            pause_flag.set()
        self._refresh_listener_ui()

    def create_new_db(self):
        self.status_var.set("正在新建数据库 ...")
        def callback(db_dir: Path):
            global DB_DIR
            DB_DIR = db_dir
            self._refresh_db_ui()
            self.status_var.set(f"正在加载数据库：{db_dir.name} ...")

            def task():
                try:
                    with search_lock:
                        switch_database(db_dir)
                    self.root.after(0, lambda: self.status_var.set(f"当前数据库：{db_dir.name}"))
                except Exception as e:
                    self.root.after(
                        0, lambda: messagebox.showerror("错误", f"切换数据库失败：{e}", parent=self.root)
                    )
                    self.root.after(0, lambda: self.status_var.set(""))

            threading.Thread(target=task, daemon=True).start()
        create_new_db_from_gui(self.root, lambda d: self.root.after(0, lambda: callback(d)))

    def open_database_selector(self):
        db_root = resource_path("databases")
        db_root.mkdir(exist_ok=True)

        win = tk.Toplevel(self.root)
        win.title("选择数据库")
        win.configure(bg=self.bg)
        win.resizable(False, False)

        container = tk.Frame(win, bg=self.bg, padx=20, pady=20)
        container.pack(fill="both", expand=True)

        tk.Label(container, text="请选择数据库：", font=("Segoe UI", 13, "bold"), bg=self.bg, fg=self.text).pack(
            anchor="w", pady=(0, 12)
        )

        list_frame = tk.Frame(container, bg=self.bg)
        list_frame.pack(fill="x")

        status_var = tk.StringVar(value="")
        tk.Label(container, textvariable=status_var, font=("Segoe UI", 10), bg=self.bg, fg=self.subtext).pack(
            anchor="w", pady=(10, 0)
        )

        def choose_db(db_name: str):
            target_dir = db_root / db_name
            status_var.set(f"正在切换到数据库：{db_name} ...")
            self.status_var.set(f"正在切换到数据库：{db_name} ...")

            def task():
                try:
                    with search_lock:
                        switch_database(target_dir)
                    def done():
                        global DB_DIR
                        DB_DIR = target_dir
                        self._refresh_db_ui()
                        self.status_var.set(f"当前数据库：{db_name}")
                        win.destroy()
                    self.root.after(0, done)
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("错误", f"切换数据库失败：{e}", parent=self.root))
                    self.root.after(0, lambda: status_var.set(""))
                    self.root.after(0, lambda: self.status_var.set(""))

            threading.Thread(target=task, daemon=True).start()

        dbs = [d.name for d in db_root.iterdir() if d.is_dir()]
        dbs.sort()
        if not dbs:
            tk.Label(list_frame, text="未找到数据库，请先点击“新建”。", font=("Segoe UI", 10), bg=self.bg, fg=self.subtext).pack(
                anchor="w"
            )
        else:
            for db_name in dbs:
                btn = tk.Button(
                    list_frame,
                    text=db_name,
                    anchor="w",
                    justify="left",
                    padx=10,
                    pady=6,
                    bg=self.card_bg,
                    fg=self.text,
                    relief="flat",
                    font=("Segoe UI", 11),
                    command=lambda n=db_name: choose_db(n),
                )
                btn.pack(fill="x", pady=4)
                btn.bind("<Enter>", lambda e, b=btn: b.configure(bg="#e6f0ff"))
                btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=self.card_bg))

        actions = tk.Frame(container, bg=self.bg)
        actions.pack(fill="x", pady=(12, 0))

        new_btn = tk.Button(
            actions,
            text="新建",
            width=8,
            padx=10,
            pady=6,
            bg="#4CAF50",
            fg="white",
            relief="flat",
            font=("Segoe UI", 11),
            command=lambda: (win.destroy(), self.create_new_db()),
        )
        new_btn.pack(side="left")
        new_btn.bind("<Enter>", lambda e: new_btn.configure(bg="#45a049"))
        new_btn.bind("<Leave>", lambda e: new_btn.configure(bg="#4CAF50"))

        cancel_btn = tk.Button(
            actions,
            text="取消",
            width=8,
            padx=10,
            pady=6,
            bg="#ffffff",
            fg=self.text,
            relief="flat",
            font=("Segoe UI", 11),
            command=win.destroy,
        )
        cancel_btn.pack(side="right")
        cancel_btn.bind("<Enter>", lambda e: cancel_btn.configure(bg="#e6f0ff"))
        cancel_btn.bind("<Leave>", lambda e: cancel_btn.configure(bg="#ffffff"))

        win.bind("<Escape>", lambda e: win.destroy())
        win.transient(self.root)
        win.grab_set()

        win.update_idletasks()
        w = max(360, win.winfo_width())
        h = win.winfo_height()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3
        win.geometry(f"{w}x{h}+{x}+{y}")

    def quit_app(self):
        stop_flag.set()
        self.root.destroy()

def main():
    expire_date = check_license_or_exit()
    threading.Thread(target=clipboard_watcher, daemon=True).start()
    ControlPanelUI(expire_date).run()

if __name__ == "__main__":
    main()

