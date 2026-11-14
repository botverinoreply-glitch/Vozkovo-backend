"""
motor.py — IA de tres en raya que aprende jugando contra sí misma.

Requisitos:
    Python 3.9 o superior.
    Tkinter (normalmente viene incluido con Python).

Ejecutar:
    python motor.py

El aprendizaje se guarda automáticamente en:
    modelo_tres_en_raya.json

La cantidad de sombreros aumenta cuando baja la pérdida (loss) suavizada.
Nota: una loss baja no garantiza por sí sola que la IA juegue mejor; por eso
también se muestran victorias, empates y derrotas.
"""

from __future__ import annotations

import json
import math
import random
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import messagebox
from typing import Dict, List, Optional, Tuple


State = Tuple[int, ...]
QTable = Dict[State, List[float]]

WIDTH = 1180
HEIGHT = 800
BOARD_SIZE = 390
CELL_SIZE = BOARD_SIZE // 3
BOARD_X = (WIDTH - BOARD_SIZE) // 2
BOARD_Y = 205

BATCH_SIZE = 14
TICK_MS = 85
DEMO_MOVE_MS = 330

ALPHA = 0.18
GAMMA = 0.94
EPSILON_START = 0.35
EPSILON_FLOOR = 0.04

MODEL_PATH = Path(__file__).resolve().with_name("modelo_tres_en_raya.json")


def winner_of(board: List[int]) -> Optional[int]:
    """Devuelve 1 o -1 si hay ganador, o None si todavía no hay ganador."""
    lines = (
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
        (0, 4, 8), (2, 4, 6),
    )
    for a, b, c in lines:
        if board[a] != 0 and board[a] == board[b] == board[c]:
            return board[a]
    return None


def legal_actions(state: State) -> List[int]:
    return [index for index, value in enumerate(state) if value == 0]


class SelfPlayAgent:
    """
    Q-learning tabular desde el punto de vista del jugador al que le toca.
    Los dos bandos comparten esta misma tabla Q.
    """

    def __init__(self) -> None:
        self.q: QTable = {}
        self.games = 0
        self.wins_x = 0
        self.wins_o = 0
        self.draws = 0
        self.loss_ema = 0.0
        self.loss_samples: deque[float] = deque(maxlen=90)
        self.load_model()

    def values_for(self, state: State) -> List[float]:
        if state not in self.q:
            self.q[state] = [0.0] * 9
        return self.q[state]

    def epsilon(self) -> float:
        # Reduce gradualmente la exploración a medida que juega más partidas.
        return max(EPSILON_FLOOR, EPSILON_START * math.exp(-self.games / 24000))

    def choose_action(self, state: State, epsilon: float) -> int:
        actions = legal_actions(state)
        if not actions:
            raise ValueError("No quedan movimientos legales.")

        if random.random() < epsilon:
            return random.choice(actions)

        values = self.values_for(state)
        best_value = max(values[a] for a in actions)
        best_actions = [a for a in actions if abs(values[a] - best_value) < 1e-12]
        return random.choice(best_actions)

    def play_training_game(self) -> float:
        """Juega una partida completa y actualiza la tabla Q al terminar."""
        board = [0] * 9
        player = 1
        # state, action, next_state, terminal, player
        history: List[Tuple[State, int, State, bool, int]] = []

        winner: Optional[int] = None
        while True:
            state = tuple(cell * player for cell in board)
            action = self.choose_action(state, self.epsilon())
            board[action] = player

            winner = winner_of(board)
            terminal = winner is not None or all(cell != 0 for cell in board)

            next_player = -player
            next_state = tuple(cell * next_player for cell in board)
            history.append((state, action, next_state, terminal, player))

            if terminal:
                break

            player = next_player

        # Actualización hacia atrás: el valor del siguiente estado pertenece
        # al rival, por eso se resta su mejor valor (juego de suma cero).
        errors: List[float] = []
        for state, action, next_state, terminal, mover in reversed(history):
            old_value = self.values_for(state)[action]

            if terminal:
                if winner is None:
                    reward = 0.0
                else:
                    reward = 1.0 if winner == mover else -1.0
                target = reward
            else:
                next_actions = legal_actions(next_state)
                opponent_best = (
                    max(self.values_for(next_state)[a] for a in next_actions)
                    if next_actions else 0.0
                )
                target = -GAMMA * opponent_best

            error = target - old_value
            self.values_for(state)[action] += ALPHA * error
            errors.append(error * error)

        self.games += 1
        if winner == 1:
            self.wins_x += 1
        elif winner == -1:
            self.wins_o += 1
        else:
            self.draws += 1

        game_loss = sum(errors) / max(1, len(errors))
        self.loss_samples.append(game_loss)

        # Suavizado para que los sombreros no cambien bruscamente cada partida.
        if self.games == 1:
            self.loss_ema = game_loss
        else:
            self.loss_ema = 0.94 * self.loss_ema + 0.06 * game_loss

        return game_loss

    def hat_count(self) -> int:
        """Más sombreros con menos loss; menos sombreros con más loss."""
        if self.games == 0:
            return 0
        score = 10.0 / (1.0 + 5.0 * max(0.0, self.loss_ema))
        return max(0, min(10, int(round(score))))

    def save_model(self) -> bool:
        try:
            payload = {
                "version": 1,
                "games": self.games,
                "wins_x": self.wins_x,
                "wins_o": self.wins_o,
                "draws": self.draws,
                "loss_ema": self.loss_ema,
                "q": [
                    [list(state), values]
                    for state, values in self.q.items()
                ],
            }
            temporary = MODEL_PATH.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary.replace(MODEL_PATH)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def load_model(self) -> None:
        if not MODEL_PATH.exists():
            return
        try:
            payload = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
            self.games = max(0, int(payload.get("games", 0)))
            self.wins_x = max(0, int(payload.get("wins_x", 0)))
            self.wins_o = max(0, int(payload.get("wins_o", 0)))
            self.draws = max(0, int(payload.get("draws", 0)))
            self.loss_ema = max(0.0, float(payload.get("loss_ema", 0.0)))

            restored: QTable = {}
            for entry in payload.get("q", []):
                raw_state, raw_values = entry
                state = tuple(int(v) for v in raw_state)
                values = [float(v) for v in raw_values]
                if len(state) == 9 and len(values) == 9:
                    restored[state] = values
            self.q = restored
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            # Si el archivo está dañado, comienza una tabla nueva sin bloquear.
            self.q = {}
            self.games = 0
            self.wins_x = self.wins_o = self.draws = 0
            self.loss_ema = 0.0


class WoodenTrainingApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.agent = SelfPlayAgent()
        self.root.title("Tres en raya — IA en autoentrenamiento")
        self.root.geometry(f"{WIDTH}x{HEIGHT}")
        self.root.resizable(False, False)
        self.root.configure(bg="#59351f")

        self.canvas = tk.Canvas(
            root,
            width=WIDTH,
            height=HEIGHT,
            highlightthickness=0,
            bg="#8b572f",
        )
        self.canvas.pack(fill="both", expand=True)

        self.demo_board = [0] * 9
        self.demo_player = 1
        self.demo_result = ""
        self.demo_finished_at = 0.0
        self.demo_moves = 0
        self.closing = False
        self.last_save_at = self.agent.games

        self.draw_scene()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(TICK_MS, self.tick)
        self.root.after(DEMO_MOVE_MS, self.advance_demo)

    def draw_wood_background(self) -> None:
        c = self.canvas
        c.create_rectangle(0, 0, WIDTH, HEIGHT, fill="#8b572f", outline="")

        rng = random.Random(31)
        plank_colors = ["#9a6338", "#87532f", "#a16a3e", "#8f5a34"]
        for y in range(0, HEIGHT, 74):
            shade = plank_colors[(y // 74) % len(plank_colors)]
            c.create_rectangle(0, y, WIDTH, y + 74, fill=shade, outline="")
            c.create_line(0, y + 2, WIDTH, y + 2, fill="#59371f", width=2)
            c.create_line(0, y + 70, WIDTH, y + 70, fill="#bd8754", width=2)

            for _ in range(4):
                x = rng.randint(25, WIDTH - 25)
                yy = y + rng.randint(12, 60)
                length = rng.randint(35, 145)
                c.create_line(
                    x, yy, x + length, yy + rng.randint(-2, 2),
                    fill="#714326", width=1,
                )

        # Nudos discretos de la madera.
        for x, y in [(125, 195), (1040, 125), (170, 690), (1000, 700)]:
            c.create_oval(x - 13, y - 7, x + 13, y + 7,
                          outline="#704326", width=2)
            c.create_oval(x - 6, y - 3, x + 6, y + 3,
                          outline="#704326", width=1)

        # Viñeta exterior.
        c.create_rectangle(8, 8, WIDTH - 8, HEIGHT - 8,
                           outline="#4d2d1b", width=5)

    def draw_hat(self, cx: int, cy: int, active: bool) -> None:
        c = self.canvas
        if active:
            fill = "#f2cf70"
            edge = "#503017"
            band = "#9d4325"
        else:
            fill = "#62452f"
            edge = "#4a3324"
            band = "#72513a"

        c.create_oval(cx - 11, cy + 7, cx + 11, cy + 13,
                      fill=fill, outline=edge, width=1)
        c.create_polygon(
            cx - 7, cy + 7,
            cx - 6, cy - 7,
            cx + 6, cy - 7,
            cx + 8, cy + 7,
            fill=fill, outline=edge, width=1,
        )
        c.create_line(cx - 6, cy + 1, cx + 7, cy + 1,
                      fill=band, width=3)

    def draw_hat_panel(self) -> None:
        c = self.canvas
        c.create_text(28, 33, anchor="w", text="SOMBREROS",
                      fill="#ffe5b4", font=("Georgia", 13, "bold"))
        count = self.agent.hat_count()
        for i in range(10):
            self.draw_hat(38 + i * 25, 66, i < count)
        c.create_text(28, 91, anchor="w",
                      text=f"{count} / 10  ·  menos loss = más sombreros",
                      fill="#fff0d3", font=("Arial", 9, "bold"))

    def draw_board(self) -> None:
        c = self.canvas
        x0, y0 = BOARD_X, BOARD_Y
        x1, y1 = x0 + BOARD_SIZE, y0 + BOARD_SIZE

        # Sombra y marco de madera.
        c.create_rectangle(x0 - 17, y0 - 12, x1 + 17, y1 + 20,
                           fill="#432819", outline="#3a2115", width=3)
        c.create_rectangle(x0 - 12, y0 - 15, x1 + 12, y1 + 12,
                           fill="#b77b42", outline="#5b351e", width=5)
        c.create_rectangle(x0 - 5, y0 - 8, x1 + 5, y1 + 5,
                           fill="#d5a467", outline="#704321", width=3)

        cell_colors = ["#ead0a0", "#e4c28b"]
        for row in range(3):
            for col in range(3):
                x = x0 + col * CELL_SIZE
                y = y0 + row * CELL_SIZE
                c.create_rectangle(
                    x + 3, y + 3, x + CELL_SIZE - 3, y + CELL_SIZE - 3,
                    fill=cell_colors[(row + col) % 2],
                    outline="#9b693e", width=1,
                )

                value = self.demo_board[row * 3 + col]
                if value == 1:
                    pad = 31
                    c.create_line(
                        x + pad, y + pad, x + CELL_SIZE - pad, y + CELL_SIZE - pad,
                        fill="#8e2922", width=13, capstyle=tk.ROUND,
                    )
                    c.create_line(
                        x + CELL_SIZE - pad, y + pad, x + pad, y + CELL_SIZE - pad,
                        fill="#8e2922", width=13, capstyle=tk.ROUND,
                    )
                elif value == -1:
                    pad = 31
                    c.create_oval(
                        x + pad, y + pad, x + CELL_SIZE - pad, y + CELL_SIZE - pad,
                        outline="#244e69", width=13,
                    )

        # Líneas y pequeños remaches.
        for i in range(4):
            xx = x0 + i * CELL_SIZE
            yy = y0 + i * CELL_SIZE
            if 0 < i < 3:
                c.create_line(xx, y0, xx, y1, fill="#734522", width=5)
                c.create_line(x0, yy, x1, yy, fill="#734522", width=5)

        for px, py in [(x0 - 8, y0 - 11), (x1 + 8, y0 - 11),
                       (x0 - 8, y1 + 8), (x1 + 8, y1 + 8)]:
            c.create_oval(px - 4, py - 4, px + 4, py + 4,
                          fill="#4b2b19", outline="#e2b875", width=1)

    def draw_loss_chart(self) -> None:
        c = self.canvas
        left, top, right, bottom = 285, 681, 895, 744

        c.create_text(left, top - 15, anchor="w",
                      text="PÉRDIDA (LOSS) · ÚLTIMAS PARTIDAS",
                      fill="#ffedcf", font=("Arial", 10, "bold"))
        c.create_rectangle(left, top, right, bottom,
                           fill="#56351f", outline="#d6a46a", width=2)
        c.create_line(left + 8, bottom - 8, right - 8, bottom - 8,
                      fill="#c69a69", width=1)

        samples = list(self.agent.loss_samples)
        if len(samples) >= 2:
            max_loss = max(0.05, max(samples))
            points = []
            usable_w = (right - left) - 20
            usable_h = (bottom - top) - 16
            for i, sample in enumerate(samples):
                px = left + 10 + usable_w * i / max(1, len(samples) - 1)
                py = bottom - 8 - (sample / max_loss) * usable_h
                points.extend((px, py))
            c.create_line(*points, fill="#f6d47e", width=2, smooth=True)

    def draw_scene(self) -> None:
        c = self.canvas
        c.delete("all")
        self.draw_wood_background()

        # Cabecera.
        c.create_text(WIDTH // 2, 37, text="TRES EN RAYA",
                      fill="#fff0d4", font=("Georgia", 27, "bold"))
        c.create_text(WIDTH // 2, 71,
                      text="ENTRENAMIENTO EN VIVO  ·  LA IA JUEGA CONTRA SÍ MISMA",
                      fill="#f5d6a6", font=("Arial", 10, "bold"))

        self.draw_hat_panel()

        c.create_text(WIDTH - 27, 35, anchor="e",
                      text=f"Exploración: {self.agent.epsilon():.3f}",
                      fill="#ffebcb", font=("Arial", 10, "bold"))
        c.create_text(WIDTH - 27, 58, anchor="e",
                      text=f"Estados aprendidos: {len(self.agent.q):,}",
                      fill="#ffebcb", font=("Arial", 10))

        # Estado de la partida que se está mostrando.
        if self.demo_result:
            status = self.demo_result
        else:
            status = f"Turno de {'X' if self.demo_player == 1 else 'O'}"
        c.create_text(WIDTH // 2, 162, text="PARTIDA DE DEMOSTRACIÓN",
                      fill="#fff0d4", font=("Georgia", 15, "bold"))
        c.create_text(WIDTH // 2, 185, text=status,
                      fill="#ffda91", font=("Arial", 11, "bold"))

        self.draw_board()

        # Resumen de entrenamiento.
        total = max(1, self.agent.games)
        c.create_text(28, 628, anchor="w",
                      text=f"PARTIDAS ENTRENADAS: {self.agent.games:,}",
                      fill="#fff0d4", font=("Arial", 12, "bold"))
        c.create_text(28, 653, anchor="w",
                      text=f"Victorias X: {self.agent.wins_x:,}",
                      fill="#ffd7a0", font=("Arial", 10, "bold"))
        c.create_text(28, 674, anchor="w",
                      text=f"Victorias O: {self.agent.wins_o:,}",
                      fill="#cce5fa", font=("Arial", 10, "bold"))
        c.create_text(28, 695, anchor="w",
                      text=f"Empates: {self.agent.draws:,}",
                      fill="#f4e6c9", font=("Arial", 10, "bold"))

        c.create_text(WIDTH - 28, 628, anchor="e",
                      text=f"LOSS MEDIA: {self.agent.loss_ema:.5f}",
                      fill="#fff0d4", font=("Arial", 12, "bold"))
        c.create_text(WIDTH - 28, 653, anchor="e",
                      text=f"Tasa de empate: {100 * self.agent.draws / total:.1f}%",
                      fill="#f4e6c9", font=("Arial", 10))
        c.create_text(WIDTH - 28, 675, anchor="e",
                      text=f"Ritmo: {BATCH_SIZE} partidas cada {TICK_MS} ms",
                      fill="#f4e6c9", font=("Arial", 10))
        c.create_text(WIDTH - 28, 697, anchor="e",
                      text="Guardado automático activado",
                      fill="#d4edc5", font=("Arial", 10, "bold"))

        self.draw_loss_chart()

        c.create_text(WIDTH // 2, 775,
                      text="La IA comparte una misma estrategia para X y O · Cierra la ventana para guardar",
                      fill="#f7dfbd", font=("Arial", 9))

    def tick(self) -> None:
        if self.closing:
            return

        for _ in range(BATCH_SIZE):
            self.agent.play_training_game()

        # Guarda cada 500 partidas, además del guardado al cerrar.
        if self.agent.games - self.last_save_at >= 500:
            self.agent.save_model()
            self.last_save_at = self.agent.games

        self.draw_scene()
        self.root.after(TICK_MS, self.tick)

    def advance_demo(self) -> None:
        if self.closing:
            return

        if self.demo_result:
            # Deja el resultado visible un instante antes de empezar otra.
            if time.monotonic() - self.demo_finished_at >= 0.95:
                self.demo_board = [0] * 9
                self.demo_player = 1
                self.demo_result = ""
                self.demo_moves = 0
        else:
            state = tuple(cell * self.demo_player for cell in self.demo_board)
            actions = legal_actions(state)
            if actions:
                action = self.agent.choose_action(state, epsilon=0.02)
                self.demo_board[action] = self.demo_player
                self.demo_moves += 1

                winner = winner_of(self.demo_board)
                if winner is not None:
                    self.demo_result = f"¡Gana {'X' if winner == 1 else 'O'}!"
                    self.demo_finished_at = time.monotonic()
                elif self.demo_moves >= 9:
                    self.demo_result = "Empate"
                    self.demo_finished_at = time.monotonic()
                else:
                    self.demo_player *= -1

        self.draw_scene()
        self.root.after(DEMO_MOVE_MS, self.advance_demo)

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        saved = self.agent.save_model()
        self.root.destroy()
        if not saved:
            # El cierre no debe bloquearse si no se puede escribir el archivo.
            print(f"No se pudo guardar el modelo en: {MODEL_PATH}")


def main() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(
            "No se pudo abrir la ventana gráfica. Comprueba que Python tenga Tkinter "
            "y que estés ejecutando el programa en un entorno con escritorio."
        ) from exc

    WoodenTrainingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
