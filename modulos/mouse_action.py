import pyautogui

pyautogui.FAILSAFE = False


def mover_cursor(dx, dy):
    # Forzamos enteros para evitar el lag de interpolación de Windows
    desplazamiento_x = int(dx)
    desplazamiento_y = int(dy)

    if desplazamiento_x != 0 or desplazamiento_y != 0:
        pyautogui.move(desplazamiento_x, desplazamiento_y, _pause=False)


def posicion_cursor():
    """Posición absoluta actual del cursor en pantalla, para el imán de objetivos."""
    return pyautogui.position()


def mover_cursor_absoluto(x, y):
    """Coloca el cursor en una posición exacta de pantalla (control por punto, no por velocidad)."""
    pyautogui.moveTo(int(x), int(y), _pause=False)


def tamano_pantalla():
    return pyautogui.size()


def hacer_clic():
    pyautogui.click()


def presionar_clic():
    """Mantiene presionado el botón izquierdo (boca abierta)."""
    pyautogui.mouseDown(button="left", _pause=False)


def soltar_clic():
    """Suelta el botón izquierdo (boca cerrada)."""
    pyautogui.mouseUp(button="left", _pause=False)
