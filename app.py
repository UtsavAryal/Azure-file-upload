import base64
import html
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse

import streamlit as st
from azure.core.exceptions import AzureError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)
from auth_utils import authenticate_user, create_user, get_user_by_id, init_user_store
from env_utils import load_local_env


load_local_env()
init_user_store()

TEXT_PREVIEW_BYTES = 96 * 1024
TEXT_FILE_EXTENSIONS = {
    "txt",
    "csv",
    "tsv",
    "json",
    "md",
    "log",
    "xml",
    "html",
    "css",
    "js",
    "ts",
    "py",
    "java",
    "c",
    "cpp",
    "h",
    "sql",
    "yaml",
    "yml",
}


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


def format_file_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def get_file_extension(file_name: str) -> str:
    if "." not in file_name:
        return ""
    return file_name.rsplit(".", 1)[-1].lower()


def get_preview_kind(uploaded_file) -> str:
    mime_type = uploaded_file.type or ""
    extension = get_file_extension(uploaded_file.name)

    if mime_type.startswith("image/"):
        return "image"
    if mime_type == "application/pdf" or extension == "pdf":
        return "pdf"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("text/") or extension in TEXT_FILE_EXTENSIONS:
        return "text"
    return "unsupported"


def render_uploaded_file_preview(uploaded_file) -> None:
    if not uploaded_file:
        st.info("Choose a file to see a preview here.")
        return

    preview_kind = get_preview_kind(uploaded_file)
    file_bytes = uploaded_file.getvalue()

    if preview_kind == "image":
        st.image(file_bytes, caption=uploaded_file.name, use_container_width=True)
        return

    if preview_kind == "pdf":
        encoded_pdf = base64.b64encode(file_bytes).decode("ascii")
        safe_title = html.escape(uploaded_file.name, quote=True)
        st.markdown(
            f"""
            <iframe
                title="Preview of {safe_title}"
                src="data:application/pdf;base64,{encoded_pdf}"
                style="width: 100%; min-height: 430px; border: 1px solid rgba(23, 53, 93, 0.12); border-radius: 14px;"
            ></iframe>
            """,
            unsafe_allow_html=True,
        )
        return

    if preview_kind == "video":
        st.video(file_bytes)
        return

    if preview_kind == "audio":
        st.audio(file_bytes, format=uploaded_file.type or "audio/mpeg")
        return

    if preview_kind == "text":
        preview_bytes = file_bytes[:TEXT_PREVIEW_BYTES]
        preview_text = preview_bytes.decode("utf-8", errors="replace") or "(Empty file)"
        st.code(preview_text, language=get_file_extension(uploaded_file.name) or "text")
        if len(file_bytes) > TEXT_PREVIEW_BYTES:
            st.caption(f"Showing the first {format_file_size(TEXT_PREVIEW_BYTES)} of this file.")
        return

    st.info("This file type can be uploaded, but it does not have an in-browser preview.")


def render_login_gate() -> None:
    user_id = st.session_state.get("user_id")
    if user_id and get_user_by_id(user_id):
        return

    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] > .main {
            max-width: 520px;
            margin: 0 auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Gmail account access")
    auth_mode = st.segmented_control("Choose an option", ["Sign in", "Sign up"], default="Sign in")

    if auth_mode == "Sign up":
        with st.form("signup_form"):
            email = st.text_input("Gmail address", placeholder="name@gmail.com")
            password = st.text_input("Password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create account", use_container_width=True)

        if submitted:
            if password != confirm_password:
                st.error("Passwords do not match.")
            else:
                created, message, user = create_user(email, password)
                if created and user:
                    st.session_state["user_id"] = user["id"]
                    st.session_state["email"] = user["email"]
                    st.rerun()
                else:
                    st.error(message)
    else:
        with st.form("login_form"):
            email = st.text_input("Gmail address", placeholder="name@gmail.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            user = authenticate_user(email, password)
            if user:
                st.session_state["user_id"] = user["id"]
                st.session_state["email"] = user["email"]
                st.rerun()
            else:
                st.error("The Gmail address or password is incorrect.")

    st.stop()


def upload_file(
    uploaded_file,
    container_name: str,
    blob_name: Optional[str],
    overwrite: bool,
    progress_callback=None,
) -> str:
    blob_service_client = build_blob_service_client()
    container_client = blob_service_client.get_container_client(container_name)

    if not container_client.exists():
        container_client.create_container()

    target_blob_name = blob_name.strip() if blob_name else uploaded_file.name
    blob_client = container_client.get_blob_client(target_blob_name)

    file_bytes = uploaded_file.getvalue()
    total_bytes = len(file_bytes)
    content_type = uploaded_file.type or "application/octet-stream"
    content_settings = ContentSettings(content_type=content_type)
    upload_kwargs = {}
    if progress_callback:
        upload_kwargs["progress_hook"] = progress_callback

    blob_client.upload_blob(
        BytesIO(file_bytes),
        length=total_bytes,
        overwrite=overwrite,
        content_settings=content_settings,
        **upload_kwargs,
    )

    return generate_sas_blob_url(container_name, target_blob_name)


st.set_page_config(
    page_title="Azure Blob Uploader",
    page_icon=":cloud:",
    layout="wide",
)

render_login_gate()

st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(11, 116, 222, 0.20), transparent 28%),
            radial-gradient(circle at top right, rgba(0, 184, 148, 0.18), transparent 24%),
            linear-gradient(180deg, #f4f8fc 0%, #eef4fb 48%, #f9fbfd 100%);
    }
    .hero-card {
        padding: 2rem 2.2rem;
        border-radius: 24px;
        background: linear-gradient(135deg, #0b2447 0%, #19376d 55%, #2459a8 100%);
        color: #ffffff;
        box-shadow: 0 22px 60px rgba(18, 52, 86, 0.22);
        margin-bottom: 1.2rem;
    }
    .hero-card h1 {
        margin: 0 0 0.45rem 0;
        font-size: 2.3rem;
    }
    .hero-card p {
        margin: 0;
        max-width: 48rem;
        color: rgba(255, 255, 255, 0.88);
        line-height: 1.6;
    }
    .info-card {
        background: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(36, 89, 168, 0.10);
        border-radius: 18px;
        padding: 1rem 1.1rem;
        box-shadow: 0 14px 32px rgba(34, 68, 120, 0.08);
        min-height: 122px;
    }
    .info-card h3 {
        margin: 0 0 0.4rem 0;
        color: #16345f;
        font-size: 1rem;
    }
    .info-card p {
        margin: 0;
        color: #45607d;
        line-height: 1.55;
    }
    .section-label {
        margin-top: 0.5rem;
        margin-bottom: 0.65rem;
        color: #17355d;
        font-size: 1.05rem;
        font-weight: 700;
    }
    .upload-panel {
        background: rgba(255, 255, 255, 0.93);
        border-radius: 22px;
        padding: 1rem 1rem 0.2rem 1rem;
        border: 1px solid rgba(23, 53, 93, 0.08);
        box-shadow: 0 18px 40px rgba(31, 55, 88, 0.08);
    }
    .status-pill {
        display: inline-block;
        padding: 0.3rem 0.7rem;
        border-radius: 999px;
        background: rgba(11, 116, 222, 0.12);
        color: #0b4ea2;
        font-size: 0.9rem;
        font-weight: 600;
        margin-bottom: 0.85rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-card">
        <div class="status-pill">Interactive frontend for Azure Blob uploads</div>
        <h1>Azure Blob Storage File Uploader</h1>
        <p>
            Upload documents, images, or any project file into your Azure Blob container
            through a clean web interface with live file details and guided configuration.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

top_col_1, top_col_2, top_col_3 = st.columns(3)
with top_col_1:
    st.markdown(
        """
        <div class="info-card">
            <h3>Flexible auth</h3>
            <p>Use a storage connection string or switch to account URL plus access key.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
with top_col_2:
    st.markdown(
        """
        <div class="info-card">
            <h3>Upload controls</h3>
            <p>Choose your container, rename the blob, and decide whether existing files can be replaced.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
with top_col_3:
    st.markdown(
        """
        <div class="info-card">
            <h3>Fast feedback</h3>
            <p>See file metadata before upload and get a secure temporary link once the transfer succeeds.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with st.sidebar:
    st.write(f"Signed in as **{st.session_state.get('email', 'User')}**")
    if st.button("Log out", use_container_width=True):
        st.session_state.pop("user_id", None)
        st.session_state.pop("email", None)
        st.rerun()
    st.divider()
    st.subheader("Connection Guide")
    st.write("Add Azure settings as environment variables before starting the app.")
    st.code(
        "AZURE_STORAGE_CONNECTION_STRING\n"
        "or\n"
        "AZURE_STORAGE_ACCOUNT_URL\n"
        "AZURE_STORAGE_ACCOUNT_KEY\n"
        "AZURE_STORAGE_CONTAINER",
        language="bash",
    )
    st.caption(
        "Connection string is the easiest setup. Container is optional if you want a default."
    )

default_container = os.getenv("AZURE_STORAGE_CONTAINER", "").strip()
has_connection_string = bool(os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip())
has_account_auth = bool(os.getenv("AZURE_STORAGE_ACCOUNT_URL", "").strip()) and bool(
    os.getenv("AZURE_STORAGE_ACCOUNT_KEY", "").strip()
)

left_col, right_col = st.columns([1.35, 0.9], gap="large")

with left_col:
    st.markdown('<div class="section-label">Upload file</div>', unsafe_allow_html=True)
    st.markdown('<div class="upload-panel">', unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "Choose a file",
        type=None,
        accept_multiple_files=False,
        help="Any file type can be uploaded to Azure Blob Storage.",
    )
    with st.form("upload_form", clear_on_submit=False):
        upload_col, name_col = st.columns(2)
        with upload_col:
            container_name = st.text_input(
                "Container name",
                value=default_container,
                help="Defaults to AZURE_STORAGE_CONTAINER if set.",
            )
        with name_col:
            blob_name = st.text_input(
                "Blob name override",
                placeholder="Optional custom filename or folder/file.ext",
            )
        overwrite = st.toggle("Overwrite existing blob if present", value=False)
        submitted = st.form_submit_button("Upload to Azure", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown('<div class="section-label">Session status</div>', unsafe_allow_html=True)
    auth_mode = "Connection string" if has_connection_string else "Account URL + key" if has_account_auth else "Not configured"
    st.metric("Authentication", auth_mode)
    st.metric("Default container", default_container or "Not set")
    if uploaded_file:
        st.metric("Selected file size", format_file_size(uploaded_file.size))
    else:
        st.metric("Selected file size", "No file yet")

    st.markdown('<div class="section-label">Before you upload</div>', unsafe_allow_html=True)
    prep_tab, file_tab, config_tab = st.tabs(["Checklist", "File preview", "Env vars"])
    with prep_tab:
        st.write("1. Add your Azure storage credentials.")
        st.write("2. Confirm the container name you want to upload into.")
        st.write("3. Pick a file and press upload.")
    with file_tab:
        if uploaded_file:
            st.write(f"**Filename:** `{uploaded_file.name}`")
            st.write(f"**Type:** `{uploaded_file.type or 'application/octet-stream'}`")
            st.write(f"**Size:** `{format_file_size(uploaded_file.size)}`")
            if blob_name.strip():
                st.write(f"**Target blob:** `{blob_name.strip()}`")
            render_uploaded_file_preview(uploaded_file)
        else:
            render_uploaded_file_preview(uploaded_file)
    with config_tab:
        st.code(
            "AZURE_STORAGE_CONNECTION_STRING=...\n"
            "AZURE_STORAGE_CONTAINER=uploads",
            language="bash",
        )
        st.caption("Or use AZURE_STORAGE_ACCOUNT_URL plus AZURE_STORAGE_ACCOUNT_KEY.")

if submitted:
    if not container_name.strip():
        st.error("Container name is required.")
    elif not uploaded_file:
        st.error("Please choose a file to upload.")
    else:
        try:
            progress = st.progress(0, text="Preparing upload...")
            progress.progress(20, text="Connecting to Azure Blob Storage...")

            def update_transfer_progress(transferred: int, total: int) -> None:
                if total:
                    percent = 30 + int((transferred / total) * 65)
                    detail = (
                        f"Uploading to Azure Blob Storage... "
                        f"{format_file_size(transferred)} of {format_file_size(total)}"
                    )
                else:
                    percent = 95
                    detail = "Uploading empty file to Azure Blob Storage..."
                progress.progress(min(percent, 95), text=detail)

            with st.spinner("Uploading file to Azure Blob Storage..."):
                progress.progress(30, text="Starting Azure transfer...")
                blob_url = upload_file(
                    uploaded_file=uploaded_file,
                    container_name=container_name.strip(),
                    blob_name=blob_name,
                    overwrite=overwrite,
                    progress_callback=update_transfer_progress,
                )
            progress.progress(100, text="Upload complete.")
            st.success("Upload completed successfully.")
            success_left, success_right = st.columns([1.2, 0.8])
            with success_left:
                st.write(f"Secure blob URL: `{blob_url}`")
                st.write(f"Container: `{container_name.strip()}`")
                st.write(
                    f"Blob name: `{blob_name.strip() if blob_name.strip() else uploaded_file.name}`"
                )
            with success_right:
                st.link_button("Open blob", blob_url, use_container_width=True)
                st.caption("This link is time-limited and keeps your storage account private.")
        except RuntimeError as exc:
            st.error(str(exc))
        except AzureError as exc:
            st.error(f"Azure upload failed: {exc}")
        except Exception as exc:
            st.error(f"Upload failed: {exc}")
