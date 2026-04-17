import os
from io import BytesIO

from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient, ContentSettings
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request


load_dotenv()

app = Flask(__name__)


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


def upload_file_to_blob(file_storage, container_name: str, blob_name: str, overwrite: bool) -> str:
    blob_service_client = build_blob_service_client()
    container_client = blob_service_client.get_container_client(container_name)

    if not container_client.exists():
        container_client.create_container()

    blob_client = container_client.get_blob_client(blob_name)
    file_bytes = file_storage.read()
    content_type = file_storage.mimetype or "application/octet-stream"

    blob_client.upload_blob(
        BytesIO(file_bytes),
        overwrite=overwrite,
        content_settings=ContentSettings(content_type=content_type),
    )
    return blob_client.url


@app.get("/")
def index():
    return render_template(
        "index.html",
        default_container=os.getenv("AZURE_STORAGE_CONTAINER", "").strip(),
        auth_mode=resolve_auth_mode(),
    )


@app.post("/upload")
def upload():
    uploaded_file = request.files.get("file")
    container_name = request.form.get("container_name", "").strip()
    blob_name = request.form.get("blob_name", "").strip()
    overwrite = request.form.get("overwrite", "false").lower() == "true"

    if not container_name:
        return jsonify({"ok": False, "error": "Container name is required."}), 400

    if uploaded_file is None or not uploaded_file.filename:
        return jsonify({"ok": False, "error": "Please choose a file to upload."}), 400

    target_blob_name = blob_name or uploaded_file.filename

    try:
        blob_url = upload_file_to_blob(
            file_storage=uploaded_file,
            container_name=container_name,
            blob_name=target_blob_name,
            overwrite=overwrite,
        )
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except AzureError as exc:
        return jsonify({"ok": False, "error": f"Azure upload failed: {exc}"}), 500

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
    app.run(debug=True, host="127.0.0.1", port=5000)
