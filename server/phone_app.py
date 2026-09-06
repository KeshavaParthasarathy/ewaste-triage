"""Restricted LAN application for short-lived phone photo capture."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge

from server.imaging import ImageTooLarge, normalize_image, register_image_formats
from server.phone_sessions import PhoneSessionManager


MAX_UPLOAD_BYTES = 16 * 1024 * 1024
_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'none'",
        "base-uri 'none'",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' blob: data:",
        "media-src blob:",
        "script-src 'self'",
        "style-src 'self'",
    )
)


def create_phone_app(
    sessions: PhoneSessionManager,
    classify_image: Callable[[Image.Image], dict[str, object]],
    receive_result: Callable[[dict[str, object]], None],
) -> Flask:
    """Build the capability-scoped LAN surface used during phone capture."""
    static_dir = Path(__file__).parent / "static"
    app = Flask(__name__, static_folder=None, template_folder=str(static_dir))
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        PHONE_SESSIONS=sessions,
        PHONE_CLASSIFY_IMAGE=classify_image,
        PHONE_RECEIVE_RESULT=receive_result,
        PHONE_REQUIRE_PAIRING_CODE=False,
    )
    register_image_formats()

    @app.after_request
    def apply_browser_security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return jsonify({
            "error": "Photo is too large. Choose an image smaller than 16 MB and try again."
        }), 413

    def token_authorized(token: str | None, code: str | None = None, *, require_code=False) -> bool:
        if not isinstance(token, str) or not token:
            return False
        if require_code and app.config["PHONE_REQUIRE_PAIRING_CODE"]:
            return isinstance(code, str) and sessions.authorize(token, code)
        return sessions.authorize(token)

    def query_token(*, require_code=False) -> str:
        token = request.args.get("token")
        if not token_authorized(
            token,
            request.args.get("code"),
            require_code=require_code,
        ):
            abort(404)
        return token

    def form_token(*, require_code=False) -> str:
        token = request.form.get("token")
        if not token_authorized(
            token,
            request.form.get("code"),
            require_code=require_code,
        ):
            abort(404)
        return token

    @app.get("/phone")
    def phone_page():
        token = query_token()
        response = render_template(
            "phone.html",
            phone_token=token,
            requires_pairing_code=bool(app.config["PHONE_REQUIRE_PAIRING_CODE"]),
        )
        sessions.touch(token)
        return response

    @app.get("/static/phone.css")
    def phone_css():
        token = query_token()
        response = send_from_directory(static_dir, "phone.css", conditional=False)
        sessions.touch(token)
        return response

    @app.get("/static/phone.js")
    def phone_javascript():
        token = query_token()
        response = send_from_directory(static_dir, "phone.js", conditional=False)
        sessions.touch(token)
        return response

    @app.get("/phone/status")
    def phone_status():
        token = query_token(require_code=True)
        session = sessions.touch(token)
        if session is None:
            abort(404)
        return jsonify({
            "active": True,
            "expires_at": session.expires_at,
            "requires_pairing_code": bool(app.config["PHONE_REQUIRE_PAIRING_CODE"]),
        })

    @app.post("/phone/upload")
    def phone_upload():
        token = form_token(require_code=True)
        upload = request.files.get("image")
        if upload is None or not upload.filename:
            return jsonify({"error": "Choose a photo to analyze."}), 400

        normalized = None
        try:
            with Image.open(upload.stream) as source:
                normalized = normalize_image(source)
                normalized.load()
            prediction = dict(app.config["PHONE_CLASSIFY_IMAGE"](normalized))
            callback_result = deepcopy(prediction)
            app.config["PHONE_RECEIVE_RESULT"](callback_result)
        except ImageTooLarge as exc:
            return jsonify({"error": str(exc)}), 413
        except Image.DecompressionBombError:
            return jsonify({"error": "image exceeds 40,000,000 pixels"}), 413
        except (UnidentifiedImageError, OSError):
            return jsonify({"error": "The selected file is not a decodable image."}), 400
        finally:
            if normalized is not None:
                normalized.close()

        sessions.touch(token)
        return jsonify({"prediction": prediction})

    return app
