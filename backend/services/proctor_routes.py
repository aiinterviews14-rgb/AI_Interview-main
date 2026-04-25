"""
Proctoring HTTP routes — Flask blueprint.

Register on the main `api` app (default) or on a small standalone app (`run_proctor_server.py`)
for a two-container deployment where the proctor worker carries the heavier CV stack.
"""
from __future__ import annotations

from datetime import datetime
from flask import Blueprint, jsonify, request

proctor_bp = Blueprint("proctoring", __name__)


class ProctorRouteDeps:
    manager = None
    proctor_service = None
    database = None
    merge_proctor_into_manager = None


def configure_proctor_blueprint(manager, proctor_service, database_mod, merge_fn):
    """Wire shared singletons used by legacy api.py design."""
    ProctorRouteDeps.manager = manager
    ProctorRouteDeps.proctor_service = proctor_service
    ProctorRouteDeps.database = database_mod
    ProctorRouteDeps.merge_proctor_into_manager = merge_fn


def _m():
    return ProctorRouteDeps.manager


def _p():
    return ProctorRouteDeps.proctor_service


def _db():
    return ProctorRouteDeps.database


def _merge():
    fn = ProctorRouteDeps.merge_proctor_into_manager
    if fn:
        fn()


@proctor_bp.route("/proctor/start", methods=["POST"])
@proctor_bp.route("/api/start_monitoring", methods=["POST"])
def start_proctoring():
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        if user_id:
            user_data = _db().get_user_by_id(user_id)
            plan_id = int(user_data.get("plan_id", 0)) if user_data else 0
            print(f"🎥 Proctoring start for user {user_id} (plan {plan_id})")

        _p().session_id = _m().session_id
        _p().start()
        return jsonify(
            {
                "status": "success",
                "message": f"Proctoring service started for session {_m().session_id}",
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@proctor_bp.route("/proctor/identity", methods=["POST"])
def proctor_identity():
    data = request.json or {}
    user_id = data.get("user_id")
    image_data = data.get("image")

    import base64
    import numpy as np
    import cv2

    try:
        frame = None
        if user_id:
            print(f"🔍 System: Fetching profile photo for user {user_id}...")
            profile_b64 = _db().get_user_photo(int(user_id))
            if profile_b64:
                if "," in profile_b64:
                    profile_b64 = profile_b64.split(",")[1]
                img_bytes = base64.b64decode(profile_b64)
                nparr = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                print(f"✅ Loaded profile photo for {user_id}")
            else:
                print(f"⚠️ No profile photo found for {user_id} in DB.")

        if frame is None and image_data:
            if "," in image_data:
                image_data = image_data.split(",")[1]
            img_bytes = base64.b64decode(image_data)
            nparr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            print("✅ Using provided camera frame as identity baseline.")

        if frame is not None:
            _p().set_reference_profile(frame)
            msg = "Identity verification baseline established against " + (
                "profile photo" if user_id else "current frame"
            )
            _p().record_event("identity_baseline", msg, "LOW")
            return jsonify({"status": "success", "message": msg})

    except Exception as e:
        print(f"Error setting identity baseline: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    return (
        jsonify(
            {
                "status": "error",
                "message": "Failed to set identity baseline. No valid image source found.",
            }
        ),
        400,
    )


@proctor_bp.route("/proctor/status", methods=["GET"])
def proctor_status():
    return jsonify(
        {
            "status": "active" if _p().running else "stopped",
            "should_terminate": _p().should_terminate,
            "termination_reason": getattr(_p(), "termination_reason", None),
            "violation_count": len(_p().violations),
        }
    )


@proctor_bp.route("/proctor/reset", methods=["POST"])
def proctor_reset():
    _p().initial_nose = None
    _p().prev_gray = None
    _p().consecutive_no_face = 0
    _p().consecutive_phone = 0
    _p().should_terminate = False
    _p().termination_reason = None
    _p().violations = []
    _m().reset()
    _p().session_id = _m().session_id
    if hasattr(_p(), "consecutive_yolo_people"):
        _p().consecutive_yolo_people = 0
    if hasattr(_p(), "consecutive_multi_face"):
        _p().consecutive_multi_face = 0
    if hasattr(_p(), "consecutive_looking_away"):
        _p().consecutive_looking_away = 0
    if hasattr(_p(), "consecutive_identity_mismatch"):
        _p().consecutive_identity_mismatch = 0
    return jsonify(
        {
            "status": "success",
            "message": "Proctoring and Interview state reset/re-calibrated",
        }
    )


@proctor_bp.route("/proctor/stage", methods=["POST"])
def proctor_stage():
    data = request.json or {}
    _p().current_stage = data.get("stage", "interview")
    return jsonify({"status": "success"})


@proctor_bp.route("/proctor/event", methods=["POST"])
def proctor_event():
    data = request.json or {}
    event_type = data.get("type", "general")
    message = data.get("message", "UI Event detected")
    severity = data.get("severity", "MEDIUM")

    _p().record_event(event_type, message, severity)
    _merge()
    return jsonify({"status": "success"})


@proctor_bp.route("/proctor/stop", methods=["POST"])
@proctor_bp.route("/api/stop_monitoring", methods=["POST"])
def stop_proctoring():
    try:
        _p().stop()
        _merge()
        _m().evidence_path = _p().evidence_path
        return jsonify(
            {
                "status": "success",
                "events": _p().violations,
                "score": _p().get_score(),
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@proctor_bp.route("/proctor/process_frame", methods=["POST"])
def process_frame():
    try:
        data = request.json
        image_data = data.get("image")

        if not image_data:
            return jsonify({"status": "error", "message": "No image data"}), 400

        import base64
        import numpy as np
        import cv2

        if "," in image_data:
            image_data = image_data.split(",")[1]

        img_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"status": "error", "message": "Failed to decode image"}), 400

        result = _p().process_frame(frame)

        if result:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] Proctor: FaceDetected={result.get('face_detected')} | "
                f"Warning={result.get('current_warning')} | Terminate={_p().should_terminate}"
            )

        _merge()

        return jsonify(
            {
                "status": "success",
                "face_detected": result.get("face_detected", False) if result else False,
                "warning": result.get("current_warning", None) if result else None,
                "should_terminate": _p().should_terminate,
                "termination_reason": _p().termination_reason,
            }
        )
    except Exception as e:
        print(f"Frame Process Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
