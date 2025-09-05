import os
import subprocess
from datetime import datetime
from flask import Flask, redirect, request, jsonify
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your-random-secret")

# --- Env dari Vercel ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# --- Global credentials (simulasi session di serverless) ---
CREDS: Credentials = None


def get_flow():
    """Buat objek Flow OAuth"""
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uris": [GOOGLE_REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )


def get_gdrive_service():
    """Bangun service Google Drive"""
    global CREDS
    if not CREDS:
        return None
    if not CREDS.valid:
        if CREDS.expired and CREDS.refresh_token:
            CREDS.refresh(Request())
    return build("drive", "v3", credentials=CREDS)


# --- ROUTES ---
@app.route("/")
def home():
    return "🚀 API berjalan! Buka /api/login untuk login Google."


@app.route("/api/login")
def login():
    flow = get_flow()
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    auth_url, _ = flow.authorization_url(prompt="consent")
    return redirect(auth_url)


@app.route("/api/oauth2callback")
def oauth2callback():
    global CREDS
    flow = get_flow()
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    flow.fetch_token(authorization_response=request.url)

    CREDS = flow.credentials  # simpan global

    return "✅ Login berhasil! Sekarang kamu bisa POST ke /api/clip untuk rekam & upload."


@app.route("/api/clip", methods=["POST"])
def record_and_upload():
    global CREDS
    if not CREDS:
        return jsonify({"error": "Belum login ke Google Drive"}), 401

    url = request.json.get("url")
    duration = request.json.get("duration", 30)
    folder_id = request.json.get("folder_id")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_filename = f"clip_{timestamp}.mp4"

    # --- Rekam dengan yt-dlp + ffmpeg ---
    command = f'yt-dlp -o - "{url}" | ffmpeg -i - -t {duration} -c copy "{output_filename}"'
    try:
        subprocess.run(command, shell=True, check=True)
    except Exception as e:
        return jsonify({"error": f"Gagal merekam: {e}"}), 500

    # --- Upload ke Google Drive ---
    try:
        service = get_gdrive_service()
        if not service:
            return jsonify({"error": "Token Google tidak valid"}), 401

        file_metadata = {"name": output_filename, "parents": [folder_id]}
        media = MediaFileUpload(output_filename, mimetype="video/mp4", resumable=True)

        uploaded = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, webViewLink")
            .execute()
        )
        os.remove(output_filename)  # hapus file lokal setelah upload

        return jsonify(
            {
                "message": "Berhasil direkam & diupload",
                "file_id": uploaded.get("id"),
                "link": uploaded.get("webViewLink"),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
