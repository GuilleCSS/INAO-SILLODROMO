"""
Vista previa de la cámara para la interfaz.

OpenFace ya tiene abierta la cámara. Algunas webcams permiten que un segundo
programa la abra al mismo tiempo y otras no. Este hilo lo intenta y, si no
consigue imagen, avisa para que la interfaz muestre solo el rastreo facial.
Se puede desactivar con "vista_camara": false en config.json.
"""

import os
import json

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

with open("config.json", "r") as f:
    config = json.load(f)


class HiloCamara(QThread):

    senal_frame = pyqtSignal(QImage)
    senal_no_disponible = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._activo = True

    def run(self):
        try:
            import cv2
        except ImportError:
            self.senal_no_disponible.emit("OpenCV no está instalado")
            return

        indice = int(config.get("camera_index", 0))
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        cap = cv2.VideoCapture(indice, backend)

        if not cap.isOpened():
            self.senal_no_disponible.emit("La cámara está en uso por OpenFace")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config.get("cam_width", 1280)))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config.get("cam_height", 720)))

        espejo = bool(config.get("camara_espejo", True))
        fallos = 0
        hubo_imagen = False

        while self._activo:
            ok, frame = cap.read()

            # Frame inválido o negro = la cámara no se pudo compartir
            if not ok or frame is None or frame.mean() < 2:
                fallos += 1
                if fallos > 40:
                    if not hubo_imagen:
                        self.senal_no_disponible.emit("La cámara está en uso por OpenFace")
                    else:
                        self.senal_no_disponible.emit("Se perdió la imagen de la cámara")
                    break
                self.msleep(25)
                continue

            fallos = 0
            hubo_imagen = True

            if espejo:
                frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            alto, ancho, _ = rgb.shape
            imagen = QImage(rgb.data, ancho, alto, 3 * ancho, QImage.Format_RGB888).copy()
            self.senal_frame.emit(imagen)
            self.msleep(15)

        cap.release()

    def detener(self):
        self._activo = False
