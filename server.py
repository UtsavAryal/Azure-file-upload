import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import urlparse

from azure.core.exceptions import AzureError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)
from env_utils import load_local_env
from flask import Flask, jsonify, render_template, request


load_local_env()

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
    return generate_sas_blob_url(container_name, blob_name)


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
