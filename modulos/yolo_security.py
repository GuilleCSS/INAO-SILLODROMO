import cv2
from ultralytics import YOLO
from PyQt5.QtCore import QThread, pyqtSignal

class HiloSeguridadYOLO(QThread):
    # Ahora enviamos un Booleano (True = Hay peligro, False = Camino Libre)
    senal_emergencia = pyqtSignal(bool) 

    def __init__(self, camera_index=0): 
        super().__init__()
        self.camera_index = camera_index
        self.corriendo = True
        self.modelo = YOLO('yolov8n.pt') 
        self.estado_peligro = False # Memoria del estado anterior

    def run(self):
        cap = cv2.VideoCapture(self.camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        contador_frames = 0
        
        while self.corriendo and cap.isOpened():
            success, frame = cap.read()
            if not success:
                continue

            contador_frames += 1
            if contador_frames % 3 != 0:
                continue 

            resultados = self.modelo(frame, verbose=False, classes=[0], imgsz=320) 
            
            peligro_actual = False
            for r in resultados:
                for caja in r.boxes:
                    x1, y1, x2, y2 = caja.xyxy[0]
                    area_objeto = (x2 - x1) * (y2 - y1)
                    h, w, _ = frame.shape
                    
                    if (area_objeto / (w * h)) > 0.40:
                        peligro_actual = True
                        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 3)
                    else:
                        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 3)

            # LÓGICA DE ESTADOS: Solo emite la señal cuando el estado CAMBIA (evita el spam)
            if peligro_actual and not self.estado_peligro:
                self.estado_peligro = True
                self.senal_emergencia.emit(True)  # Inicia emergencia
            elif not peligro_actual and self.estado_peligro:
                self.estado_peligro = False
                self.senal_emergencia.emit(False) # Termina emergencia

            cv2.imshow("Escudo Anticolision - YOLO (Camara Externa)", frame)
            cv2.waitKey(1)

    def detener(self):
        self.corriendo = False
        cv2.destroyAllWindows()