#!/usr/bin/env python3
"""Orange auto-farming helper.

Features:
- Toggle ON/OFF by Insert key.
- Presses E, waits, finds oranges on screen, clicks them.
- Performs movement routine and repeats.
- Optional LLM-based recovery hints.

Run:
    python orange_bot.py --help
"""

from __future__ import annotations

import argparse
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
    click_pause: float = 0.1
    orange_min_area: int = 120
    orange_max_area: int = 60000
    max_targets: int = 18
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
            state = "ON" if self.running else "OFF"
            print(f"[BOT] State: {state}")
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
            pyautogui.moveTo(x, y, duration=0.03)
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

        lower1 = np.array([4, 90, 70])
        upper1 = np.array([25, 255, 255])
        lower2 = np.array([0, 120, 90])
        upper2 = np.array([4, 255, 255])
        mask = cv2.inRange(hsv, lower1, upper1) | cv2.inRange(hsv, lower2, upper2)

        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        points: List[Point] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.cfg.orange_min_area or area > self.cfg.orange_max_area:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = (4 * np.pi * area) / (perimeter * perimeter)
            if circularity < 0.4:
                continue

            m = cv2.moments(contour)
            if m["m00"] == 0:
                continue
            cx = int(m["m10"] / m["m00"])
            cy = int(m["m01"] / m["m00"])
            points.append((cx, cy))

        points = sorted(points, key=lambda p: (p[1], p[0]))
        return points[: self.cfg.max_targets]

    def _capture_frame_bgr(self) -> np.ndarray:
        """Grab current primary monitor frame.

        MSS handles are thread-local on Windows, so we create MSS in the same
        thread where `grab()` is called to avoid `_thread._local` handle errors.
        """
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            shot = sct.grab(monitor)
        frame = np.array(shot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def turn_right_180(self) -> None:
        pyautogui.moveRel(self.cfg.turn_pixels, 0, duration=0.25)

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
            resp = chat(
                model=self.cfg.llm_model,
                messages=[{"role": "user", "content": prompt}],
            )
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
            pyautogui.moveRel(-250, 0, duration=0.15)
        elif action == "rotate_right_small":
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
    p.add_argument("--max-targets", type=int, default=18)
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
