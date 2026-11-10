# Dual Camera ALPR System

Automatic License Plate Recognition system with dual camera support, serial communication, and Telegram notifications.

## Features

- **Dual Camera Support**: Live preview of two cameras simultaneously
- **License Plate Detection**: Uses Fast ALPR (YOLO + OCR) for accurate detection
- **Serial Communication**: Triggers capture on receiving 'A' or 'B' via USB serial
- **Telegram Notifications**: Sends detected plates with images to Telegram
- **Manual Triggers**: Press 'a' or 'b' keys for manual capture
- **Image Saving**: Automatically saves annotated images

## Quick Start

### 1. Run Setup

```powershell
.\setup.ps1
```

This will:
- Create virtual environment `.venv`
- Install all dependencies (Fast ALPR, OpenCV, PySerial, etc.)
- Detect available cameras and serial ports
- Create `run_alpr.ps1` launcher script

### 2. Configure

Edit `config.json` with your settings:

```json
{
  "telegram": {
    "bot_token": "YOUR_BOT_TOKEN_FROM_BOTFATHER",
    "chat_id": "YOUR_CHAT_ID"
  },
  "cameras": {
    "camera_a_index": 0,
    "camera_b_index": 1,
    "width": 1280,
    "height": 720,
    "fps": 30
  },
  "serial": {
    "port": "COM3",
    "baudrate": 9600,
    "timeout": 1
  },
  "alpr": {
    "detector_model": "yolo-v9-t-384-license-plate-end2end",
    "ocr_model": "cct-xs-v2-global-model",
    "conf_threshold": 0.4
  },
  "paths": {
    "save_images": true,
    "image_save_dir": "captured_images"
  }
}
```

### 3. Get Telegram Bot Token & Chat ID

1. Message @BotFather on Telegram
2. Create new bot: `/newbot`
3. Copy the token to `bot_token`
4. Message your bot, then visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. Find your `chat_id` in the response

### 4. Run

```powershell
.\run_alpr.ps1
```

Or directly:
```powershell
.venv\Scripts\python.exe main.py
```

## Hardware Setup

### Cameras
- Connect two USB cameras
- Check indices in Device Manager or run setup to auto-detect
- Default: Camera 0 = Path A, Camera 1 = Path B

### Serial Device
- Connect Arduino/ESP32/USB-Serial device
- Send 'A' or 'B' (with newline) to trigger capture
- Default: COM3, 9600 baud

Example Arduino code:
```cpp
void setup() {
  Serial.begin(9600);
}

void loop() {
  if (sensorTriggeredPathA()) {
    Serial.println("A");
    delay(1000);
  }
  if (sensorTriggeredPathB()) {
    Serial.println("B");
    delay(1000);
  }
}
```

## Controls

| Key | Action |
|-----|--------|
| `q` | Quit application |
| `a` | Manual trigger Path A |
| `b` | Manual trigger Path B |

## Output

- **Live Preview**: Two windows showing Camera A and Camera B with detection overlays
- **Telegram**: Receives message with plate text, confidence, and annotated image
- **Local Storage**: Images saved to `captured_images/` folder

## Configuration Options

### Cameras
- `camera_a_index` / `camera_b_index`: Camera device indices (0, 1, 2...)
- `width` / `height`: Resolution (default 1280x720)
- `fps`: Target FPS (default 30)

### Serial
- `port`: COM port (e.g., "COM3", "/dev/ttyUSB0")
- `baudrate`: Baud rate (default 9600)
- `timeout`: Read timeout in seconds

### ALPR
- `detector_model`: Plate detection model
- `ocr_model`: OCR model
- `conf_threshold`: Minimum detection confidence (0.0-1.0)

### Paths
- `save_images`: Save captured images locally
- `image_save_dir`: Directory for saved images

## Troubleshooting

### Camera not detected
- Run setup script to see available cameras
- Check camera indices in config.json
- Ensure cameras aren't used by other applications

### Serial connection failed
- Check COM port in Device Manager
- Verify baud rate matches your device
- Ensure no other program is using the port

### Telegram not working
- Verify bot token and chat ID
- Check internet connection
- Ensure bot is started (send /start to bot)

### Low detection accuracy
- Adjust `conf_threshold` lower (e.g., 0.3)
- Ensure good lighting
- Camera should capture plates clearly

## Project Structure

```
fast-alpr/
├── main.py              # Main application
├── config.json          # Configuration
├── requirements.txt     # Python dependencies
├── setup.ps1           # PowerShell setup script
├── run_alpr.ps1        # Launcher script
├── captured_images/    # Saved images (auto-created)
└── .venv/              # Virtual environment (auto-created)
```

## Requirements

- Windows 10/11
- Python 3.10+
- Two USB cameras
- Serial device (Arduino, ESP32, etc.)
- Telegram account

## License

MIT License - See LICENSE file