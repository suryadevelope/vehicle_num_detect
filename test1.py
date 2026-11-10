import cv2

# Tests indices 0 through 5 to see which ones are active
for index in range(6):
    cap = cv2.VideoCapture(index)
    if cap.isOpened():
        ret, _ = cap.read()
        print(f"Camera found at index: {index} (Working: {ret})")
        cap.release()
