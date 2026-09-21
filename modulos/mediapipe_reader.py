"""
Lector de bioseñales con MediaPipe FaceMesh, en reemplazo de OpenFace.

A diferencia de openface_reader.py (que lanza un binario externo y lee su
CSV), este módulo abre la cámara directamente y hace el tracking en el
mismo proceso Python — no hay subproceso ni archivos intermedios, y solo
se abre la cámara una vez (antes, OpenFace y el panel de vista previa de
la interfaz competían por el mismo dispositivo).

generador_mediapipe() yield-ea (frame, hx, hy, au45_c, conf, y_51, y_57):
mismo orden que espera GazeStateController.process_frame(), más el frame
ya anotado para mostrarlo en el panel de cámara de la interfaz.
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
    refine_landmarks=True,
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
    Posición vertical de la nariz respecto al centro de los ojos, normalizada
    por la distancia entre ojos (para que acercarse/alejarse de la cámara
    afecte lo mínimo posible). No depende de pitch/solvePnP.
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


def generador_mediapipe():
    """
    Abre la cámara, corre MediaPipe FaceMesh frame a frame, y va entregando
    (frame_anotado, hx, hy, au45_c, conf, y_51, y_57) — el mismo contrato de
    datos que antes daba stream_openface_csv(), más el frame para la vista
    previa embebida.
    """
    cam_idx = int(config.get("camera_index", 0))
    if os.name == "nt":
        cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(cam_idx)
    else:
        cap = cv2.VideoCapture(cam_idx)

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config.get("cam_width", 1280)))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config.get("cam_height", 720)))
    cap.set(cv2.CAP_PROP_FPS, int(config.get("camera_fps", 30)))

    yaw_normalizacion = float(config.get("mp_yaw_normalization_deg", 35.0))
    escala_vertical = float(config.get("mp_vertical_scale", 4.0))
    invertir_x = bool(config.get("mp_invert_x", False))
    invertir_y = bool(config.get("mp_invert_y", False))
    eye_threshold = float(config.get("mp_eye_closed_threshold", 0.20))
    mostrar_debug = bool(config.get("mp_debug_overlay", False))
    # La app ya muestra la cámara en su propio panel embebido — no abrir
    # además la ventana nativa de OpenCV (sería una segunda ventana suelta).
    mostrar_camara = bool(config.get("mp_show_camera", False))

    ultimo_tiempo = time.perf_counter()
    fps_suavizado = 0.0

    try:
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue

            frame = cv2.flip(frame, 1)  # espejo, igual que camara.py antes
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            resultados = face_mesh.process(rgb)
            rgb.flags.writeable = True

            hx = hy = au45 = conf = y_51 = y_57 = 0.0
            yaw = señal_vertical = apertura_boca = ear = 0.0

            if resultados.multi_face_landmarks:
                face_landmarks = resultados.multi_face_landmarks[0]
                img_h, img_w, _ = frame.shape

                yaw = obtener_yaw(frame, face_landmarks)
                hx = yaw / yaw_normalizacion
                if invertir_x:
                    hx = -hx

                señal_vertical = obtener_control_vertical(face_landmarks)
                hy = señal_vertical * escala_vertical
                if invertir_y:
                    hy = -hy

                apertura_boca = calcular_apertura_boca(face_landmarks, img_w, img_h)
                y_51, y_57 = 0.0, apertura_boca

                ear = calcular_ear(face_landmarks, img_w, img_h)
                au45 = 1.0 if ear < eye_threshold else 0.0

                conf = 0.98

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

            if mostrar_debug:
                cv2.putText(frame, f"Yaw: {yaw:5.1f}  HX: {hx:+.3f}", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 0), 2)
                cv2.putText(frame, f"Vertical: {señal_vertical:.3f}  HY: {hy:+.3f}", (10, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2)
                cv2.putText(frame, f"Boca: {apertura_boca:4.1f}  EAR: {ear:.3f}", (10, 75),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 0), 2)
                cv2.putText(frame, f"FPS: {fps_suavizado:4.1f}", (10, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 0), 2)

            if mostrar_camara:
                cv2.imshow("Sillodromo · MediaPipe", frame)
                if (cv2.waitKey(1) & 0xFF) == 27:
                    break

            yield frame, hx, hy, au45, conf, y_51, y_57
    finally:
        cap.release()
        if mostrar_camara:
            cv2.destroyAllWindows()
