import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from io import BytesIO
from typing import Optional
from urllib.parse import quote, urlparse

from azure.core.exceptions import AzureError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)
from auth_utils import (
    authenticate_user,
    create_user,
    get_user_by_id,
    init_user_store,
)
from env_utils import load_local_env
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for


load_local_env()
init_user_store()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

UPLOAD_PROGRESS: dict[str, dict] = {}
UPLOAD_PROGRESS_LOCK = threading.Lock()
UPLOAD_PROGRESS_TTL_SECONDS = 30 * 60


def is_safe_redirect_target(target: str) -> bool:
    return target.startswith("/") and not target.startswith("//")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user_id = session.get("user_id")
        if user_id and get_user_by_id(user_id):
            return view(*args, **kwargs)

        if request.path.startswith(("/upload", "/progress", "/files")):
            return jsonify({"ok": False, "error": "Please log in again."}), 401

        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    return wrapped_view


def build_blob_service_client() -> BlobServiceClient:
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY", "").strip()

    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string)

    if account_url and account_key:
        return BlobServiceClient(account_url=account_url, credential=account_key)

    raise RuntimeError(
        "Set AZURE_STORAGE_CONNECTION_STRING or both "
        "AZURE_STORAGE_ACCOUNT_URL and AZURE_STORAGE_ACCOUNT_KEY."
    )


def cleanup_stale_upload_progress() -> None:
    cutoff = time.time() - UPLOAD_PROGRESS_TTL_SECONDS
    with UPLOAD_PROGRESS_LOCK:
        stale_uploads = [
            upload_id
            for upload_id, progress in UPLOAD_PROGRESS.items()
            if progress.get("updated_at", 0) < cutoff
        ]
        for upload_id in stale_uploads:
            UPLOAD_PROGRESS.pop(upload_id, None)


def set_upload_progress(
    upload_id: str,
    *,
    percent: int,
    message: str,
    phase: str,
    transferred: Optional[int] = None,
    total: Optional[int] = None,
    done: bool = False,
    error: bool = False,
) -> None:
    if not upload_id:
        return

    now = time.time()
    with UPLOAD_PROGRESS_LOCK:
        existing = UPLOAD_PROGRESS.get(upload_id, {})
        UPLOAD_PROGRESS[upload_id] = {
            "created_at": existing.get("created_at", now),
            "updated_at": now,
            "percent": max(0, min(100, int(percent))),
            "message": message,
            "phase": phase,
            "transferred": transferred,
            "total": total,
            "done": done,
            "error": error,
        }


def get_upload_progress(upload_id: str) -> dict:
    with UPLOAD_PROGRESS_LOCK:
        return dict(UPLOAD_PROGRESS.get(upload_id, {}))


def ensure_upload_progress(upload_id: str) -> None:
    if not upload_id:
        return

    with UPLOAD_PROGRESS_LOCK:
        if upload_id not in UPLOAD_PROGRESS:
            now = time.time()
            UPLOAD_PROGRESS[upload_id] = {
                "created_at": now,
                "updated_at": now,
                "percent": 0,
                "message": "Waiting for upload to start...",
                "phase": "queued",
                "transferred": None,
                "total": None,
                "done": False,
                "error": False,
            }


def resolve_account_name_and_key() -> tuple[str, str]:
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY", "").strip()

    if connection_string:
        parts = {}
        for item in connection_string.split(";"):
            if "=" in item:
                key, value = item.split("=", 1)
                parts[key.strip()] = value.strip()
        account_name = parts.get("AccountName", "")
        connection_account_key = parts.get("AccountKey", "")
        if account_name and connection_account_key:
            return account_name, connection_account_key

    if account_url and account_key:
        parsed = urlparse(account_url)
        account_name = parsed.netloc.split(".")[0]
        if account_name:
            return account_name, account_key

    raise RuntimeError(
        "Unable to generate a secure blob link. Make sure the storage account key is available."
    )


def generate_sas_blob_url(container_name: str, blob_name: str, expiry_hours: int = 1) -> str:
    account_name, account_key = resolve_account_name_and_key()
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
    )

    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()
    if account_url:
        base_url = account_url.rstrip("/")
    else:
        base_url = f"https://{account_name}.blob.core.windows.net"

    return f"{base_url}/{container_name}/{blob_name}?{sas_token}"


def format_blob_download_name(blob_name: str) -> str:
    file_name = os.path.basename(blob_name.rstrip("/")) or "download"
    fallback = file_name.replace("\\", "_").replace("/", "_").replace('"', "")
    encoded_name = quote(file_name)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded_name}"


def serialize_blob(blob) -> dict:
    return {
        "name": blob.name,
        "size": blob.size or 0,
        "content_type": blob.content_settings.content_type
        if blob.content_settings
        else "application/octet-stream",
        "last_modified": blob.last_modified.isoformat() if blob.last_modified else None,
    }


def list_container_blobs(container_name: str) -> list[dict]:
    blob_service_client = build_blob_service_client()
    container_client = blob_service_client.get_container_client(container_name)

    if not container_client.exists():
        return []

    blobs = [serialize_blob(blob) for blob in container_client.list_blobs()]
    return sorted(blobs, key=lambda blob: blob["name"].lower())


def upload_file_to_blob(
    file_storage,
    container_name: str,
    blob_name: str,
    overwrite: bool,
    progress_callback=None,
) -> str:
    def report(
        percent: int,
        message: str,
        phase: str,
        transferred: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        if progress_callback:
            progress_callback(
                percent=percent,
                message=message,
                phase=phase,
                transferred=transferred,
                total=total,
            )

    report(42, "Connecting to Azure Blob Storage...", "azure-connect")
    blob_service_client = build_blob_service_client()
    report(50, "Checking the target container...", "container")
    container_client = blob_service_client.get_container_client(container_name)

    if not container_client.exists():
        report(54, "Creating the target container...", "container")
        container_client.create_container()

    blob_client = container_client.get_blob_client(blob_name)
    file_bytes = file_storage.read()
    total_bytes = len(file_bytes)
    content_type = file_storage.mimetype or "application/octet-stream"

    def track_azure_transfer(transferred: int, total: Optional[int]) -> None:
        known_total = total or total_bytes
        percent = 58 + int((transferred / known_total) * 34) if known_total else 92
        report(
            percent,
            "Uploading to Azure Blob Storage...",
            "azure-transfer",
            transferred,
            known_total,
        )

    report(58, "Uploading to Azure Blob Storage...", "azure-transfer", 0, total_bytes)

    blob_client.upload_blob(
        BytesIO(file_bytes),
        length=total_bytes,
        overwrite=overwrite,
        content_settings=ContentSettings(content_type=content_type),
        progress_hook=track_azure_transfer,
    )
    report(94, "Creating the secure blob link...", "link", total_bytes, total_bytes)
    return generate_sas_blob_url(container_name, blob_name)


@app.get("/login")
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    next_url = request.args.get("next", url_for("index"))
    if not is_safe_redirect_target(next_url):
        next_url = url_for("index")

    return render_template(
        "login.html",
        mode="login",
        error=None,
        next_url=next_url,
    )


@app.post("/login")
def login_submit():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    next_url = request.form.get("next", url_for("index"))

    if not is_safe_redirect_target(next_url):
        next_url = url_for("index")

    user = authenticate_user(email, password)
    if user:
        session.clear()
        session["user_id"] = user["id"]
        session["email"] = user["email"]
        return redirect(next_url)

    return render_template(
        "login.html",
        mode="login",
        error="The Gmail address or password is incorrect.",
        next_url=next_url,
    ), 401


@app.get("/signup")
def signup():
    if session.get("user_id"):
        return redirect(url_for("index"))

    return render_template(
        "login.html",
        mode="signup",
        error=None,
        next_url=url_for("index"),
    )


@app.post("/signup")
def signup_submit():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if password != confirm_password:
        return render_template(
            "login.html",
            mode="signup",
            error="Passwords do not match.",
            next_url=url_for("index"),
        ), 400

    created, message, user = create_user(email, password)
    if not created or not user:
        return render_template(
            "login.html",
            mode="signup",
            error=message,
            next_url=url_for("index"),
        ), 400

    session.clear()
    session["user_id"] = user["id"]
    session["email"] = user["email"]
    return redirect(url_for("index"))


@app.get("/signin")
def signin_alias():
    return redirect(url_for("login", **request.args))


@app.post("/signin")
def signin_submit_alias():
    return login_submit()


@app.get("/register")
def register_alias():
    return redirect(url_for("signup"))


@app.post("/register")
def register_submit_alias():
    return signup_submit()


@app.get("/auth")
def auth_entry():
    mode = request.args.get("mode", "login")
    if mode == "signup":
        return redirect(url_for("signup"))
    return redirect(url_for("login"))


@app.get("/sign-in")
def sign_in_alias():
    return redirect(url_for("login", **request.args))


@app.post("/sign-in")
def sign_in_submit_alias():
    return login_submit()


@app.get("/sign-up")
def sign_up_alias():
    return redirect(url_for("signup"))


@app.post("/sign-up")
def sign_up_submit_alias():
    return signup_submit()


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index():
    cleanup_stale_upload_progress()
    user = get_user_by_id(session.get("user_id"))
    return render_template(
        "index.html",
        default_container=os.getenv("AZURE_STORAGE_CONTAINER", "").strip(),
        auth_mode=resolve_auth_mode(),
        username=user["email"] if user else "User",
    )


@app.get("/progress/<upload_id>")
@login_required
def upload_progress(upload_id: str):
    cleanup_stale_upload_progress()
    ensure_upload_progress(upload_id)
    response = jsonify(get_upload_progress(upload_id))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/files")
@login_required
def files():
    container_name = request.args.get("container_name", "").strip()
    if not container_name:
        return jsonify({"ok": False, "error": "Container name is required."}), 400

    try:
        return jsonify({"ok": True, "files": list_container_blobs(container_name)})
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except AzureError as exc:
        return jsonify({"ok": False, "error": f"Could not load files: {exc}"}), 500


@app.get("/download")
@login_required
def download():
    container_name = request.args.get("container_name", "").strip()
    blob_name = request.args.get("blob_name", "").strip()

    if not container_name or not blob_name:
        return jsonify({"ok": False, "error": "Container name and blob name are required."}), 400

    try:
        blob_service_client = build_blob_service_client()
        blob_client = blob_service_client.get_blob_client(
            container=container_name,
            blob=blob_name,
        )
        properties = blob_client.get_blob_properties()
        stream = blob_client.download_blob()
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except AzureError as exc:
        return jsonify({"ok": False, "error": f"Download failed: {exc}"}), 500

    headers = {
        "Content-Disposition": format_blob_download_name(blob_name),
        "Content-Length": str(properties.size),
        "Cache-Control": "no-store",
    }
    content_type = (
        properties.content_settings.content_type
        if properties.content_settings
        else "application/octet-stream"
    ) or "application/octet-stream"

    return Response(stream.chunks(), headers=headers, mimetype=content_type)


@app.post("/upload")
@login_required
def upload():
    upload_id = request.form.get("upload_id", "").strip()
    if upload_id:
        ensure_upload_progress(upload_id)
        set_upload_progress(
            upload_id,
            percent=38,
            message="File received by the app. Preparing Azure transfer...",
            phase="received",
        )

    uploaded_file = request.files.get("file")
    container_name = request.form.get("container_name", "").strip()
    blob_name = request.form.get("blob_name", "").strip()
    overwrite = request.form.get("overwrite", "false").lower() == "true"

    if not container_name:
        set_upload_progress(
            upload_id,
            percent=0,
            message="Container name is required.",
            phase="error",
            error=True,
        )
        return jsonify({"ok": False, "error": "Container name is required."}), 400

    if uploaded_file is None or not uploaded_file.filename:
        set_upload_progress(
            upload_id,
            percent=0,
            message="Please choose a file to upload.",
            phase="error",
            error=True,
        )
        return jsonify({"ok": False, "error": "Please choose a file to upload."}), 400

    target_blob_name = blob_name or uploaded_file.filename

    try:
        blob_url = upload_file_to_blob(
            file_storage=uploaded_file,
            container_name=container_name,
            blob_name=target_blob_name,
            overwrite=overwrite,
            progress_callback=lambda **progress: set_upload_progress(upload_id, **progress),
        )
    except RuntimeError as exc:
        set_upload_progress(
            upload_id,
            percent=get_upload_progress(upload_id).get("percent", 0),
            message=str(exc),
            phase="error",
            error=True,
        )
        return jsonify({"ok": False, "error": str(exc)}), 400
    except AzureError as exc:
        set_upload_progress(
            upload_id,
            percent=get_upload_progress(upload_id).get("percent", 0),
            message=f"Azure upload failed: {exc}",
            phase="error",
            error=True,
        )
        return jsonify({"ok": False, "error": f"Azure upload failed: {exc}"}), 500
    except Exception as exc:
        set_upload_progress(
            upload_id,
            percent=get_upload_progress(upload_id).get("percent", 0),
            message=f"Upload failed: {exc}",
            phase="error",
            error=True,
        )
        return jsonify({"ok": False, "error": f"Upload failed: {exc}"}), 500

    final_progress = get_upload_progress(upload_id)
    total_bytes = final_progress.get("total")
    set_upload_progress(
        upload_id,
        percent=100,
        message="Upload complete.",
        phase="done",
        transferred=total_bytes,
        total=total_bytes,
        done=True,
    )
    return jsonify(
        {
            "ok": True,
            "blob_url": blob_url,
            "container_name": container_name,
            "blob_name": target_blob_name,
            "file_name": uploaded_file.filename,
        }
    )


def resolve_auth_mode() -> str:
    if os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip():
        return "Connection string"
    if os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip() and os.getenv(
        "AZURE_STORAGE_ACCOUNT_KEY", ""
    ).strip():
        return "Account URL + key"
    return "Not configured"


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000, threaded=True)
