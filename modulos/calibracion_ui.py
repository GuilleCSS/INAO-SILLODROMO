"""
Asistente de calibración del control por posición absoluta.

Totalmente automático: no requiere que nadie presione nada por cada punto.
Por cada una de las 5 posturas (centro / izquierda / derecha / arriba /
abajo) hay una fase de "prepárate" (tiempo para sostener la postura) y
luego una fase de "capturando" (se promedian las lecturas de ese tramo).
Al terminar la última, guarda calibracion.json y el controlador pasa a usar
control por posición (la cabeza apunta directo a un lugar de pantalla) en
vez de control por velocidad.

Se ejecuta obligatoriamente al iniciar la aplicación (ver main_app.py),
porque la postura de la persona en la silla cambia de una sesión a otra.
"""

import json

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar

from .gaze_controller import Calibrador

with open("config.json", "r") as f:
    _config = json.load(f)

ESPERA_MS = int(_config.get("calibracion_espera_seg", 1.5) * 1000)
CAPTURA_MS = int(_config.get("calibracion_captura_seg", 1.5) * 1000)
TICK_MS = 100

ESTILO = """
QDialog {
    background-color: #0A0F1C;
}
QLabel {
    color: #E8EEF9;
    background: transparent;
}
QLabel#titulo {
    font-size: 26px;
    font-weight: 800;
}
QLabel#instruccion {
    font-size: 17px;
    color: #8B9AB8;
}
QLabel#lectura {
    font-size: 14px;
    color: #22D3EE;
    font-family: Consolas;
}
QProgressBar {
    background-color: #18223A;
    border: 1px solid #26324D;
    border-radius: 8px;
    height: 16px;
    text-align: center;
    color: #E8EEF9;
}
QProgressBar::chunk {
    background-color: #22D3EE;
    border-radius: 8px;
}
QPushButton {
    padding: 10px 20px;
    border-radius: 14px;
    font-size: 15px;
    font-weight: 700;
    color: #8B9AB8;
    background-color: #18223A;
    border: 1px solid #26324D;
}
QPushButton:hover { background-color: #26324D; }
"""


class DialogoCalibracion(QDialog):
    """Modal automático: cuenta regresiva + captura por cada uno de los 5 puntos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibrando cursor")
        self.setModal(True)
        self.setMinimumSize(560, 320)
        self.setStyleSheet(ESTILO)

        self.calibrador = Calibrador()
        self._paso = 0
        self._fase = "espera"          # "espera" | "captura"
        self._restante_ms = ESPERA_MS
        self._capturando = False
        self._muestras_paso = []
        self.guardado = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(14)

        self.lblPaso = QLabel()
        self.lblPaso.setObjectName("titulo")
        layout.addWidget(self.lblPaso)

        self.lblInstruccion = QLabel()
        self.lblInstruccion.setObjectName("instruccion")
        self.lblInstruccion.setWordWrap(True)
        layout.addWidget(self.lblInstruccion)

        layout.addStretch(1)

        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        layout.addWidget(self.barra)

        self.lblLectura = QLabel()
        self.lblLectura.setObjectName("lectura")
        layout.addWidget(self.lblLectura)

        fila_botones = QHBoxLayout()
        fila_botones.addStretch(1)
        self.btnCancelar = QPushButton("Cancelar (Esc)")
        self.btnCancelar.clicked.connect(self.reject)
        fila_botones.addWidget(self.btnCancelar)
        layout.addLayout(fila_botones)

        self._entrar_paso(reiniciar_restante=True)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # --------------------------------------------------------
    # Alimentado en vivo por la ventana principal
    # --------------------------------------------------------

    def actualizar_lectura(self, hx, hy):
        self.lblLectura.setText(f"Lectura de cámara  ·  x={hx:+.3f}  y={hy:+.3f}")
        if self._capturando:
            self._muestras_paso.append((hx, hy))

    # --------------------------------------------------------
    # Máquina de estados: espera -> captura -> (siguiente punto | terminar)
    # --------------------------------------------------------

    def _entrar_paso(self, reiniciar_restante):
        nombre = Calibrador.PUNTOS[self._paso]
        self.lblPaso.setText(
            f"Punto {self._paso + 1} de {len(Calibrador.PUNTOS)} · {nombre.upper()}"
        )
        self.lblInstruccion.setText(f"{Calibrador.ETIQUETAS[nombre]} y mantente así.")
        self._fase = "espera"
        self._capturando = False
        self._muestras_paso = []
        if reiniciar_restante:
            self._restante_ms = ESPERA_MS
        self.barra.setValue(0)

    def _tick(self):
        self._restante_ms -= TICK_MS
        total = ESPERA_MS if self._fase == "espera" else CAPTURA_MS
        progreso = int(100 * (1 - max(0, self._restante_ms) / total))
        self.barra.setValue(min(100, progreso))

        if self._restante_ms > 0:
            return

        if self._fase == "espera":
            self._fase = "captura"
            self._capturando = True
            self._muestras_paso = []
            self._restante_ms = CAPTURA_MS
            self.lblInstruccion.setText("Capturando… no te muevas.")
        else:
            self._finalizar_captura()

    def _finalizar_captura(self):
        nombre = Calibrador.PUNTOS[self._paso]
        if self._muestras_paso:
            hx = sum(m[0] for m in self._muestras_paso) / len(self._muestras_paso)
            hy = sum(m[1] for m in self._muestras_paso) / len(self._muestras_paso)
        else:
            hx, hy = 0.0, 0.0
        self.calibrador.registrar(nombre, hx, hy)

        if self._paso < len(Calibrador.PUNTOS) - 1:
            self._paso += 1
            self._entrar_paso(reiniciar_restante=True)
        else:
            self._timer.stop()
            self.calibrador.guardar()
            self.guardado = True
            self.accept()
