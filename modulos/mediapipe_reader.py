import cv2
import mediapipe as mp
import numpy as np
import json
import time
import math

with open('config.json', 'r') as f:
    config = json.load(f)

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

def obtener_angulos_cabeza(image, face_landmarks):
    img_h, img_w, _ = image.shape
    face_2d = []
    face_3d = []

    puntos_clave = [1, 152, 33, 263, 61, 291]
    for idx, lm in enumerate(face_landmarks.landmark):
        if idx in puntos_clave:
            x, y = int(lm.x * img_w), int(lm.y * img_h)
            face_2d.append([x, y])
            face_3d.append([x, y, lm.z])

    face_2d = np.array(face_2d, dtype=np.float64)
    face_3d = np.array(face_3d, dtype=np.float64)

    focal_length = 1 * img_w
    cam_matrix = np.array([[focal_length, 0, img_w / 2],
                           [0, focal_length, img_h / 2],
                           [0, 0, 1]])
    dist_matrix = np.zeros((4, 1), dtype=np.float64)

    success, rot_vec, trans_vec = cv2.solvePnP(face_3d, face_2d, cam_matrix, dist_matrix)
    rmat, _ = cv2.Rodrigues(rot_vec)
    angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)

    yaw = angles[1] * 360
    pitch = angles[0] * 360
    return yaw, pitch

def distancia(p1, p2, w, h):
    return math.hypot((p2.x - p1.x) * w, (p2.y - p1.y) * h)

def generador_mediapipe():
    cam_idx = int(config.get("camera_index", 0))
    cap = cv2.VideoCapture(cam_idx)

    while cap.isOpened():
        success, image = cap.read()
        if not success:
            time.sleep(0.1)
            continue

        image = cv2.cvtColor(cv2.flip(image, 1), cv2.COLOR_BGR2RGB)
        image.flags.writeable = False
        results = face_mesh.process(image)

        image.flags.writeable = True
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

        hx, hy, au45, conf, y_51, y_57 = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                yaw, pitch = obtener_angulos_cabeza(image, face_landmarks)

                hx = yaw / 100.0   
                hy = -pitch / 100.0 

                img_h, img_w, _ = image.shape

                dist_boca = distancia(face_landmarks.landmark[13], face_landmarks.landmark[14], img_w, img_h)
                y_57 = dist_boca * 4.0 

                v_izq = distancia(face_landmarks.landmark[159], face_landmarks.landmark[145], img_w, img_h)
                h_izq = distancia(face_landmarks.landmark[33], face_landmarks.landmark[133], img_w, img_h)
                ear_izq = v_izq / (h_izq + 1e-6)

                v_der = distancia(face_landmarks.landmark[386], face_landmarks.landmark[374], img_w, img_h)
                h_der = distancia(face_landmarks.landmark[362], face_landmarks.landmark[263], img_w, img_h)
                ear_der = v_der / (h_der + 1e-6)

                if ear_izq < 0.22 and ear_der < 0.22:
                    au45 = 1.0 
                else:
                    au45 = 0.0

                conf = 0.98

                mp.solutions.drawing_utils.draw_landmarks(
                    image=image,
                    landmark_list=face_landmarks,
                    connections=mp_face_mesh.FACEMESH_TESSELATION,
                    landmark_drawing_spec=None,
                    connection_drawing_spec=mp.solutions.drawing_styles.get_default_face_mesh_tesselation_style())

        cv2.imshow("Vision Inteligente - Sillodromo", image)
        cv2.waitKey(1)

        yield hx, hy, au45, conf, y_51, y_57

    cap.release()
    cv2.destroyAllWindows()