#!/usr/bin/env python3
"""Orange auto-farming helper."""

from __future__ import annotations

import argparse
import ctypes
import platform
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import mss
import numpy as np
import pyautogui
from ollama import chat
from pynput import keyboard

Point = Tuple[int, int]


@dataclass
class BotConfig:
    e_cooldown: float = 2.0
    post_pick_cooldown: float = 1.5
    move_duration: float = 1.5
    turn_pixels: int = 1200
    turn_duration: float = 0.3
    turn_steps: int = 24
    click_pause: float = 0.05
    orange_min_area: int = 80
    orange_max_area: int = 80000
    orange_min_circularity: float = 0.2
    max_targets: int = 24
    dedup_radius: int = 30
    enable_llm: bool = False
    llm_model: str = "llama3.1:8b"
    idle_sleep: float = 0.05
    cycle_error_sleep: float = 0.3


class OrangeBot:
    def __init__(self, config: BotConfig) -> None:
        self.cfg = config
        self.running = False
        self.shutdown = False
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None

        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = self.cfg.click_pause

    def toggle(self) -> None:
        with self._lock:
            self.running = not self.running
            print(f"[BOT] State: {'ON' if self.running else 'OFF'}")
            if self.running and (self._worker is None or not self._worker.is_alive()):
                self._worker = threading.Thread(target=self._loop, daemon=True)
                self._worker.start()

    def stop_all(self) -> None:
        with self._lock:
            self.running = False
            self.shutdown = True
        print("[BOT] Shutdown requested")

    def _loop(self) -> None:
        print("[BOT] Worker started")
        while True:
            with self._lock:
                if self.shutdown:
                    break
                running = self.running

            if not running:
                time.sleep(self.cfg.idle_sleep)
                continue

            try:
                self._run_cycle()
            except Exception as exc:
                print(f"[BOT] Cycle error: {exc}")
                time.sleep(self.cfg.cycle_error_sleep)

        print("[BOT] Worker finished")

    def _run_cycle(self) -> None:
        pyautogui.press("e")
        time.sleep(self.cfg.e_cooldown)

        targets = self.detect_oranges()
        print(f"[BOT] Orange targets found: {len(targets)}")
        for x, y in targets:
            if not self._is_running():
                return
            pyautogui.moveTo(x, y, duration=0.025)
            pyautogui.click(button="left")

        time.sleep(self.cfg.post_pick_cooldown)
        if not self._is_running():
            return

        self.turn_right_180()
        self.hold_forward(self.cfg.move_duration)
        self.turn_right_180()
        self.hold_forward(self.cfg.move_duration)

        if self.cfg.enable_llm:
            self._llm_recovery_step()

    def _is_running(self) -> bool:
        with self._lock:
            return self.running and not self.shutdown

    def detect_oranges(self) -> List[Point]:
        frame_bgr = self._capture_frame_bgr()
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

        # Broader orange ranges: bright oranges + darker oranges.
        lower_a = np.array([3, 70, 70], dtype=np.uint8)
        upper_a = np.array([28, 255, 255], dtype=np.uint8)
        lower_b = np.array([0, 100, 90], dtype=np.uint8)
        upper_b = np.array([4, 255, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_a, upper_a) | cv2.inRange(hsv, lower_b, upper_b)

        # Clean mask while keeping partially occluded fruits.
        kernel3 = np.ones((3, 3), np.uint8)
        kernel5 = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel3, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel5, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        points: List[Point] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.cfg.orange_min_area or area > self.cfg.orange_max_area:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            circularity = (4 * np.pi * area) / (perimeter * perimeter)
            if circularity < self.cfg.orange_min_circularity:
                continue

            (_, _), radius = cv2.minEnclosingCircle(contour)
            if radius < 5 or radius > 120:
                continue

            m = cv2.moments(contour)
            if m["m00"] == 0:
                continue
            cx = int(m["m10"] / m["m00"])
            cy = int(m["m01"] / m["m00"])
            points.append((cx, cy))

        points = sorted(points, key=lambda p: (p[1], p[0]))
        points = self._dedup_points(points, self.cfg.dedup_radius)
        return points[: self.cfg.max_targets]

    @staticmethod
    def _dedup_points(points: List[Point], radius: int) -> List[Point]:
        result: List[Point] = []
        for x, y in points:
            duplicated = False
            for rx, ry in result:
                if (x - rx) * (x - rx) + (y - ry) * (y - ry) <= radius * radius:
                    duplicated = True
                    break
            if not duplicated:
                result.append((x, y))
        return result

    def _capture_frame_bgr(self) -> np.ndarray:
        # mss internals are thread-local on Windows, so create the instance
        # in the same thread where grab() is called.
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            shot = sct.grab(monitor)
        frame = np.array(shot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def turn_right_180(self) -> None:
        # In many games pyautogui moveRel may not rotate camera.
        # Use native Windows relative mouse input when available.
        if platform.system().lower().startswith("win"):
            self._turn_right_windows_relative(self.cfg.turn_pixels, self.cfg.turn_duration, self.cfg.turn_steps)
            return
        pyautogui.moveRel(self.cfg.turn_pixels, 0, duration=self.cfg.turn_duration)

    @staticmethod
    def _turn_right_windows_relative(total_dx: int, duration: float, steps: int) -> None:
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", ctypes.c_ulong), ("u", INPUT_UNION)]

        MOUSEEVENTF_MOVE = 0x0001
        INPUT_MOUSE = 0
        send_input = ctypes.windll.user32.SendInput

        steps = max(1, steps)
        step_dx = int(total_dx / steps)
        sleep_dt = max(0.0, duration / steps)

        remainder = total_dx - step_dx * steps
        for i in range(steps):
            dx = step_dx + (1 if i < abs(remainder) else 0) * (1 if remainder > 0 else -1)
            inp = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx=dx, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_MOVE, time=0, dwExtraInfo=None))
            send_input(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            if sleep_dt:
                time.sleep(sleep_dt)

    def hold_forward(self, duration: float) -> None:
        pyautogui.keyDown("w")
        try:
            time.sleep(duration)
        finally:
            pyautogui.keyUp("w")

    def _llm_recovery_step(self) -> None:
        prompt = (
            "You are controlling a harvesting bot in a game. "
            "Choose exactly one action from this list and output only the token: "
            "press_e, rotate_left_small, rotate_right_small, step_forward, step_back, wait. "
            "State before choice: just collected oranges and may need small correction to return to tree."
        )
        try:
            resp = chat(model=self.cfg.llm_model, messages=[{"role": "user", "content": prompt}])
            content = (resp.message.content if resp and resp.message else "")
            action = content.strip().split()[0].lower() if content.strip() else "wait"
            self._execute_recovery_action(action)
            print(f"[BOT] LLM action: {action}")
        except Exception as exc:
            print(f"[BOT] LLM step failed: {exc}")

    def _execute_recovery_action(self, action: str) -> None:
        if action == "press_e":
            pyautogui.press("e")
        elif action == "rotate_left_small":
            if platform.system().lower().startswith("win"):
                self._turn_right_windows_relative(-250, 0.15, 10)
            else:
                pyautogui.moveRel(-250, 0, duration=0.15)
        elif action == "rotate_right_small":
            if platform.system().lower().startswith("win"):
                self._turn_right_windows_relative(250, 0.15, 10)
            else:
                pyautogui.moveRel(250, 0, duration=0.15)
        elif action == "step_forward":
            self.hold_forward(0.35)
        elif action == "step_back":
            pyautogui.keyDown("s")
            time.sleep(0.35)
            pyautogui.keyUp("s")
        else:
            time.sleep(0.25)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Orange auto-farming helper")
    p.add_argument("--e-cooldown", type=float, default=2.0)
    p.add_argument("--post-pick-cooldown", type=float, default=1.5)
    p.add_argument("--move-duration", type=float, default=1.5)
    p.add_argument("--turn-pixels", type=int, default=1200, help="Horizontal mouse movement for ~180°")
    p.add_argument("--turn-duration", type=float, default=0.3)
    p.add_argument("--max-targets", type=int, default=24)
    p.add_argument("--enable-llm", action="store_true")
    p.add_argument("--llm-model", default="llama3.1:8b")
    return p


def main() -> None:
    args = build_parser().parse_args()
    cfg = BotConfig(
        e_cooldown=args.e_cooldown,
        post_pick_cooldown=args.post_pick_cooldown,
        move_duration=args.move_duration,
        turn_pixels=args.turn_pixels,
        turn_duration=args.turn_duration,
        max_targets=args.max_targets,
        enable_llm=args.enable_llm,
        llm_model=args.llm_model,
    )

    bot = OrangeBot(cfg)

    print("=== OrangeBot controls ===")
    print("Insert -> toggle ON/OFF")
    print("End    -> exit")

    def on_press(key: keyboard.Key | keyboard.KeyCode) -> Optional[bool]:
        if key == keyboard.Key.insert:
            bot.toggle()
        elif key == keyboard.Key.end:
            bot.stop_all()
            return False
        return None

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


if __name__ == "__main__":
    main()
