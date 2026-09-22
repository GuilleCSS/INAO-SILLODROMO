"""
Lector de bioseñales con MediaPipe FaceMesh.

Abre la cámara y hace el rastreo en el MISMO proceso de la aplicación (no
hay binario externo, ni CSV intermedio, ni dos programas peleando por la
cámara). Eso permite tres cosas que con un proceso aparte eran imposibles:

  1. Mostrar en la interfaz exactamente los frames que ve el detector.
  2. MEJORAR la imagen antes de detectar (los filtros sí suben la calidad
     de detección, no son solo cosméticos).
  3. Ajustar la cámara (exposición, brillo) porque somos sus dueños.

Al arrancar se hace un "reconocimiento de escenario": se miden unos frames
para ver qué tan oscura/plana está la imagen, y con eso se decide cuánto
filtro aplicar el resto de la sesión (ver `analizar_escenario`).

generador_mediapipe() yield-ea (frame, hx, hy, au45_c, conf, y_51, y_57):
el mismo contrato de datos que espera GazeStateController.process_frame(),
más el frame ya listo para mostrarse.
"""

import os
import json
import math
import time

import cv2
import numpy as np
import mediapipe as mp

with open("config.json", "r") as f:
    config = json.load(f)

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    # refine_landmarks mejora la precisión de ojos y labios (justo lo que
    # usamos para el parpadeo y el clic), a cambio de algo de CPU. Se deja
    # configurable por si hace falta aligerar en un equipo lento.
    refine_landmarks=bool(config.get("mp_refine_landmarks", True)),
    min_detection_confidence=config.get("mp_detection_confidence", 0.60),
    min_tracking_confidence=config.get("mp_tracking_confidence", 0.60),
)

# --- Modelo 3D genérico de cara, para estimar el yaw con solvePnP ---
MODEL_POINTS = np.array([
    [0.0, 0.0, 0.0],           # Nariz
    [0.0, -330.0, -65.0],      # Barbilla
    [-225.0, 170.0, -135.0],   # Ojo izquierdo
    [225.0, 170.0, -135.0],    # Ojo derecho
    [-150.0, -150.0, -125.0],  # Boca izquierda
    [150.0, -150.0, -125.0],   # Boca derecha
], dtype=np.float64)

LANDMARK_IDS = [1, 152, 33, 263, 61, 291]  # nariz, barbilla, ojos, boca


# ============================================================
# RECONOCIMIENTO DE ESCENARIO Y MEJORA DE IMAGEN
# ============================================================

class MejoradorImagen:
    """
    Mide la escena real al arrancar y aplica solo el filtro que haga falta.

    Aplicar siempre el mismo filtro a ciegas puede empeorar las cosas (subir
    el brillo de una imagen ya bien expuesta la quema y se pierden los
    bordes que el detector necesita). Por eso primero se observa y después
    se decide, y todo se aplica sobre la LUMINANCIA: tocar los canales de
    color por separado desplazaría los tonos de piel, que es justo lo que
    MediaPipe usa para encontrar la cara.
    """

    def __init__(self):
        self.listo = False
        self.gamma = 1.0
        self.usar_clahe = False
        self._tabla_gamma = None
        self._clahe = None
        self._muestras = []
        self.resumen = "Analizando escenario…"

    def analizar(self, frame):
        """Acumula frames hasta tener suficientes para decidir los filtros."""
        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._muestras.append((float(gris.mean()), float(gris.std())))

        if len(self._muestras) < int(config.get("escena_frames", 30)):
            return

        brillo = sum(m[0] for m in self._muestras) / len(self._muestras)
        contraste = sum(m[1] for m in self._muestras) / len(self._muestras)

        # Gamma < 1 aclara. Se apunta a un brillo medio cómodo (~120 de 255)
        # y se limita el rango para no destruir la imagen si la medición
        # sale rara (p. ej. alguien tapó la cámara durante el análisis).
        objetivo = float(config.get("escena_brillo_objetivo", 120.0))
        if brillo < 5.0:
            self.gamma = 1.0  # prácticamente a oscuras: no hay nada que rescatar
        else:
            self.gamma = max(0.45, min(1.6, math.log(objetivo / 255.0) / math.log(brillo / 255.0)))

        # CLAHE solo si la imagen está "plana" (poco contraste): recupera los
        # bordes de ojos y boca sin quemar el resto.
        self.usar_clahe = contraste < float(config.get("escena_contraste_min", 45.0))

        if abs(self.gamma - 1.0) > 0.03:
            i = np.arange(256, dtype=np.float32) / 255.0
            self._tabla_gamma = np.clip((i ** self.gamma) * 255.0, 0, 255).astype(np.uint8)
        if self.usar_clahe:
            self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        filtros = []
        if self._tabla_gamma is not None:
            filtros.append(f"gamma {self.gamma:.2f}")
        if self.usar_clahe:
            filtros.append("CLAHE")
        self.resumen = (
            f"brillo {brillo:.0f} · contraste {contraste:.0f} · "
            + (" + ".join(filtros) if filtros else "sin filtros (imagen ya buena)")
        )
        self.listo = True
        print(f"[escena] {self.resumen}")

    def aplicar(self, frame):
        if not self.listo or (self._tabla_gamma is None and not self.usar_clahe):
            return frame

        # Se trabaja en YUV para tocar solo la luminancia (Y) y dejar el
        # color intacto.
        yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
        canal_y = yuv[:, :, 0]
        if self._tabla_gamma is not None:
            canal_y = cv2.LUT(canal_y, self._tabla_gamma)
        if self._clahe is not None:
            canal_y = self._clahe.apply(canal_y)
        yuv[:, :, 0] = canal_y
        return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)


# ============================================================
# REGISTRO DE SEÑALES (para ajustar umbrales con datos reales)
# ============================================================

class RegistroSenales:
    """
    Guarda las señales crudas en un CSV mientras se usa la app con
    normalidad.

    Antes esto se imprimía en consola, que es inservible aquí: la app corre
    en pantalla completa y tapa la terminal, así que no hay forma de leer
    los valores mientras se hacen los gestos. Con el archivo no hace falta
    ningún asistente de calibración ni transcribir nada a mano: se usa la
    app normal y después se analiza el registro.
    """

    def __init__(self):
        self.activo = bool(config.get("registro_senales", True))
        if not self.activo:
            return
        self.ruta = config.get("registro_ruta", "diagnostico_senales.csv")
        self.intervalo = 1.0 / max(1, int(config.get("registro_hz", 10)))
        self.max_filas = int(config.get("registro_max_filas", 20000))
        self._filas = 0
        self._ultimo = 0.0
        try:
            self._f = open(self.ruta, "w", buffering=1)  # line buffered: legible en vivo
            self._f.write("t,hx,hy,vertical,yaw,boca,ear,fps\n")
        except OSError as e:
            print(f"[registro] no se pudo abrir {self.ruta}: {e}")
            self.activo = False

    def anotar(self, ahora, hx, hy, vertical, yaw, boca, ear, fps):
        if not self.activo or self._filas >= self.max_filas:
            return
        if (ahora - self._ultimo) < self.intervalo:
            return
        self._ultimo = ahora
        self._filas += 1
        try:
            self._f.write(f"{ahora:.3f},{hx:.4f},{hy:.4f},{vertical:.4f},"
                          f"{yaw:.2f},{boca:.2f},{ear:.4f},{fps:.1f}\n")
        except OSError:
            self.activo = False

    def cerrar(self):
        if self.activo:
            try:
                self._f.close()
            except OSError:
                pass


# ============================================================
# MEDICIONES SOBRE LA MALLA FACIAL
# ============================================================

def distancia(p1, p2, w, h):
    return math.hypot((p2.x - p1.x) * w, (p2.y - p1.y) * h)


def obtener_yaw(frame, face_landmarks):
    """Ángulo de giro de la cabeza (izquierda/derecha) vía solvePnP, en grados."""
    img_h, img_w, _ = frame.shape
    image_points = np.array(
        [[face_landmarks.landmark[i].x * img_w, face_landmarks.landmark[i].y * img_h]
         for i in LANDMARK_IDS],
        dtype=np.float64,
    )
    focal_length = float(img_w)
    camera_matrix = np.array([
        [focal_length, 0, img_w / 2.0],
        [0, focal_length, img_h / 2.0],
        [0, 0, 1],
    ], dtype=np.float64)

    exito, rotation_vector, _ = cv2.solvePnP(
        MODEL_POINTS, image_points, camera_matrix, np.zeros((4, 1)),
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not exito:
        return 0.0

    rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
    sy = math.sqrt(rotation_matrix[0, 0] ** 2 + rotation_matrix[1, 0] ** 2)
    yaw = math.degrees(math.atan2(-rotation_matrix[2, 0], sy))
    return float(np.clip(yaw, -60.0, 60.0))


def obtener_control_vertical(face_landmarks):
    """
    Señal vertical: posición de la nariz respecto al centro de los ojos,
    normalizada por la distancia entre ojos (así acercarse o alejarse de la
    cámara casi no la afecta). No usa pitch de solvePnP porque ahí resulta
    mucho más ruidoso que el yaw.

    Ojo: en reposo esta señal NO vale 0 (la nariz siempre está por debajo de
    los ojos); el valor de reposo lo absorbe el auto-centrado de
    GazeStateController, así que aquí solo importa que varíe de forma
    consistente al subir y bajar la cara.
    """
    ojo_izq = face_landmarks.landmark[33]
    ojo_der = face_landmarks.landmark[263]
    nariz = face_landmarks.landmark[1]

    centro_ojos_y = (ojo_izq.y + ojo_der.y) / 2.0
    distancia_ojos = math.hypot(ojo_der.x - ojo_izq.x, ojo_der.y - ojo_izq.y)
    return (nariz.y - centro_ojos_y) / (distancia_ojos + 1e-6)


def calcular_ear(face_landmarks, img_w, img_h):
    """Eye Aspect Ratio promedio de ambos ojos (baja cuando se cierran)."""
    def ear_de(v1a, v1b, v2a, v2b, ha, hb):
        v1 = distancia(face_landmarks.landmark[v1a], face_landmarks.landmark[v1b], img_w, img_h)
        v2 = distancia(face_landmarks.landmark[v2a], face_landmarks.landmark[v2b], img_w, img_h)
        h = distancia(face_landmarks.landmark[ha], face_landmarks.landmark[hb], img_w, img_h)
        return ((v1 + v2) / 2.0) / (h + 1e-6)

    ear_izq = ear_de(159, 145, 158, 153, 33, 133)
    ear_der = ear_de(386, 374, 385, 380, 362, 263)
    return (ear_izq + ear_der) / 2.0


def calcular_apertura_boca(face_landmarks, img_w, img_h):
    """Apertura de boca normalizada por su ancho (escala 0-100 aprox.)."""
    apertura = distancia(face_landmarks.landmark[13], face_landmarks.landmark[14], img_w, img_h)
    ancho = distancia(face_landmarks.landmark[78], face_landmarks.landmark[308], img_w, img_h)
    return (apertura / (ancho + 1e-6)) * 100.0


# ============================================================
# GENERADOR PRINCIPAL
# ============================================================

def generador_mediapipe():
    """
    Abre la cámara, analiza el escenario, y entrega frame a frame
    (frame_para_mostrar, hx, hy, au45_c, conf, y_51, y_57).
    """
    cam_idx = int(config.get("camera_index", 0))
    if os.name == "nt":
        cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(cam_idx)
    else:
        cap = cv2.VideoCapture(cam_idx)

    # BUFFERSIZE=1 es clave: sin esto la cámara acumula frames viejos en cola
    # y el control se siente retrasado aunque el detector vaya rápido.
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config.get("cam_width", 1280)))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config.get("cam_height", 720)))
    cap.set(cv2.CAP_PROP_FPS, int(config.get("camera_fps", 30)))

    yaw_normalizacion = float(config.get("mp_yaw_normalization_deg", 35.0))
    escala_vertical = float(config.get("mp_vertical_scale", 4.0))
    invertir_x = bool(config.get("mp_invert_x", False))
    invertir_y = bool(config.get("mp_invert_y", False))
    eye_threshold = float(config.get("mp_eye_closed_threshold", 0.20))
    espejo = bool(config.get("camara_espejo", True))
    dibujar_malla = bool(config.get("mostrar_malla", False))
    registro = RegistroSenales()

    # El detector corre sobre una copia reducida: MediaPipe no gana precisión
    # útil con más resolución para esta tarea, y bajarla aligera bastante la
    # CPU. La imagen que se muestra sigue siendo la de resolución completa.
    ancho_deteccion = int(config.get("mp_ancho_deteccion", 640))

    mejorador = MejoradorImagen()
    ultimo_tiempo = time.perf_counter()
    fps_suavizado = 0.0

    try:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue

            if espejo:
                frame = cv2.flip(frame, 1)

            # --- Reconocimiento de escenario (solo al principio) ---
            if not mejorador.listo:
                mejorador.analizar(frame)

            # --- Mejora de imagen ANTES de detectar ---
            frame = mejorador.aplicar(frame)

            # --- Detección sobre una copia reducida ---
            alto_orig, ancho_orig = frame.shape[:2]
            if ancho_deteccion and ancho_orig > ancho_deteccion:
                escala = ancho_deteccion / float(ancho_orig)
                frame_det = cv2.resize(frame, (ancho_deteccion, int(alto_orig * escala)))
            else:
                frame_det = frame

            rgb = cv2.cvtColor(frame_det, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            resultados = face_mesh.process(rgb)

            hx = hy = au45 = conf = y_51 = y_57 = 0.0
            yaw = senal_vertical = apertura_boca = ear = 0.0

            if resultados.multi_face_landmarks:
                face_landmarks = resultados.multi_face_landmarks[0]
                img_h, img_w = frame_det.shape[:2]

                yaw = obtener_yaw(frame_det, face_landmarks)
                hx = yaw / yaw_normalizacion
                if invertir_x:
                    hx = -hx

                senal_vertical = obtener_control_vertical(face_landmarks)
                hy = senal_vertical * escala_vertical
                if invertir_y:
                    hy = -hy

                apertura_boca = calcular_apertura_boca(face_landmarks, img_w, img_h)
                y_51, y_57 = 0.0, apertura_boca

                ear = calcular_ear(face_landmarks, img_w, img_h)
                au45 = 1.0 if ear < eye_threshold else 0.0

                conf = 0.98

                if dibujar_malla:
                    mp.solutions.drawing_utils.draw_landmarks(
                        image=frame,
                        landmark_list=face_landmarks,
                        connections=mp_face_mesh.FACEMESH_TESSELATION,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=mp.solutions.drawing_styles.get_default_face_mesh_tesselation_style(),
                    )

            ahora = time.perf_counter()
            dt = max(ahora - ultimo_tiempo, 1e-6)
            ultimo_tiempo = ahora
            fps_actual = 1.0 / dt
            fps_suavizado = fps_actual if fps_suavizado == 0.0 else (0.10 * fps_actual + 0.90 * fps_suavizado)

            registro.anotar(ahora, hx, hy, senal_vertical, yaw,
                            apertura_boca, ear, fps_suavizado)

            yield frame, hx, hy, au45, conf, y_51, y_57
    finally:
        registro.cerrar()
        cap.release()
