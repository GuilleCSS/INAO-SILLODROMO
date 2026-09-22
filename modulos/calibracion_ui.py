"""
Calibración de gestos al iniciar la sesión.

Por qué existe (y por qué el intento anterior se había quitado): la versión
vieja intentaba mapear la cabeza a un punto exacto de la pantalla, que era
un problema mucho más difícil del necesario. Esta solo mide dos cosas:

  1. Dónde está el REPOSO real de la persona hoy.
  2. Hasta dónde llega su gesto cómodo hacia cada lado.

Hace falta porque ese alcance varía muchísimo entre sesiones —medido en dos
sesiones reales: 1.81 y 0.91 hacia la izquierda, más del doble— según qué
tan lejos se siente la persona, el ángulo de la cámara y la postura. Ningún
umbral fijo sirve para ambas, así que se miden al arrancar.

El resultado se guarda en calibracion.json y GazeStateController lo usa en
lugar de los umbrales por defecto de config.json.

Se puede saltar con Esc: en ese caso se usan los valores de config.json y el
centro se aprende solo, como antes.
"""

import json

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence, QPainter, QColor, QPen
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QShortcut,
)

from .voice_synth import hablar_en_segundo_plano

with open("config.json", "r") as f:
    _config = json.load(f)

RUTA_CALIBRACION = "calibracion.json"

PREPARAR_MS = int(_config.get("calib_preparar_seg", 1.5) * 1000)
CAPTURAR_MS = int(_config.get("calib_capturar_seg", 2.0) * 1000)
TICK_MS = 50

# Qué fracción del alcance medido se usa como umbral. Por debajo de esto se
# dispara sin querer; por encima hay que forzar el cuello.
FRACCION = float(_config.get("calib_fraccion_umbral", 0.35))

PASOS = [
    ("centro", "Mira al frente, relajado", None, None),
    ("izquierda", "Gira la cabeza a la IZQUIERDA", "x", -1),
    ("derecha", "Gira la cabeza a la DERECHA", "x", +1),
    ("arriba", "Sube la cara hacia ARRIBA", "y", -1),
    ("abajo", "Baja la cara hacia ABAJO", "y", +1),
]

ESTILO = """
QDialog { background-color: #0A0F1C; }
QLabel { color: #E8EEF9; background: transparent; }
QLabel#paso { font-size: 20px; font-weight: 800; color: #8B9AB8;
              qproperty-alignment: AlignCenter; }
QLabel#instruccion { font-size: 34px; font-weight: 800;
                     qproperty-alignment: AlignCenter; }
QLabel#cuenta { font-size: 64px; font-weight: 800; color: #22D3EE;
                qproperty-alignment: AlignCenter; }
QLabel#cuenta[fase="captura"] { color: #22C55E; font-size: 34px; }
QLabel#cuenta[fase="pausa"]   { color: #FBBF24; font-size: 26px; }
QLabel#ayuda { font-size: 15px; color: #8B9AB8; qproperty-alignment: AlignCenter; }
QProgressBar { background-color: #18223A; border: 1px solid #26324D;
               border-radius: 8px; height: 14px; text-align: center; color: #E8EEF9; }
QProgressBar::chunk { background-color: #22D3EE; border-radius: 8px; }
QPushButton { padding: 10px 20px; border-radius: 14px; font-size: 15px;
              font-weight: 700; color: #8B9AB8; background-color: #18223A;
              border: 1px solid #26324D; }
QPushButton:hover { background-color: #26324D; }
"""


class BarraSenal(QLabel):
    """Muestra en vivo cuánto se está moviendo la cabeza en el eje del paso
    actual. Sirve para que la persona vea que el sistema la está siguiendo:
    sin esto no hay forma de saber si el gesto se está registrando."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.valor = 0.0      # desviación actual respecto al centro
        self.pico = 0.0       # máximo alcanzado en este paso
        self.eje = None
        self.setMinimumHeight(70)

    def actualizar(self, valor, pico, eje):
        self.valor, self.pico, self.eje = valor, pico, eje
        self.update()

    def paintEvent(self, e):
        if self.eje is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cy = h / 2

        p.setPen(QPen(QColor("#26324D"), 2))
        p.drawLine(0, int(cy), w, int(cy))
        p.drawLine(int(w / 2), int(cy - 18), int(w / 2), int(cy + 18))

        # Escala relativa al pico del propio paso, para que la barra siempre
        # se vea moverse aunque el rango de la persona sea chico o grande.
        escala = max(self.pico, 0.2)
        x = w / 2 + max(-1.0, min(1.0, self.valor / escala)) * (w / 2 - 12)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#22D3EE"))
        p.drawEllipse(int(x) - 9, int(cy) - 9, 18, 18)
        p.end()


class DialogoCalibracion(QDialog):
    """Mide el reposo y el alcance de gesto hacia cada lado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibración de gestos")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setStyleSheet(ESTILO)

        self._paso = 0
        self._fase = "preparar"
        self._restante = PREPARAR_MS
        self._muestras = []
        self._rostro = False
        self._hx = self._hy = 0.0
        self.centro = None
        self.ruido = (0.0, 0.0)
        self.alcances = {}
        self._al_reves = {}
        self.guardado = False
        self.aviso = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(80, 50, 80, 40)
        lay.setSpacing(14)

        self.lblPaso = QLabel(); self.lblPaso.setObjectName("paso")
        lay.addWidget(self.lblPaso)
        self.lblInstruccion = QLabel(); self.lblInstruccion.setObjectName("instruccion")
        self.lblInstruccion.setWordWrap(True)
        lay.addWidget(self.lblInstruccion)
        lay.addStretch(1)
        self.lblCuenta = QLabel(); self.lblCuenta.setObjectName("cuenta")
        lay.addWidget(self.lblCuenta)
        self.barra_senal = BarraSenal()
        lay.addWidget(self.barra_senal)
        lay.addStretch(1)
        self.barra = QProgressBar(); self.barra.setRange(0, 100)
        lay.addWidget(self.barra)
        self.lblAyuda = QLabel("Esc para saltar la calibración y usar los valores guardados")
        self.lblAyuda.setObjectName("ayuda")
        lay.addWidget(self.lblAyuda)

        fila = QHBoxLayout(); fila.addStretch(1)
        btn = QPushButton("Repetir este paso (R)")
        btn.clicked.connect(self._repetir)
        fila.addWidget(btn)
        fila.addStretch(1)
        lay.addLayout(fila)

        QShortcut(QKeySequence(Qt.Key_R), self, activated=self._repetir)

        self._entrar_paso()
        self.showFullScreen()

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # -- alimentado por la ventana principal --------------------------

    def actualizar_lectura(self, hx, hy, rostro=True):
        self._rostro = rostro
        if not rostro:
            return
        self._hx, self._hy = hx, hy
        if self._fase == "capturar":
            self._muestras.append((hx, hy))

        nombre, _, eje, _ = PASOS[self._paso]
        if eje and self.centro is not None:
            base = self.centro[0] if eje == "x" else self.centro[1]
            actual = (hx if eje == "x" else hy) - base
            picos = [abs((m[0] if eje == "x" else m[1]) - base) for m in self._muestras]
            self.barra_senal.actualizar(actual, max(picos) if picos else 0.0, eje)

    # -- flujo ---------------------------------------------------------

    def _entrar_paso(self):
        nombre, texto, eje, _ = PASOS[self._paso]
        self.lblPaso.setText(f"Paso {self._paso + 1} de {len(PASOS)}")
        self.lblInstruccion.setText(texto)
        self._fase = "preparar"
        self._restante = PREPARAR_MS
        self._muestras = []
        self.barra.setValue(0)
        self.barra_senal.actualizar(0.0, 0.0, eje)
        self._pintar("preparar")
        hablar_en_segundo_plano(nombre if nombre != "centro" else "Mira al frente")

    def _repetir(self):
        hablar_en_segundo_plano("Repitiendo")
        self._entrar_paso()

    def _pintar(self, fase, texto=None):
        self.lblCuenta.setProperty("fase", fase)
        self.lblCuenta.style().unpolish(self.lblCuenta)
        self.lblCuenta.style().polish(self.lblCuenta)
        if texto is not None:
            self.lblCuenta.setText(texto)

    def _tick(self):
        if not self._rostro:
            self._pintar("pausa", "⏸  No se ve tu cara")
            return

        self._restante -= TICK_MS
        total = PREPARAR_MS if self._fase == "preparar" else CAPTURAR_MS
        self.barra.setValue(min(100, int(100 * (1 - max(0, self._restante) / total))))

        if self._fase == "preparar":
            self._pintar("preparar", str(max(1, (self._restante + 999) // 1000)))
        else:
            self._pintar("captura", "● MIDIENDO")

        if self._restante > 0:
            return

        if self._fase == "preparar":
            self._fase = "capturar"
            self._restante = CAPTURAR_MS
            self._muestras = []
            self._pintar("captura", "● MIDIENDO")
            hablar_en_segundo_plano("Sostén")
        else:
            self._terminar_paso()

    def _terminar_paso(self):
        nombre, _, eje, signo = PASOS[self._paso]

        if not self._muestras:
            self._repetir()
            return

        if nombre == "centro":
            xs = sorted(m[0] for m in self._muestras)
            ys = sorted(m[1] for m in self._muestras)
            self.centro = (xs[len(xs) // 2], ys[len(ys) // 2])
            # Temblor en reposo: cuánto oscila la señal con la cabeza quieta.
            # Es el dato que faltaba: los márgenes calculados como fracción
            # fija del umbral podían quedar por debajo de este ruido, y
            # entonces la cabeza volvía al centro sin que el sistema lo
            # reconociera (navegación bloqueada). Se toma un percentil alto
            # en vez del máximo para que un frame suelto no lo infle.
            def dispersion(vals, centro):
                d = sorted(abs(v - centro) for v in vals)
                return d[int(len(d) * 0.9)] if d else 0.0
            self.ruido = (dispersion(xs, self.centro[0]),
                          dispersion(ys, self.centro[1]))
        else:
            base = self.centro[0] if eje == "x" else self.centro[1]
            # Desviación con el signo ya puesto en el sentido que se pidió
            # (positivo = hacia allá). Se ordena DESPUÉS de multiplicar por
            # el signo: multiplicar por -1 invierte el orden, así que
            # ordenar antes daba un percentil equivocado.
            desv = [((m[0] if eje == "x" else m[1]) - base) * signo
                    for m in self._muestras]
            # Percentil alto del recorrido, en vez del máximo absoluto: un
            # solo frame con ruido no debe definir el alcance.
            hacia_alla = sorted(d for d in desv if d > 0)
            self.alcances[nombre] = (hacia_alla[int(len(hacia_alla) * 0.8)]
                                     if hacia_alla else 0.0)
            # Guardamos también cuánto se movió al REVÉS. Si el recorrido fue
            # casi todo al revés, el eje está invertido respecto a lo que se
            # pidió, y hay que avisarlo: si no, el alcance sale 0, el umbral
            # cae al piso de seguridad y los gestos de ese eje terminan
            # moviendo el foco al lado contrario sin explicación.
            al_reves = sorted(-d for d in desv if d < 0)
            self._al_reves[nombre] = (al_reves[int(len(al_reves) * 0.8)]
                                      if al_reves else 0.0)

        if self._paso < len(PASOS) - 1:
            self._paso += 1
            self._entrar_paso()
        else:
            self._timer.stop()
            self._guardar()
            self.accept()

    def ejes_invertidos(self):
        """Ejes donde el movimiento fue mayormente AL REVÉS de lo pedido.
        Casi siempre significa que la señal de ese eje tiene el signo
        cambiado (p. ej. por la imagen en espejo)."""
        invertidos = set()
        for nombre, eje in (("izquierda", "x"), ("derecha", "x"),
                            ("arriba", "y"), ("abajo", "y")):
            bien = self.alcances.get(nombre, 0.0)
            reves = self._al_reves.get(nombre, 0.0)
            if reves > max(bien * 2, 0.1):
                invertidos.add(eje)
        return invertidos

    def _guardar(self):
        minimo = float(_config.get("calib_umbral_minimo", 0.12))
        # El umbral también tiene que quedar claramente por encima del
        # temblor en reposo: si no, ese eje se dispara solo sin que la
        # persona mueva la cabeza.
        veces_ruido = float(_config.get("calib_umbral_veces_ruido", 3.0))
        piso = {"izquierda": self.ruido[0], "derecha": self.ruido[0],
                "arriba": self.ruido[1], "abajo": self.ruido[1]}

        umbrales = {}
        for d in ("izquierda", "derecha", "arriba", "abajo"):
            # Piso de seguridad: si alguien no alcanzó a moverse en un paso,
            # un umbral diminuto haría que ese lado se dispare sin parar.
            umbrales[d] = round(max(minimo,
                                    piso[d] * veces_ruido,
                                    self.alcances.get(d, 0.0) * FRACCION), 4)

        datos = {"centro": list(self.centro),
                 "ruido": {"x": round(self.ruido[0], 4), "y": round(self.ruido[1], 4)},
                 "umbrales": umbrales,
                 "alcances": {k: round(v, 4) for k, v in self.alcances.items()}}
        with open(RUTA_CALIBRACION, "w") as f:
            json.dump(datos, f, indent=2)
        self.guardado = True
        print(f"[calibracion] centro={datos['centro']} umbrales={umbrales}")

        for eje in self.ejes_invertidos():
            clave = "mp_invert_x" if eje == "x" else "mp_invert_y"
            self.aviso = (f"El eje {eje.upper()} está invertido: al pedir un "
                          f"sentido, la cabeza se movió al contrario. "
                          f"Cambia \"{clave}\" en config.json.")
            print(f"[calibracion] AVISO: {self.aviso}")
