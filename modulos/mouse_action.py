import pyautogui

pyautogui.FAILSAFE = False

def mover_cursor(dx, dy):
    # Forzamos enteros para evitar el lag de interpolación de Windows
    desplazamiento_x = int(dx)
    desplazamiento_y = int(dy)
    
    if desplazamiento_x != 0 or desplazamiento_y != 0:
        pyautogui.move(desplazamiento_x, desplazamiento_y, _pause=False)

def hacer_clic():
    pyautogui.click()