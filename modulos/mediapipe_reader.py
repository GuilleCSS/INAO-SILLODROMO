import os
import cv2
import mediapipe as mp
import numpy as np
import json
import time
import math


# ============================================================
# CONFIGURACIÓN
# ============================================================

with open("config.json", "r") as f:
    config = json.load(f)


# ============================================================
# MEDIAPIPE FACE MESH
# ============================================================

mp_face_mesh = mp.solutions.face_mesh

face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=config.get(
        "mp_detection_confidence",
        0.60
    ),
    min_tracking_confidence=config.get(
        "mp_tracking_confidence",
        0.60
    )
)


# ============================================================
# MODELO 3D PARA ESTIMAR YAW
# ============================================================

MODEL_POINTS = np.array(
    [
        [0.0, 0.0, 0.0],           # Nariz
        [0.0, -330.0, -65.0],      # Barbilla
        [-225.0, 170.0, -135.0],   # Ojo izquierdo
        [225.0, 170.0, -135.0],    # Ojo derecho
        [-150.0, -150.0, -125.0],  # Boca izquierda
        [150.0, -150.0, -125.0],   # Boca derecha
    ],
    dtype=np.float64
)

LANDMARK_IDS = [
    1,      # Nariz
    152,    # Barbilla
    33,     # Ojo izquierdo
    263,    # Ojo derecho
    61,     # Boca izquierda
    291     # Boca derecha
]


# ============================================================
# DISTANCIA
# ============================================================

def distancia(p1, p2, w, h):
    return math.hypot(
        (p2.x - p1.x) * w,
        (p2.y - p1.y) * h
    )


# ============================================================
# YAW DE LA CABEZA
# ============================================================

def obtener_yaw(image, face_landmarks):

    img_h, img_w, _ = image.shape

    image_points = []

    for idx in LANDMARK_IDS:

        lm = face_landmarks.landmark[idx]

        image_points.append(
            [
                lm.x * img_w,
                lm.y * img_h
            ]
        )

    image_points = np.array(
        image_points,
        dtype=np.float64
    )

    focal_length = float(img_w)

    camera_matrix = np.array(
        [
            [focal_length, 0, img_w / 2.0],
            [0, focal_length, img_h / 2.0],
            [0, 0, 1]
        ],
        dtype=np.float64
    )

    dist_coeffs = np.zeros(
        (4, 1),
        dtype=np.float64
    )

    success, rotation_vector, translation_vector = cv2.solvePnP(
        MODEL_POINTS,
        image_points,
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE
    )

    if not success:
        return 0.0

    rotation_matrix, _ = cv2.Rodrigues(
        rotation_vector
    )

    sy = math.sqrt(
        rotation_matrix[0, 0] ** 2
        +
        rotation_matrix[1, 0] ** 2
    )

    yaw = math.atan2(
        -rotation_matrix[2, 0],
        sy
    )

    yaw = math.degrees(yaw)

    return float(
        np.clip(
            yaw,
            -60.0,
            60.0
        )
    )


# ============================================================
# CONTROL VERTICAL
# ============================================================

def obtener_control_vertical(face_landmarks):
    """
    Calcula la posición vertical de la nariz respecto al centro
    de los ojos.

    Se normaliza usando la distancia entre los ojos para que
    acercarse o alejarse de la cámara afecte lo mínimo posible.
    """

    ojo_izquierdo = face_landmarks.landmark[33]
    ojo_derecho = face_landmarks.landmark[263]
    nariz = face_landmarks.landmark[1]

    centro_ojos_x = (
        ojo_izquierdo.x
        +
        ojo_derecho.x
    ) / 2.0

    centro_ojos_y = (
        ojo_izquierdo.y
        +
        ojo_derecho.y
    ) / 2.0

    distancia_ojos = math.hypot(
        ojo_derecho.x - ojo_izquierdo.x,
        ojo_derecho.y - ojo_izquierdo.y
    )

    señal_vertical = (
        nariz.y
        -
        centro_ojos_y
    ) / (
        distancia_ojos + 1e-6
    )

    return señal_vertical


# ============================================================
# EYE ASPECT RATIO
# ============================================================

def calcular_ear(
    face_landmarks,
    img_w,
    img_h
):

    # --------------------------------------------------------
    # OJO IZQUIERDO
    # --------------------------------------------------------

    izq_v1 = distancia(
        face_landmarks.landmark[159],
        face_landmarks.landmark[145],
        img_w,
        img_h
    )

    izq_v2 = distancia(
        face_landmarks.landmark[158],
        face_landmarks.landmark[153],
        img_w,
        img_h
    )

    izq_h = distancia(
        face_landmarks.landmark[33],
        face_landmarks.landmark[133],
        img_w,
        img_h
    )

    ear_izq = (
        (izq_v1 + izq_v2) / 2.0
    ) / (
        izq_h + 1e-6
    )

    # --------------------------------------------------------
    # OJO DERECHO
    # --------------------------------------------------------

    der_v1 = distancia(
        face_landmarks.landmark[386],
        face_landmarks.landmark[374],
        img_w,
        img_h
    )

    der_v2 = distancia(
        face_landmarks.landmark[385],
        face_landmarks.landmark[380],
        img_w,
        img_h
    )

    der_h = distancia(
        face_landmarks.landmark[362],
        face_landmarks.landmark[263],
        img_w,
        img_h
    )

    ear_der = (
        (der_v1 + der_v2) / 2.0
    ) / (
        der_h + 1e-6
    )

    return (
        ear_izq
        +
        ear_der
    ) / 2.0


# ============================================================
# APERTURA NORMALIZADA DE BOCA
# ============================================================

def calcular_apertura_boca(
    face_landmarks,
    img_w,
    img_h
):

    apertura = distancia(
        face_landmarks.landmark[13],
        face_landmarks.landmark[14],
        img_w,
        img_h
    )

    ancho = distancia(
        face_landmarks.landmark[78],
        face_landmarks.landmark[308],
        img_w,
        img_h
    )

    ratio = (
        apertura
        /
        (ancho + 1e-6)
    )

    # Convertimos a una escala cómoda.
    return ratio * 100.0


# ============================================================
# GENERADOR PRINCIPAL
# ============================================================

def generador_mediapipe():

    cam_idx = int(
        config.get(
            "camera_index",
            0
        )
    )

    # --------------------------------------------------------
    # DIRECTSHOW EN WINDOWS
    # --------------------------------------------------------

    if os.name == "nt":

        cap = cv2.VideoCapture(
            cam_idx,
            cv2.CAP_DSHOW
        )

        if not cap.isOpened():

            cap = cv2.VideoCapture(
                cam_idx
            )

    else:

        cap = cv2.VideoCapture(
            cam_idx
        )

    # --------------------------------------------------------
    # CONFIGURACIÓN DE CÁMARA
    # --------------------------------------------------------

    cap.set(
        cv2.CAP_PROP_BUFFERSIZE,
        1
    )

    cap.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        int(
            config.get(
                "camera_width",
                640
            )
        )
    )

    cap.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        int(
            config.get(
                "camera_height",
                480
            )
        )
    )

    cap.set(
        cv2.CAP_PROP_FPS,
        int(
            config.get(
                "camera_fps",
                30
            )
        )
    )

    # ========================================================
    # CONFIGURACIÓN DE SEÑALES
    # ========================================================

    yaw_normalizacion = float(
        config.get(
            "mp_yaw_normalization_deg",
            35.0
        )
    )

    escala_vertical = float(
        config.get(
            "mp_vertical_scale",
            4.0
        )
    )

    invertir_x = bool(
        config.get(
            "mp_invert_x",
            False
        )
    )

    invertir_y = bool(
        config.get(
            "mp_invert_y",
            False
        )
    )

    eye_threshold = float(
        config.get(
            "mp_eye_closed_threshold",
            0.20
        )
    )

    mostrar_debug = bool(
        config.get(
            "mp_debug_overlay",
            True
        )
    )

    mostrar_camara = bool(
        config.get(
            "mp_show_camera",
            True
        )
    )

    ultimo_tiempo = time.perf_counter()

    fps_suavizado = 0.0


    try:

        while cap.isOpened():

            success, frame = cap.read()

            if not success:

                time.sleep(
                    0.01
                )

                continue

            # =================================================
            # ESPEJO
            # =================================================

            frame = cv2.flip(
                frame,
                1
            )

            rgb = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2RGB
            )

            rgb.flags.writeable = False

            results = face_mesh.process(
                rgb
            )

            rgb.flags.writeable = True

            # =================================================
            # VALORES POR DEFECTO
            # =================================================

            hx = 0.0
            hy = 0.0

            au45 = 0.0

            conf = 0.0

            y_51 = 0.0
            y_57 = 0.0

            yaw = 0.0

            señal_vertical = 0.0

            apertura_boca = 0.0

            ear = 0.0


            # =================================================
            # CARA DETECTADA
            # =================================================

            if results.multi_face_landmarks:

                face_landmarks = (
                    results.multi_face_landmarks[0]
                )

                img_h, img_w, _ = (
                    frame.shape
                )


                # =============================================
                # EJE X - YAW
                # =============================================

                yaw = obtener_yaw(
                    frame,
                    face_landmarks
                )

                hx = (
                    yaw
                    /
                    yaw_normalizacion
                )

                # IMPORTANTE:
                # En tu equipo true dejaba X invertido.
                # El config nuevo usa false.
                if invertir_x:

                    hx = -hx


                # =============================================
                # EJE Y
                #
                # Ya NO depende de pitch/solvePnP.
                # =============================================

                señal_vertical = (
                    obtener_control_vertical(
                        face_landmarks
                    )
                )

                hy = (
                    señal_vertical
                    *
                    escala_vertical
                )

                if invertir_y:

                    hy = -hy


                # =============================================
                # BOCA
                # =============================================

                apertura_boca = (
                    calcular_apertura_boca(
                        face_landmarks,
                        img_w,
                        img_h
                    )
                )

                y_51 = 0.0
                y_57 = apertura_boca


                # =============================================
                # OJOS
                # =============================================

                ear = calcular_ear(
                    face_landmarks,
                    img_w,
                    img_h
                )

                if ear < eye_threshold:

                    au45 = 1.0

                else:

                    au45 = 0.0


                # =============================================
                # CONFIANZA
                # =============================================

                conf = 0.98


                # =============================================
                # DIBUJAR MALLA
                # =============================================

                mp.solutions.drawing_utils.draw_landmarks(
                    image=frame,
                    landmark_list=face_landmarks,
                    connections=mp_face_mesh.FACEMESH_TESSELATION,
                    landmark_drawing_spec=None,
                    connection_drawing_spec=(
                        mp.solutions.drawing_styles
                        .get_default_face_mesh_tesselation_style()
                    )
                )


            # =================================================
            # FPS
            # =================================================

            ahora = time.perf_counter()

            dt = max(
                ahora - ultimo_tiempo,
                1e-6
            )

            ultimo_tiempo = ahora

            fps_actual = (
                1.0 / dt
            )

            if fps_suavizado == 0.0:

                fps_suavizado = fps_actual

            else:

                fps_suavizado = (
                    0.10 * fps_actual
                    +
                    0.90 * fps_suavizado
                )


            # =================================================
            # DEBUG VISUAL
            # =================================================

            if mostrar_debug:

                cv2.putText(
                    frame,
                    f"Yaw: {yaw:5.1f}   HX: {hx:+.3f}",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.58,
                    (0, 255, 0),
                    2
                )

                cv2.putText(
                    frame,
                    f"Vertical: {señal_vertical:.3f}   HY: {hy:+.3f}",
                    (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.58,
                    (0, 255, 255),
                    2
                )

                cv2.putText(
                    frame,
                    f"Boca: {apertura_boca:4.1f}   EAR: {ear:.3f}",
                    (10, 75),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.58,
                    (0, 255, 0),
                    2
                )

                cv2.putText(
                    frame,
                    f"FPS: {fps_suavizado:4.1f}",
                    (10, 100),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.58,
                    (0, 255, 0),
                    2
                )


            # =================================================
            # MOSTRAR CÁMARA
            # =================================================

            if mostrar_camara:

                cv2.imshow(
                    "Vision Inteligente - Sillodromo",
                    frame
                )

                key = (
                    cv2.waitKey(1)
                    &
                    0xFF
                )

                if key == 27:
                    break


            # =================================================
            # DEVOLVER DATOS
            # =================================================

            yield (
                hx,
                hy,
                au45,
                conf,
                y_51,
                y_57
            )


    finally:

        cap.release()

        cv2.destroyAllWindows()