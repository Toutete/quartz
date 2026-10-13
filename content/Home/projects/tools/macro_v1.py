"""Schedule one mouse click and an optional Enter key press with a Tkinter GUI.

Install: python -m pip install pyautogui
Run:     python macro_v1.py
"""

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk


class MacroApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("예약 클릭 매크로")
        root.resizable(False, False)

        default_time = datetime.now() + timedelta(minutes=2)
        self.date_var = tk.StringVar(value=default_time.strftime("%Y-%m-%d"))
        self.time_var = tk.StringVar(value=default_time.strftime("%H:%M:%S"))
        self.x_var = tk.StringVar()
        self.y_var = tk.StringVar()
        self.press_enter_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="날짜, 시간, 클릭 좌표를 입력하세요.")
        self.target = None
        self.position = None
        self.press_enter = True
        self.job = None
        self.gui = None

        frame = ttk.Frame(root, padding=16)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="실행 날짜 (YYYY-MM-DD)").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.date_var, width=18).grid(
            row=0, column=1, columnspan=2, sticky="ew", pady=4
        )
        ttk.Label(frame, text="실행 시간 (HH:MM:SS)").grid(row=1, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.time_var, width=18).grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=4
        )
        ttk.Label(frame, text="클릭 좌표 (X, Y)").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.x_var, width=8).grid(row=2, column=1, pady=4)
        ttk.Entry(frame, textvariable=self.y_var, width=8).grid(row=2, column=2, pady=4)

        self.capture_button = ttk.Button(
            frame, text="3초 후 마우스 위치 가져오기", command=self.capture_position
        )
        self.capture_button.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        ttk.Label(
            frame,
            text="좌표 선택 시 버튼 위에 마우스를 올리세요. 예약 중에는 로그인된 사이트 창을 앞에 두세요.",
            wraplength=310,
        ).grid(row=4, column=0, columnspan=3, sticky="w")

        self.start_button = ttk.Button(frame, text="예약 시작", command=self.start)
        self.enter_checkbox = ttk.Checkbutton(
            frame, text="클릭 후 Enter 누르기", variable=self.press_enter_var
        )
        self.enter_checkbox.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.start_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        self.cancel_button = ttk.Button(frame, text="예약 취소", command=self.cancel, state="disabled")
        self.cancel_button.grid(row=6, column=2, sticky="ew", pady=(12, 4))
        ttk.Label(frame, textvariable=self.status_var, wraplength=310).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

    def get_pyautogui(self):
        if self.gui is None:
            try:
                import pyautogui
            except ImportError:
                messagebox.showerror(
                    "라이브러리 설치 필요",
                    "터미널에서 다음 명령을 실행하세요:\npython -m pip install pyautogui",
                )
                return None
            pyautogui.FAILSAFE = True
            self.gui = pyautogui
        return self.gui

    def capture_position(self) -> None:
        if self.get_pyautogui() is None:
            return
        self.capture_button.configure(state="disabled")
        self.status_var.set("3초 안에 사이트 버튼 위로 마우스를 옮기세요.")
        self.root.iconify()
        self.root.after(3000, self.save_position)

    def save_position(self) -> None:
        try:
            x, y = self.gui.position()
            self.x_var.set(str(x))
            self.y_var.set(str(y))
            self.status_var.set(f"클릭 좌표: ({x}, {y})")
        finally:
            self.capture_button.configure(state="normal")
            self.root.deiconify()

    def start(self) -> None:
        gui = self.get_pyautogui()
        if gui is None:
            return
        try:
            target = datetime.strptime(
                f"{self.date_var.get().strip()} {self.time_var.get().strip()}",
                "%Y-%m-%d %H:%M:%S",
            )
            x, y = int(self.x_var.get()), int(self.y_var.get())
        except ValueError:
            messagebox.showerror("입력 오류", "날짜, 시간, X/Y 좌표를 형식에 맞게 입력하세요.")
            return
        if target <= datetime.now():
            messagebox.showerror("입력 오류", "미래 시간을 입력하세요.")
            return
        if not gui.onScreen(x, y):
            messagebox.showerror("입력 오류", "클릭 좌표가 화면 범위를 벗어났습니다.")
            return

        self.target = target
        self.position = (x, y)
        self.press_enter = self.press_enter_var.get()
        self.start_button.configure(state="disabled")
        self.capture_button.configure(state="disabled")
        self.enter_checkbox.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status_var.set(f"예약됨: {target:%Y-%m-%d %H:%M:%S}, 좌표 ({x}, {y})")
        self.root.iconify()
        self.check_schedule()

    def check_schedule(self) -> None:
        self.job = None
        if self.target is None:
            return
        if datetime.now() < self.target:
            self.job = self.root.after(50, self.check_schedule)
            return

        try:
            self.gui.click(*self.position)
            if self.press_enter:
                self.gui.press("enter")
        except self.gui.FailSafeException:
            self.status_var.set("중단됨: 마우스가 화면 왼쪽 위에 있습니다.")
        except Exception as exc:
            self.status_var.set(f"실행 실패: {exc}")
        else:
            action = "클릭 후 Enter를 눌렀습니다." if self.press_enter else "클릭했습니다."
            self.status_var.set(f"완료: {action}")
        finally:
            self.target = None
            self.position = None
            self.start_button.configure(state="normal")
            self.enter_checkbox.configure(state="normal")
            self.capture_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.root.deiconify()

    def cancel(self) -> None:
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None
        self.target = None
        self.position = None
        self.start_button.configure(state="normal")
        self.enter_checkbox.configure(state="normal")
        self.capture_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.status_var.set("예약을 취소했습니다.")


def main() -> None:
    root = tk.Tk()
    MacroApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
