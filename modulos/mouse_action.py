import os
import ctypes
import threading

import pyautogui


# ============================================================
# CONFIGURACIÓN PYAUTOGUI
# ============================================================

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


# ============================================================
# MOVIMIENTO SUBPÍXEL
# ============================================================

_residuo_x = 0.0
_residuo_y = 0.0


# ============================================================
# ESTADO DEL BOTÓN IZQUIERDO
# ============================================================

_mouse_presionado = False


# ============================================================
# WINDOWS
# ============================================================

if os.name == "nt":

    user32 = ctypes.windll.user32

    class POINT(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_long),
            ("y", ctypes.c_long)
        ]


# ============================================================
# MOVER CURSOR
# ============================================================

def mover_cursor(dx, dy):

    global _residuo_x
    global _residuo_y

    _residuo_x += dx
    _residuo_y += dy

    desplazamiento_x = int(_residuo_x)
    desplazamiento_y = int(_residuo_y)

    _residuo_x -= desplazamiento_x
    _residuo_y -= desplazamiento_y

    if desplazamiento_x == 0 and desplazamiento_y == 0:
        return

    # ========================================================
    # WINDOWS
    # ========================================================

    if os.name == "nt":

        punto = POINT()

        user32.GetCursorPos(
            ctypes.byref(punto)
        )

        ancho = user32.GetSystemMetrics(0)
        alto = user32.GetSystemMetrics(1)

        nueva_x = punto.x + desplazamiento_x
        nueva_y = punto.y + desplazamiento_y

        nueva_x = max(
            0,
            min(ancho - 1, nueva_x)
        )

        nueva_y = max(
            0,
            min(alto - 1, nueva_y)
        )

        user32.SetCursorPos(
            nueva_x,
            nueva_y
        )

    # ========================================================
    # OTROS SISTEMAS
    # ========================================================

    else:

        pyautogui.moveRel(
            desplazamiento_x,
            desplazamiento_y,
            duration=0,
            _pause=False
        )


# ============================================================
# CLIC NORMAL
# ============================================================

def hacer_clic():

    pyautogui.click(
        _pause=False
    )


# ============================================================
# MANTENER BOTÓN PRESIONADO
# ============================================================

def presionar_mouse():

    global _mouse_presionado

    if not _mouse_presionado:

        pyautogui.mouseDown(
            button="left",
            _pause=False
        )

        _mouse_presionado = True

        print("[MOUSE] Botón izquierdo PRESIONADO")


# ============================================================
# SOLTAR BOTÓN
# ============================================================

def soltar_mouse():

    global _mouse_presionado

    if _mouse_presionado:

        pyautogui.mouseUp(
            button="left",
            _pause=False
        )

        _mouse_presionado = False

        print("[MOUSE] Botón izquierdo LIBERADO")


# ============================================================
# CONSULTAR ESTADO
# ============================================================

def mouse_esta_presionado():

    return _mouse_presionado


# ============================================================
# FEEDBACK LOCAL
# ============================================================

def feedback_clic_inmediato():

    if os.name != "nt":
        return

    def reproducir():

        try:

            import winsound

            winsound.PlaySound(
                "SystemAsterisk",
                winsound.SND_ALIAS |
                winsound.SND_ASYNC
            )

        except Exception:
            pass

    threading.Thread(
        target=reproducir,
        daemon=True
    ).start()