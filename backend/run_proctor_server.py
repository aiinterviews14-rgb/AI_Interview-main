"""
Standalone proctoring service (Part 2 of a split backend).

Run on a separate host/port when you want the heavy CV stack isolated, e.g.:
  set PROCTOR_PORT=5051 && python run_proctor_server.py

Important: This process has its own InterviewManager + ProctoringService memory.
For production multi-container setups, point the browser (or API gateway) at this
service only for /proctor/* and /api/start_monitoring|stop_monitoring, and keep
interview state in sync via your API layer (or run monolith `api.py` for single-node).

Default / recommended: run `api.py` only (proctor blueprint is already registered there).
"""
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(current_dir, ".env"))
load_dotenv(os.path.join(os.path.dirname(current_dir), ".env"))

from flask import Flask, jsonify

from app_config import apply_cors
import database
from manager import InterviewManager
from proctoring_engine.service import ProctoringService
from services.proctor_routes import proctor_bp, configure_proctor_blueprint

app = Flask(__name__)
apply_cors(app)

database.init_db(app)

manager = InterviewManager()
proctor_service = ProctoringService()


def _merge_proctor_violations_into_manager():
    for ev in proctor_service.violations:
        if ev not in manager.violations:
            manager.violations.append(ev)


configure_proctor_blueprint(manager, proctor_service, database, _merge_proctor_violations_into_manager)
app.register_blueprint(proctor_bp)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"service": "proctor", "status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PROCTOR_PORT", "5051"))
    print(f"[proctor] listening on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
