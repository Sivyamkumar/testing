"""Frontend for the video -> mp3 converter.

Two pages:
  /login    - sign in (credentials are checked by the gateway/auth services)
  /convert  - upload an mp4; once converted the mp3 downloads automatically

The browser only talks to this service. It forwards requests to the gateway
and keeps the JWT in the (signed) session cookie, so no CORS and no token in JS.
"""
import os
from functools import wraps

import requests
from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, session, stream_with_context, url_for)

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:8080").rstrip("/")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))

app = Flask(__name__)
app.secret_key = os.environ.get("FRONTEND_SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def _auth_header():
    return {"Authorization": f"Bearer {session['token']}"}


def page_login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if "token" not in session:
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapper


def api_login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if "token" not in session:
            return jsonify(error="Session expired. Please sign in again."), 401
        return view(*a, **kw)
    return wrapper


def _gateway(method, path, **kw):
    try:
        return requests.request(method, GATEWAY_URL + path, timeout=kw.pop("timeout", 60), **kw)
    except requests.RequestException:
        return None


# ---------------------------------------------------------------- pages
@app.route("/")
def index():
    return redirect(url_for("convert" if "token" in session else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "token" in session:
            return redirect(url_for("convert"))
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    if not email or not password:
        return render_template("login.html", error="Enter your email and password.", email=email), 400

    resp = _gateway("POST", "/login", auth=(email, password))
    if resp is None:
        return render_template("login.html", error="Can't reach the server. Try again shortly.", email=email), 502
    if resp.status_code != 200:
        return render_template("login.html", error="Invalid email or password.", email=email), 401

    session.clear()
    session["token"] = resp.text.strip()
    session["email"] = email
    return redirect(url_for("convert"))


@app.route("/convert")
@page_login_required
def convert():
    return render_template("convert.html", email=session.get("email"), max_mb=MAX_UPLOAD_MB)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------ API
@app.route("/api/upload", methods=["POST"])
@api_login_required
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="Choose an MP4 file first."), 400
    if not f.filename.lower().endswith(".mp4"):
        return jsonify(error="Only .mp4 videos are supported."), 400

    resp = _gateway("POST", "/upload", headers=_auth_header(), timeout=300,
                    files={"file": (f.filename, f.stream, "video/mp4")})
    if resp is None:
        return jsonify(error="Can't reach the conversion service."), 502
    if resp.status_code == 401:
        session.clear()
        return jsonify(error="Session expired. Please sign in again."), 401
    if resp.status_code != 200:
        return jsonify(error=resp.text or "Upload failed."), resp.status_code
    return jsonify(video_fid=resp.json()["video_fid"])


@app.route("/api/status/<video_fid>")
@api_login_required
def api_status(video_fid):
    resp = _gateway("GET", "/status", headers=_auth_header(), params={"video_fid": video_fid})
    if resp is None:
        return jsonify(error="Can't reach the conversion service."), 502
    if resp.status_code == 401:
        session.clear()
        return jsonify(error="Session expired. Please sign in again."), 401
    if resp.status_code != 200:
        return jsonify(error=resp.text), resp.status_code
    return jsonify(resp.json())


@app.route("/api/download/<mp3_fid>")
@api_login_required
def api_download(mp3_fid):
    name = os.path.splitext(os.path.basename(request.args.get("name", "audio")))[0] or "audio"
    try:
        upstream = requests.get(f"{GATEWAY_URL}/download", headers=_auth_header(),
                                params={"fid": mp3_fid}, stream=True, timeout=60)
    except requests.RequestException:
        return jsonify(error="Can't reach the conversion service."), 502
    if upstream.status_code != 200:
        return jsonify(error="Download failed."), upstream.status_code
    return Response(stream_with_context(upstream.iter_content(64 * 1024)),
                    mimetype="audio/mpeg",
                    headers={"Content-Disposition": f'attachment; filename="{name}.mp3"'})


@app.errorhandler(413)
def too_large(_):
    return jsonify(error=f"File is too large (max {MAX_UPLOAD_MB} MB)."), 413


@app.route("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=bool(os.environ.get("FLASK_DEBUG")))
