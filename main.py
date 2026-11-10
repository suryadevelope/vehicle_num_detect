import json
import os
import sys
import time
import threading
import queue
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import cv2
import numpy as np
import requests
try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    serial = None
    SERIAL_AVAILABLE = False
from fast_alpr import ALPR


class ChallanHistory:
    """Track challan history per license plate"""
    def __init__(self, history_file: str = "challan_history.json"):
        self.history_file = Path(history_file)
        self.history: Dict[str, List[Dict]] = {}
        self.load()
    
    def load(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, "r") as f:
                    self.history = json.load(f)
                print(f"[ChallanHistory] Loaded {sum(len(v) for v in self.history.values())} records for {len(self.history)} plates")
            except Exception as e:
                print(f"[ChallanHistory] Error loading: {e}")
                self.history = {}
        else:
            self.history = {}
    
    def save(self):
        try:
            with open(self.history_file, "w") as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            print(f"[ChallanHistory] Error saving: {e}")
    
    def add_challan(self, plate: str, path: str, speed: float, timestamp: str):
        normalized = plate.replace(" ", "").upper()
        if normalized not in self.history:
            self.history[normalized] = []
        
        record = {
            "plate": plate,
            "path": path,
            "speed": speed,
            "timestamp": timestamp,
            "limit": self.get_speed_limit()
        }
        self.history[normalized].append(record)
        self.save()
        return len(self.history[normalized])
    
    def get_total_challans(self, plate: str) -> int:
        normalized = plate.replace(" ", "").upper()
        return len(self.history.get(normalized, []))
    
    def get_recent_challans(self, plate: str, limit: int = 5) -> List[Dict]:
        normalized = plate.replace(" ", "").upper()
        return self.history.get(normalized, [])[-limit:]
    
    def get_speed_limit(self) -> float:
        # This will be overridden by the app
        return 40.0


class Config:
    def __init__(self, config_path: str = "config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)
    
    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value


class TelegramNotifier:
    def __init__(self, bot_token: str, default_chat_id: str, plate_chat_mapping: Dict[str, str]):
        self.bot_token = bot_token
        self.default_chat_id = default_chat_id
        self.plate_chat_mapping = plate_chat_mapping
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def get_chat_id_for_plate(self, plate_text: str) -> str:
        """Get chat ID for a specific plate, fallback to default"""
        # Normalize plate text for lookup (remove spaces, uppercase)
        normalized = plate_text.replace(" ", "").upper()
        for plate, chat_id in self.plate_chat_mapping.items():
            if plate.upper() in normalized or normalized in plate.upper():
                return chat_id
        return self.default_chat_id
    
    def send_message(self, text: str, chat_id: str = None) -> bool:
        url = f"{self.base_url}/sendMessage"
        target_chat_id = chat_id or self.default_chat_id
        payload = {"chat_id": target_chat_id, "text": text, "parse_mode": "HTML"}
        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"[Telegram] Error sending message: {e}")
            return False
    
    def send_photo(self, image_path: str, caption: str = "", chat_id: str = None) -> bool:
        url = f"{self.base_url}/sendPhoto"
        target_chat_id = chat_id or self.default_chat_id
        try:
            with open(image_path, "rb") as photo:
                files = {"photo": photo}
                data = {"chat_id": target_chat_id, "caption": caption, "parse_mode": "HTML"}
                response = requests.post(url, files=files, data=data, timeout=15)
            return response.status_code == 200
        except Exception as e:
            print(f"[Telegram] Error sending photo: {e}")
            return False


class SerialSimulator:
    """Simulates serial input from terminal for testing"""
    def __init__(self, path_queue: queue.Queue):
        self.path_queue = path_queue
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.output_queue: queue.Queue = queue.Queue()  # For outgoing serial data
    
    def start(self) -> bool:
        self.running = True
        self.thread = threading.Thread(target=self._input_loop, daemon=True)
        self.thread.start()
        print("[SerialSim] Started - Enter serial data in format: SPEED,<PATH>,<SPEED_VALUE>")
        print("[SerialSim] Examples: SPEED,A,12.5  |  SPEED,B,45.0  |  quit")
        print("[SerialSim] Output will be shown as: [TX] DETECT,<PATH>,<PLATE>,<SPEED>")
        return True
    
    def _input_loop(self):
        while self.running:
            try:
                # Check for outgoing data to display
                try:
                    output_data = self.output_queue.get_nowait()
                    print(f"[TX] {output_data}")
                except queue.Empty:
                    pass
                
                line = input().strip()
                if not line:
                    continue
                
                # Parse format: SPEED,<PATH>,<SPEED_VALUE>
                parts = line.split(',')
                if len(parts) >= 2 and parts[0].upper() == "SPEED":
                    path = parts[1].upper()
                    speed = float(parts[2]) if len(parts) > 2 else 0.0
                    if path in ("A", "B"):
                        print(f"[SerialSim] Parsed: Path={path}, Speed={speed} km/h")
                        self.path_queue.put({"path": path, "speed": speed, "raw": line})
                    else:
                        print(f"[SerialSim] Invalid path: {path} (use A or B)")
                elif line.upper() in ("QUIT", "EXIT", "Q"):
                    print("[SerialSim] Quit command received")
                    self.running = False
                    break
                elif line.upper() == "HELP":
                    print("[SerialSim] Format: SPEED,<A|B>,<speed>  |  quit  |  help")
                else:
                    print(f"[SerialSim] Unknown format: {line} (use SPEED,A,12.5)")
            except EOFError:
                break
            except ValueError:
                print(f"[SerialSim] Invalid speed value in: {line}")
            except Exception as e:
                print(f"[SerialSim] Error: {e}")
                time.sleep(0.1)
    
    def send_detection(self, path: str, plate: str, speed: float):
        """Send detection result back via serial (simulated)"""
        output = f"DETECT,{path},{plate},{speed:.1f}"
        self.output_queue.put(output)
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)


class SerialHandler:
    def __init__(self, port: str, baudrate: int, timeout: float, path_queue: queue.Queue):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.path_queue = path_queue
        self.serial_conn: Optional[serial.Serial] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
    
    def start(self) -> bool:
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            self.running = True
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
            print(f"[Serial] Connected to {self.port} at {self.baudrate} baud")
            return True
        except Exception as e:
            print(f"[Serial] Failed to connect: {e}")
            return False
    
    def _read_loop(self):
        buffer = ""
        while self.running and self.serial_conn and self.serial_conn.is_open:
            try:
                data = self.serial_conn.read(self.serial_conn.in_waiting or 1)
                if data:
                    buffer += data.decode("utf-8", errors="ignore")
                    print(f"[Serial] RX: {data.decode('utf-8', errors='ignore').strip()}")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        # Parse format: SPEED,<PATH>,<SPEED_VALUE>
                        parts = line.split(',')
                        if len(parts) >= 2 and parts[0].upper() == "SPEED":
                            path = parts[1].upper()
                            speed = float(parts[2]) if len(parts) > 2 else 0.0
                            if path in ("A", "B"):
                                print(f"[Serial] Parsed: Path={path}, Speed={speed} km/h")
                                self.path_queue.put({"path": path, "speed": speed, "raw": line})
                            else:
                                print(f"[Serial] Invalid path: {path}")
                        elif line in ("A", "B", "a", "b"):
                            # Backward compatibility: just path letter
                            path = line.upper()
                            print(f"[Serial] Received path (legacy): {path}")
                            self.path_queue.put({"path": path, "speed": 0.0, "raw": line})
            except Exception as e:
                print(f"[Serial] Read error: {e}")
                time.sleep(0.1)
    
    def stop(self):
        self.running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        if self.thread:
            self.thread.join(timeout=2)
    
    def send_detection(self, path: str, plate: str, speed: float):
        """Send detection result back via serial"""
        if self.serial_conn and self.serial_conn.is_open:
            try:
                output = f"DETECT,{path},{plate},{speed:.1f}\n"
                self.serial_conn.write(output.encode('utf-8'))
                self.serial_conn.flush()
                print(f"[Serial] TX: {output.strip()}")
            except Exception as e:
                print(f"[Serial] Send error: {e}")


class CameraManager:
    def __init__(self, camera_a_index: int, camera_b_index: int, width: int, height: int, fps: int):
        self.camera_a_index = camera_a_index
        self.camera_b_index = camera_b_index
        self.width = width
        self.height = height
        self.fps = fps
        self.cap_a: Optional[cv2.VideoCapture] = None
        self.cap_b: Optional[cv2.VideoCapture] = None
        self.latest_frame_a: Optional[np.ndarray] = None
        self.latest_frame_b: Optional[np.ndarray] = None
        self.frame_lock_a = threading.Lock()
        self.frame_lock_b = threading.Lock()
        self.running = False
        self.thread_a: Optional[threading.Thread] = None
        self.thread_b: Optional[threading.Thread] = None
    
    def start(self) -> bool:
        self.cap_a = cv2.VideoCapture(self.camera_a_index, cv2.CAP_DSHOW)
        self.cap_b = cv2.VideoCapture(self.camera_b_index, cv2.CAP_DSHOW)
        
        for cap, name in [(self.cap_a, "A"), (self.cap_b, "B")]:
            if not cap.isOpened():
                print(f"[Camera] Failed to open camera {name} (index {self.camera_a_index if name == 'A' else self.camera_b_index})")
                return False
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        self.running = True
        self.thread_a = threading.Thread(target=self._capture_loop, args=("A", self.cap_a, self.frame_lock_a), daemon=True)
        self.thread_b = threading.Thread(target=self._capture_loop, args=("B", self.cap_b, self.frame_lock_b), daemon=True)
        self.thread_a.start()
        self.thread_b.start()
        print("[Camera] Both cameras started")
        return True
    
    def _capture_loop(self, name: str, cap: cv2.VideoCapture, lock: threading.Lock):
        while self.running and cap.isOpened():
            ret, frame = cap.read()
            if ret:
                with lock:
                    if name == "A":
                        self.latest_frame_a = frame.copy()
                    else:
                        self.latest_frame_b = frame.copy()
            else:
                time.sleep(0.01)
    
    def get_latest_frame(self, camera: str) -> Optional[np.ndarray]:
        if camera == "A":
            with self.frame_lock_a:
                return self.latest_frame_a.copy() if self.latest_frame_a is not None else None
        else:
            with self.frame_lock_b:
                return self.latest_frame_b.copy() if self.latest_frame_b is not None else None
    
    def get_both_frames(self) -> tuple:
        return self.get_latest_frame("A"), self.get_latest_frame("B")
    
    def stop(self):
        self.running = False
        for cap in [self.cap_a, self.cap_b]:
            if cap:
                cap.release()
        for t in [self.thread_a, self.thread_b]:
            if t:
                t.join(timeout=2)
        print("[Camera] Stopped")


class ALPRProcessor:
    def __init__(self, detector_model: str, ocr_model: str, conf_threshold: float):
        print("[ALPR] Initializing models...")
        self.alpr = ALPR(
            detector_model=detector_model,
            ocr_model=ocr_model,
        )
        self.conf_threshold = conf_threshold
        print("[ALPR] Models loaded")
    
    def process_frame(self, frame: np.ndarray) -> list:
        results = self.alpr.predict(frame)
        filtered = []
        for r in results:
            if r.ocr and r.ocr.text and r.detection.confidence >= self.conf_threshold:
                filtered.append({
                    "text": r.ocr.text,
                    "confidence": r.detection.confidence,
                    "ocr_confidence": r.ocr.confidence,
                    "bbox": (r.detection.bounding_box.x1, r.detection.bounding_box.y1,
                            r.detection.bounding_box.x2, r.detection.bounding_box.y2)
                })
        return filtered
    
    def draw_results(self, frame: np.ndarray) -> np.ndarray:
        drawn = self.alpr.draw_predictions(frame)
        return drawn.image


class DualCameraALPRApp:
    def __init__(self, config_path: str = "config.json", simulate_serial: bool = False):
        self.config = Config(config_path)
        self.path_queue = queue.Queue()
        self.running = False
        self.simulate_serial = simulate_serial
        
        # Speed limit settings
        self.speed_limit_enabled = self.config.get("speed_limit.enabled", True)
        self.speed_limit_kmh = self.config.get("speed_limit.limit_kmh", 40)
        self.challan_history = ChallanHistory(self.config.get("speed_limit.challan_history_file", "challan_history.json"))
        self.challan_history.get_speed_limit = lambda: self.speed_limit_kmh
        
        # Initialize serial handler (real or simulated)
        if simulate_serial or not SERIAL_AVAILABLE:
            self.serial_handler = SerialSimulator(path_queue=self.path_queue)
            print("[App] Using serial simulator (terminal input)")
        else:
            self.serial_handler = SerialHandler(
                port=self.config.get("serial.port", "COM3"),
                baudrate=self.config.get("serial.baudrate", 9600),
                timeout=self.config.get("serial.timeout", 1),
                path_queue=self.path_queue
            )
        
        self.camera_manager = CameraManager(
            camera_a_index=self.config.get("cameras.camera_a_index", 0),
            camera_b_index=self.config.get("cameras.camera_b_index", 1),
            width=self.config.get("cameras.width", 1280),
            height=self.config.get("cameras.height", 720),
            fps=self.config.get("cameras.fps", 30)
        )
        
        self.alpr_processor = ALPRProcessor(
            detector_model=self.config.get("alpr.detector_model", "yolo-v9-t-384-license-plate-end2end"),
            ocr_model=self.config.get("alpr.ocr_model", "cct-xs-v2-global-model"),
            conf_threshold=self.config.get("alpr.conf_threshold", 0.4)
        )
        
        self.telegram = TelegramNotifier(
            bot_token=self.config.get("telegram.bot_token", ""),
            default_chat_id=self.config.get("telegram.default_chat_id", ""),
            plate_chat_mapping=self.config.get("telegram.plate_chat_mapping", {})
        )
        
        self.save_images = self.config.get("paths.save_images", True)
        self.image_save_dir = Path(self.config.get("paths.image_save_dir", "captured_images"))
        if self.save_images:
            self.image_save_dir.mkdir(exist_ok=True)
        
        print(f"[App] Speed limit: {self.speed_limit_kmh} km/h (enabled: {self.speed_limit_enabled})")
    
    def start(self) -> bool:
        print("[App] Starting Dual Camera ALPR System...")
        
        if not self.serial_handler.start():
            print("[App] Warning: Serial not connected, continuing without it")
        
        if not self.camera_manager.start():
            print("[App] Error: Failed to start cameras")
            return False
        
        self.running = True
        self.main_loop()
        return True
    
    def main_loop(self):
        print("[App] Starting main loop. Press 'q' to quit.")
        cv2.namedWindow("Camera A - Path A", cv2.WINDOW_NORMAL)
        cv2.namedWindow("Camera B - Path B", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Camera A - Path A", 640, 360)
        cv2.resizeWindow("Camera B - Path B", 640, 360)
        
        last_capture_time = {"A": 0, "B": 0}
        capture_cooldown = 2.0
        
        while self.running:
            frame_a, frame_b = self.camera_manager.get_both_frames()
            
            if frame_a is not None:
                display_a = self.alpr_processor.draw_results(frame_a)
                cv2.putText(display_a, "CAMERA A (Path A)", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.imshow("Camera A - Path A", display_a)
            
            if frame_b is not None:
                display_b = self.alpr_processor.draw_results(frame_b)
                cv2.putText(display_b, "CAMERA B (Path B)", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.imshow("Camera B - Path B", display_b)
            
            # Check serial queue for path triggers
            try:
                trigger_data = self.path_queue.get_nowait()
                current_time = time.time()
                
                # Handle both old string format and new dict format
                if isinstance(trigger_data, dict):
                    path = trigger_data.get("path")
                    speed = trigger_data.get("speed", 0.0)
                else:
                    # Legacy string format
                    path = trigger_data
                    speed = 0.0
                
                if path in ("A", "B"):
                    # Check speed limit before processing
                    if self.speed_limit_enabled and speed > 0 and speed <= self.speed_limit_kmh:
                        print(f"[App] Path {path} speed {speed:.1f} km/h <= limit {self.speed_limit_kmh} km/h - no violation")
                        continue
                    
                    if current_time - last_capture_time[path] >= capture_cooldown:
                        last_capture_time[path] = current_time
                        self.handle_path_trigger(path, speed)
            except queue.Empty:
                pass
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('a'):
                self.handle_path_trigger("A")
            elif key == ord('b'):
                self.handle_path_trigger("B")
        
        self.stop()
    
    def handle_path_trigger(self, path: str, speed: float = 0.0):
        speed_str = f"{speed:.1f} km/h" if speed > 0 else "N/A"
        
        # Check speed limit violation
        if self.speed_limit_enabled and speed > 0 and speed <= self.speed_limit_kmh:
            print(f"[App] Path {path} speed {speed_str} within limit ({self.speed_limit_kmh} km/h) - no challan")
            return
        
        violation_type = "SPEEDING" if speed > self.speed_limit_kmh else "TRIGGER"
        print(f"[App] Path {path} triggered ({violation_type}: {speed_str}) - capturing and processing...")
        frame = self.camera_manager.get_latest_frame(path)
        
        if frame is None:
            print(f"[App] No frame available for camera {path}")
            return
        
        # Process with ALPR
        results = self.alpr_processor.process_frame(frame)
        
        # Save image
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        iso_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        image_filename = f"path_{path}_{timestamp}.jpg"
        image_path = self.image_save_dir / image_filename
        
        if self.save_images:
            annotated = self.alpr_processor.draw_results(frame)
            cv2.imwrite(str(image_path), annotated)
            print(f"[App] Saved image: {image_path}")
        
        # Send Telegram notifications per detected plate
        if self.config.get("telegram.bot_token") != "YOUR_BOT_TOKEN_HERE":
            if results:
                for r in results:
                    plate_text = r['text']
                    chat_id = self.telegram.get_chat_id_for_plate(plate_text)
                    
                    # Add to challan history and get total count
                    total_challans = self.challan_history.add_challan(plate_text, path, speed, iso_timestamp)
                    
                    # Send detection result back via serial
                    self.serial_handler.send_detection(path, plate_text, speed)
                    
                    # Individual message for each plate to specific chat ID
                    message = f"🚗 <b>Challan Notice - Path {path}</b>\n"
                    message += f"🕐 Time: {iso_timestamp}\n"
                    message += f"🚙 Vehicle: <b>{plate_text}</b>\n"
                    message += f"📍 Location: Path {path}\n"
                    message += f"🚀 Speed: <b>{speed_str}</b> (Limit: {self.speed_limit_kmh} km/h)\n"
                    message += f"⚠️ Violation: {violation_type}\n"
                    message += f"📊 Total Challans: <b>{total_challans}</b>"
                    
                    self.telegram.send_message(message, chat_id=chat_id)
                    
                    if self.save_images:
                        caption = f"Path {path} - {plate_text} - {speed_str} - Total: {total_challans} - {iso_timestamp}"
                        self.telegram.send_photo(str(image_path), caption=caption, chat_id=chat_id)
                    
                    print(f"[Telegram] Sent challan for {plate_text} (Speed: {speed_str}, Total: {total_challans}) to chat_id: {chat_id}")
            else:
                # No plates detected - send to default chat
                message = f"🚗 <b>Path {path} - Triggered</b>\n"
                message += f"🕐 Time: {iso_timestamp}\n"
                message += f"🚀 Speed: {speed_str}\n"
                message += f"📍 No license plates detected"
                self.telegram.send_message(message)
        else:
            print(f"[Telegram] Not configured, skipping notification")
            if results:
                for r in results:
                    total = self.challan_history.get_total_challans(r['text']) + 1
                    print(f"[App] Would send challan for {r['text']} (Speed: {speed_str}, Total: {total})")
                    # Send detection result back via serial (simulated)
                    self.serial_handler.send_detection(path, r['text'], speed)
            else:
                print(f"[App] No license plates detected")
    
    def stop(self):
        print("[App] Stopping...")
        self.running = False
        self.serial_handler.stop()
        self.camera_manager.stop()
        cv2.destroyAllWindows()
        print("[App] Stopped")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Dual Camera ALPR System")
    parser.add_argument("--simulate", action="store_true", help="Simulate serial input from terminal")
    parser.add_argument("--config", default="config.json", help="Config file path")
    args = parser.parse_args()
    
    config_path = args.config
    if not os.path.exists(config_path):
        print(f"Error: Config file not found at {config_path}")
        print("Please create config.json with your settings")
        sys.exit(1)
    
    app = DualCameraALPRApp(config_path, simulate_serial=args.simulate)
    try:
        app.start()
    except KeyboardInterrupt:
        print("\n[App] Interrupted by user")
    except Exception as e:
        print(f"[App] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        app.stop()


if __name__ == "__main__":
    main()