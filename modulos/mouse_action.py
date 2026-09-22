import pyautogui

pyautogui.FAILSAFE = False


def mover_cursor_absoluto(x, y):
    """Coloca el cursor en una posición exacta de pantalla (teletransporte, no arrastre)."""
    pyautogui.moveTo(int(x), int(y), _pause=False)


def presionar_clic():
    """Mantiene presionado el botón izquierdo (boca abierta)."""
    pyautogui.mouseDown(button="left", _pause=False)


def soltar_clic():
    """Suelta el botón izquierdo (boca cerrada)."""
    pyautogui.mouseUp(button="left", _pause=False)
