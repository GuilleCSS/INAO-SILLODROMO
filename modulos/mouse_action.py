"""
Lo único que toca el mouse del sistema. El resto del programa pasa por aquí.

Los gestos se traducen a clics reales del sistema operativo, no a llamadas
directas a los botones de Qt: así la interfaz se maneja exactamente igual que
con un mouse y no hay dos caminos distintos que mantener.
"""

import pyautogui

# FAILSAFE mata el programa si el cursor toca una esquina de la pantalla.
# Aquí el cursor salta a botones que están pegados al borde, así que se
# dispararía solo en pleno uso. _pause=False quita la espera de 0.1 s que
# pyautogui mete después de cada llamada, que a 30 frames por segundo se
# convertiría en un retraso notorio.
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
