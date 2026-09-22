"""
Asistente de calibración del control por posición absoluta.

Pantalla completa con un punto real en cada posición (centro, izquierda,
derecha, arriba, abajo): la persona apunta la cabeza hacia ESE punto en
la pantalla, no hacia una dirección abstracta. Antes se calibraba con un
cuadro de texto chico ("gira cómodamente a la izquierda") sin ningún
punto de referencia real, lo que hacía el rango calibrado arbitrario e
inconsistente de una sesión a otra — la causa más probable de que el
cursor no aterrizara bien en el lugar correcto.

Automático (nadie tiene que presionar nada por cada punto), pero interactivo:
- Anuncia por voz cada postura y cuándo hay que quedarse quieto.
- Cuenta regresiva grande antes de capturar.
- Si se pierde el rostro, PAUSA el conteo en vez de capturar datos basura.
- Botón (y atajo "R") para repetir el punto actual si algo salió mal.

Por cada una de las 5 posturas hay una fase de "prepárate" y luego una de
"capturando" (se promedian las lecturas de ese tramo). Al terminar la
última, guarda calibracion.json y el controlador pasa a usar control por
posición (la cabeza apunta directo a un lugar de pantalla) en vez de
control por velocidad.

Se ejecuta obligatoriamente al iniciar la aplicación (ver main_app.py),
porque la postura de la persona en la silla cambia de una sesión a otra.
"""

import json

from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtGui import QKeySequence, QPainter, QColor, QPen
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QShortcut,
)

from .gaze_controller import Calibrador
from .voice_synth import hablar_en_segundo_plano

with open("config.json", "r") as f:
    _config = json.load(f)

ESPERA_MS = int(_config.get("calibracion_espera_seg", 1.5) * 1000)
CAPTURA_MS = int(_config.get("calibracion_captura_seg", 1.5) * 1000)
TICK_MS = 100

# Dónde aparece el punto en pantalla para cada postura (fracción de ancho/alto).
# Insertados un poco desde el borde real: fáciles de ver y apuntar sin ser
# incómodos, y el margen de calibración (config: calibracion_margen) ya se
# encarga de que un poco más allá de este punto llegue al borde real.
POSICIONES = {
    "centro": (0.50, 0.42),
    "izquierda": (0.10, 0.42),
    "derecha": (0.90, 0.42),
    "arriba": (0.50, 0.12),
    "abajo": (0.50, 0.72),
}

ESTILO = """
QDialog {
    background-color: #0A0F1C;
}
QLabel {
    color: #E8EEF9;
    background: transparent;
}
QLabel#titulo {
    font-size: 24px;
    font-weight: 800;
    qproperty-alignment: AlignCenter;
}
QLabel#instruccion {
    font-size: 16px;
    color: #8B9AB8;
    qproperty-alignment: AlignCenter;
}
QLabel#cuenta {
    font-size: 44px;
    font-weight: 800;
    color: #22D3EE;
    qproperty-alignment: AlignCenter;
}
QLabel#cuenta[fase="captura"] {
    color: #22C55E;
    font-size: 26px;
}
QLabel#cuenta[fase="pausa"] {
    color: #FBBF24;
    font-size: 20px;
}
QLabel#lectura {
    font-size: 13px;
    color: #22D3EE;
    font-family: Consolas;
    qproperty-alignment: AlignCenter;
}
QProgressBar {
    background-color: #18223A;
    border: 1px solid #26324D;
    border-radius: 8px;
    height: 14px;
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
QPushButton#btnRepetir {
    color: #FBBF24;
    border: 1px solid rgba(245, 158, 11, 120);
}
QPushButton#btnRepetir:hover { background-color: rgba(245, 158, 11, 30); }
"""


class DialogoCalibracion(QDialog):
    """Pantalla completa: punto real en cada posición + cuenta regresiva + captura."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibrando cursor")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setStyleSheet(ESTILO)

        self.calibrador = Calibrador()
        self._paso = 0
        self._fase = "espera"          # "espera" | "captura"
        self._restante_ms = ESPERA_MS
        self._capturando = False
        self._muestras_paso = []
        self._rostro_detectado = False
        self.guardado = False

        # ---- HUD anclado abajo; el punto a apuntar se dibuja arriba, en paintEvent ----
        layout = QVBoxLayout(self)
        layout.setContentsMargins(260, 40, 260, 56)
        layout.setSpacing(10)
        layout.addStretch(1)

        self.lblPaso = QLabel()
        self.lblPaso.setObjectName("titulo")
        layout.addWidget(self.lblPaso)

        self.lblInstruccion = QLabel()
        self.lblInstruccion.setObjectName("instruccion")
        self.lblInstruccion.setWordWrap(True)
        layout.addWidget(self.lblInstruccion)

        self.lblCuenta = QLabel()
        self.lblCuenta.setObjectName("cuenta")
        layout.addWidget(self.lblCuenta)

        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        layout.addWidget(self.barra)

        self.lblLectura = QLabel()
        self.lblLectura.setObjectName("lectura")
        layout.addWidget(self.lblLectura)

        fila_botones = QHBoxLayout()
        self.btnRepetir = QPushButton("Repetir este punto (R)")
        self.btnRepetir.setObjectName("btnRepetir")
        self.btnRepetir.clicked.connect(self._repetir_punto)
        fila_botones.addWidget(self.btnRepetir)
        fila_botones.addStretch(1)
        self.btnCancelar = QPushButton("Cancelar (Esc)")
        self.btnCancelar.clicked.connect(self.reject)
        fila_botones.addWidget(self.btnCancelar)
        layout.addLayout(fila_botones)

        QShortcut(QKeySequence(Qt.Key_R), self, activated=self._repetir_punto)

        self._entrar_paso(reiniciar_restante=True, anunciar=True)
        self.showFullScreen()

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # --------------------------------------------------------
    # Alimentado en vivo por la ventana principal
    # --------------------------------------------------------

    def actualizar_lectura(self, hx, hy, rostro=True):
        self._rostro_detectado = rostro
        if rostro:
            self.lblLectura.setText(f"Lectura de cámara  ·  x={hx:+.3f}  y={hy:+.3f}")
            if self._capturando:
                self._muestras_paso.append((hx, hy))
        else:
            self.lblLectura.setText("Sin lectura: no se detecta rostro")

    # --------------------------------------------------------
    # Punto a apuntar en pantalla (se dibuja detrás del HUD)
    # --------------------------------------------------------

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        nombre = Calibrador.PUNTOS[self._paso]
        fx, fy = POSICIONES[nombre]
        cx, cy = self.width() * fx, self.height() * fy

        if self._fase == "captura":
            color = QColor("#22C55E")
            radio_halo, radio_anillo, radio_punto = 50, 22, 8
        else:
            color = QColor("#22D3EE")
            radio_halo, radio_anillo, radio_punto = 36, 18, 6

        centro = QPointF(cx, cy)
        p.setPen(Qt.NoPen)
        halo = QColor(color)
        halo.setAlpha(45)
        p.setBrush(halo)
        p.drawEllipse(centro, radio_halo, radio_halo)

        p.setPen(QPen(color, 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(centro, radio_anillo, radio_anillo)

        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(centro, radio_punto, radio_punto)
        p.end()

    # --------------------------------------------------------
    # Máquina de estados: espera -> captura -> (siguiente punto | terminar)
    # --------------------------------------------------------

    def _entrar_paso(self, reiniciar_restante, anunciar=True):
        nombre = Calibrador.PUNTOS[self._paso]
        self.lblPaso.setText(
            f"Punto {self._paso + 1} de {len(Calibrador.PUNTOS)} · {nombre.upper()}"
        )
        self.lblInstruccion.setText(f"{Calibrador.ETIQUETAS[nombre]}, y mantente así.")
        self._fase = "espera"
        self._capturando = False
        self._muestras_paso = []
        if reiniciar_restante:
            self._restante_ms = ESPERA_MS
        self.barra.setValue(0)
        self._pintar_cuenta("espera")
        self.update()

        if anunciar:
            hablar_en_segundo_plano(nombre)

    def _repetir_punto(self):
        hablar_en_segundo_plano("Repitiendo")
        self._entrar_paso(reiniciar_restante=True, anunciar=True)

    def _pintar_cuenta(self, fase, texto=None):
        self.lblCuenta.setProperty("fase", fase)
        self.lblCuenta.style().unpolish(self.lblCuenta)
        self.lblCuenta.style().polish(self.lblCuenta)
        if texto is not None:
            self.lblCuenta.setText(texto)

    def _tick(self):
        if not self._rostro_detectado:
            self.lblInstruccion.setText("Buscando rostro… colócate frente a la cámara")
            self._pintar_cuenta("pausa", "⏸  Pausado")
            return  # no se detecta cara: se pausa, no se gasta el tiempo ni se captura

        self._restante_ms -= TICK_MS
        total = ESPERA_MS if self._fase == "espera" else CAPTURA_MS
        progreso = int(100 * (1 - max(0, self._restante_ms) / total))
        self.barra.setValue(min(100, progreso))

        if self._fase == "espera":
            segundos = max(1, (self._restante_ms + 999) // 1000)
            self._pintar_cuenta("espera", str(segundos))
        else:
            self.lblInstruccion.setText("Capturando… no te muevas.")
            self._pintar_cuenta("captura", "● GRABANDO")

        if self._restante_ms > 0:
            return

        if self._fase == "espera":
            self._fase = "captura"
            self._capturando = True
            self._muestras_paso = []
            self._restante_ms = CAPTURA_MS
            self.lblInstruccion.setText("Capturando… no te muevas.")
            self._pintar_cuenta("captura", "● GRABANDO")
            self.update()
            hablar_en_segundo_plano("Quieto")
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
            self._entrar_paso(reiniciar_restante=True, anunciar=True)
        else:
            self._timer.stop()
            self.calibrador.guardar()
            self.guardado = True
            self.accept()
