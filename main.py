from flask import Flask
#from camera_manager import start_camera_service, capture_frame
from app import create_app
import os

app = create_app()
if app is None:
    raise RuntimeError("Failed to create Flask app")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,threaded=True)
