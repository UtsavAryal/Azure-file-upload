const form = document.getElementById("uploadForm");
const fileInput = document.getElementById("fileInput");
const containerNameInput = document.getElementById("containerName");
const blobNameInput = document.getElementById("blobName");
const dropzone = document.getElementById("dropzone");
const submitButton = document.getElementById("submitButton");
const refreshFilesButton = document.getElementById("refreshFilesButton");

const fileName = document.getElementById("fileName");
const fileType = document.getElementById("fileType");
const fileSize = document.getElementById("fileSize");
const targetBlob = document.getElementById("targetBlob");

const resultBox = document.getElementById("resultBox");
const resultTitle = document.getElementById("resultTitle");
const resultMessage = document.getElementById("resultMessage");
const resultLink = document.getElementById("resultLink");

const progressTracker = document.getElementById("progressTracker");
const progressStatus = document.getElementById("progressStatus");
const progressPercent = document.getElementById("progressPercent");
const progressMeter = document.getElementById("progressMeter");
const progressFill = document.getElementById("progressFill");
const progressDetail = document.getElementById("progressDetail");

const previewTitle = document.getElementById("previewTitle");
const previewBadge = document.getElementById("previewBadge");
const previewLoader = document.getElementById("previewLoader");
const previewLoaderText = document.getElementById("previewLoaderText");
const previewLoaderPercent = document.getElementById("previewLoaderPercent");
const previewMeter = document.getElementById("previewMeter");
const previewFill = document.getElementById("previewFill");
const previewStage = document.getElementById("previewStage");
const fileSystemStatus = document.getElementById("fileSystemStatus");
const fileTableWrap = document.getElementById("fileTableWrap");
const fileTableBody = document.getElementById("fileTableBody");

let activeProgressTimer = null;
let currentProgressPercent = 0;
let activePreviewUrl = null;
let activePreviewReader = null;
let previewSequence = 0;

const TEXT_PREVIEW_BYTES = 96 * 1024;
const TEXT_FILE_EXTENSIONS = new Set([
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
    "yml"
]);

function formatFileSize(size) {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = size;
    let index = 0;

    while (value >= 1024 && index < units.length - 1) {
        value /= 1024;
        index += 1;
    }

    return `${value.toFixed(1)} ${units[index]}`;
}

function formatDateTime(value) {
    if (!value) {
        return "-";
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return "-";
    }

    return parsed.toLocaleString([], {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit"
    });
}

function getFileExtension(fileName) {
    const lastDot = fileName.lastIndexOf(".");
    if (lastDot === -1) {
        return "";
    }

    return fileName.slice(lastDot + 1).toLowerCase();
}

function getPreviewKind(file) {
    const mimeType = file.type || "";
    const extension = getFileExtension(file.name);

    if (mimeType.startsWith("image/")) {
        return "image";
    }

    if (mimeType === "application/pdf" || extension === "pdf") {
        return "pdf";
    }

    if (mimeType.startsWith("video/")) {
        return "video";
    }

    if (mimeType.startsWith("audio/")) {
        return "audio";
    }

    if (mimeType.startsWith("text/") || TEXT_FILE_EXTENSIONS.has(extension)) {
        return "text";
    }

    return "unsupported";
}

function revokeActivePreviewUrl() {
    if (activePreviewUrl) {
        URL.revokeObjectURL(activePreviewUrl);
        activePreviewUrl = null;
    }
}

function abortActivePreviewReader() {
    if (activePreviewReader && activePreviewReader.readyState === FileReader.LOADING) {
        activePreviewReader.abort();
    }
    activePreviewReader = null;
}

function clearPreviewStage(message) {
    const emptyState = document.createElement("p");
    emptyState.className = "preview-empty";
    emptyState.textContent = message;
    previewStage.replaceChildren(emptyState);
}

function setPreviewBadge(text, state = "") {
    previewBadge.className = "preview-badge";
    if (state) {
        previewBadge.classList.add(`is-${state}`);
    }
    previewBadge.textContent = text;
}

function setPreviewLoading(percent, detail) {
    const safePercent = Math.max(0, Math.min(100, Math.round(percent)));

    previewLoader.hidden = false;
    previewLoaderText.textContent = detail;
    previewLoaderPercent.textContent = `${safePercent}%`;
    previewFill.style.width = `${safePercent}%`;
    previewMeter.setAttribute("aria-valuenow", String(safePercent));
}

function hidePreviewLoading() {
    previewLoader.hidden = true;
    previewFill.style.width = "0%";
    previewLoaderPercent.textContent = "0%";
    previewMeter.setAttribute("aria-valuenow", "0");
}

function resetFilePreview() {
    previewSequence += 1;
    abortActivePreviewReader();
    revokeActivePreviewUrl();
    hidePreviewLoading();
    previewTitle.textContent = "No preview yet";
    setPreviewBadge("Idle");
    clearPreviewStage("Choose a file to see a preview here.");
}

function renderPreviewError(message) {
    hidePreviewLoading();
    setPreviewBadge("Unavailable", "error");
    clearPreviewStage(message);
}

function renderObjectPreview(file, kind, token) {
    const previewUrl = URL.createObjectURL(file);
    activePreviewUrl = previewUrl;
    previewStage.replaceChildren();

    if (kind === "image") {
        const image = document.createElement("img");
        image.alt = `Preview of ${file.name}`;
        image.src = previewUrl;
        image.addEventListener("load", () => {
            if (token !== previewSequence) {
                return;
            }
            hidePreviewLoading();
            setPreviewBadge("Image", "success");
        });
        image.addEventListener("error", () => {
            if (token === previewSequence) {
                renderPreviewError("This image could not be previewed.");
            }
        });
        previewStage.appendChild(image);
        return;
    }

    if (kind === "pdf") {
        const frame = document.createElement("iframe");
        frame.title = `Preview of ${file.name}`;
        frame.src = previewUrl;
        previewStage.appendChild(frame);
        hidePreviewLoading();
        setPreviewBadge("PDF", "success");
        return;
    }

    if (kind === "video") {
        const video = document.createElement("video");
        video.controls = true;
        video.preload = "metadata";
        video.src = previewUrl;
        previewStage.appendChild(video);
        hidePreviewLoading();
        setPreviewBadge("Video", "success");
        return;
    }

    if (kind === "audio") {
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.preload = "metadata";
        audio.src = previewUrl;
        previewStage.appendChild(audio);
        hidePreviewLoading();
        setPreviewBadge("Audio", "success");
    }
}

function renderTextPreview(file, token) {
    const previewSlice = file.slice(0, Math.min(file.size, TEXT_PREVIEW_BYTES));
    const reader = new FileReader();
    activePreviewReader = reader;

    reader.addEventListener("progress", (event) => {
        if (token !== previewSequence) {
            return;
        }

        const percent = event.lengthComputable && event.total
            ? (event.loaded / event.total) * 92
            : 60;
        setPreviewLoading(percent, "Reading text preview...");
    });

    reader.addEventListener("load", () => {
        if (token !== previewSequence) {
            return;
        }

        const text = String(reader.result || "");
        const pre = document.createElement("pre");
        pre.textContent = text || "(Empty file)";

        previewStage.replaceChildren(pre);

        if (file.size > TEXT_PREVIEW_BYTES) {
            const note = document.createElement("p");
            note.className = "preview-note";
            note.textContent = `Showing the first ${formatFileSize(TEXT_PREVIEW_BYTES)} of this file.`;
            previewStage.appendChild(note);
        }

        activePreviewReader = null;
        hidePreviewLoading();
        setPreviewBadge("Text", "success");
    });

    reader.addEventListener("error", () => {
        if (token === previewSequence) {
            activePreviewReader = null;
            renderPreviewError("This text file could not be previewed.");
        }
    });

    reader.readAsText(previewSlice);
}

function renderFilePreview(file) {
    if (!file) {
        resetFilePreview();
        return;
    }

    previewSequence += 1;
    const token = previewSequence;
    abortActivePreviewReader();
    revokeActivePreviewUrl();

    previewTitle.textContent = file.name;
    setPreviewBadge("Loading", "active");
    clearPreviewStage("Preparing preview...");
    setPreviewLoading(8, "Preparing preview...");

    const previewKind = getPreviewKind(file);

    if (previewKind === "text") {
        renderTextPreview(file, token);
        return;
    }

    if (["image", "pdf", "video", "audio"].includes(previewKind)) {
        renderObjectPreview(file, previewKind, token);
        return;
    }

    hidePreviewLoading();
    setPreviewBadge("File", "active");
    clearPreviewStage("This file type can be uploaded, but it does not have an in-browser preview.");
}

function createUploadId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
        return window.crypto.randomUUID();
    }

    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function setProgress(percent, status, detail, state = "active") {
    const safePercent = Math.max(0, Math.min(100, Math.round(percent)));
    currentProgressPercent = safePercent;

    progressTracker.hidden = false;
    progressTracker.classList.remove("is-active", "is-success", "is-error");
    progressTracker.classList.add(`is-${state}`);
    progressStatus.textContent = status;
    progressPercent.textContent = `${safePercent}%`;
    progressFill.style.width = `${safePercent}%`;
    progressMeter.setAttribute("aria-valuenow", String(safePercent));
    progressDetail.textContent = detail || "";
}

function resetProgress() {
    currentProgressPercent = 0;
    progressTracker.hidden = true;
    progressFill.style.width = "0%";
    progressMeter.setAttribute("aria-valuenow", "0");
    progressPercent.textContent = "0%";
    progressStatus.textContent = "Waiting to start";
    progressDetail.textContent = "Progress appears here once the upload starts.";
}

function stopProgressPolling() {
    if (activeProgressTimer) {
        window.clearInterval(activeProgressTimer);
        activeProgressTimer = null;
    }
}

async function pollUploadProgress(uploadId) {
    try {
        const response = await fetch(`/progress/${encodeURIComponent(uploadId)}`, {
            cache: "no-store"
        });

        if (!response.ok) {
            return;
        }

        const update = await response.json();
        const percent = Number(update.percent) || 0;

        if (update.phase === "queued" && currentProgressPercent > percent) {
            return;
        }

        const transferred = Number(update.transferred);
        const total = Number(update.total);
        const detail = Number.isFinite(transferred) && Number.isFinite(total) && total > 0
            ? `${formatFileSize(transferred)} of ${formatFileSize(total)}`
            : "";
        const state = update.error ? "error" : update.done ? "success" : "active";

        setProgress(
            Math.max(percent, currentProgressPercent),
            update.message || "Working...",
            detail,
            state
        );

        if (update.done || update.error) {
            stopProgressPolling();
        }
    } catch (error) {
        // The upload request itself owns the user-facing error state.
    }
}

function startProgressPolling(uploadId) {
    stopProgressPolling();
    pollUploadProgress(uploadId);
    activeProgressTimer = window.setInterval(() => pollUploadProgress(uploadId), 600);
}

function describeBrowserUploadProgress(event, startedAt) {
    if (!event.lengthComputable) {
        return "Sending file to the app...";
    }

    const elapsedSeconds = Math.max((performance.now() - startedAt) / 1000, 0.1);
    const transferRate = event.loaded / elapsedSeconds;

    return `${formatFileSize(event.loaded)} of ${formatFileSize(event.total)} at ${formatFileSize(transferRate)}/s`;
}

function updateFileDetails() {
    const file = fileInput.files[0];
    if (!file) {
        fileName.textContent = "No file selected yet";
        fileType.textContent = "-";
        fileSize.textContent = "-";
        targetBlob.textContent = blobNameInput.value.trim() || "Waiting for your file";
        return;
    }

    fileName.textContent = file.name;
    fileType.textContent = file.type || "application/octet-stream";
    fileSize.textContent = formatFileSize(file.size);
    targetBlob.textContent = blobNameInput.value.trim() || file.name;
}

function handleFileSelection() {
    updateFileDetails();
    renderFilePreview(fileInput.files[0]);
    resetProgress();
}

function showResult(kind, message, url) {
    resultBox.hidden = false;
    resultBox.classList.remove("success", "error");
    resultBox.classList.add(kind);
    resultTitle.textContent = kind === "success" ? "Your file made it" : "Something needs attention";
    resultMessage.textContent = message;

    if (url) {
        resultLink.hidden = false;
        resultLink.href = url;
    } else {
        resultLink.hidden = true;
        resultLink.removeAttribute("href");
    }
}

function setFileSystemStatus(message, state = "") {
    fileSystemStatus.classList.remove("is-error");
    if (state) {
        fileSystemStatus.classList.add(`is-${state}`);
    }
    fileSystemStatus.textContent = message;
}

function buildDownloadUrl(containerName, blobName) {
    const params = new URLSearchParams({
        container_name: containerName,
        blob_name: blobName
    });
    return `/download?${params.toString()}`;
}

function renderFileSystem(containerName, files) {
    fileTableBody.replaceChildren();

    if (!files.length) {
        fileTableWrap.hidden = true;
        setFileSystemStatus(`No files were found in ${containerName}.`);
        return;
    }

    const fragment = document.createDocumentFragment();
    files.forEach((file) => {
        const row = document.createElement("tr");

        const nameCell = document.createElement("td");
        nameCell.textContent = file.name;
        nameCell.title = file.name;

        const typeCell = document.createElement("td");
        typeCell.textContent = file.content_type || "application/octet-stream";

        const sizeCell = document.createElement("td");
        sizeCell.textContent = formatFileSize(Number(file.size) || 0);

        const modifiedCell = document.createElement("td");
        modifiedCell.textContent = formatDateTime(file.last_modified);

        const actionCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = buildDownloadUrl(containerName, file.name);
        link.textContent = "Download";
        link.setAttribute("download", "");
        actionCell.appendChild(link);

        row.append(nameCell, typeCell, sizeCell, modifiedCell, actionCell);
        fragment.appendChild(row);
    });

    fileTableBody.appendChild(fragment);
    fileTableWrap.hidden = false;
    setFileSystemStatus(`Loaded ${files.length} file${files.length === 1 ? "" : "s"} from ${containerName}.`);
}

async function loadFileSystem() {
    const containerName = containerNameInput.value.trim();

    if (!containerName) {
        fileTableWrap.hidden = true;
        setFileSystemStatus("Enter a container name above, then refresh to load downloadable files.", "error");
        return;
    }

    refreshFilesButton.disabled = true;
    setFileSystemStatus(`Loading files from ${containerName}...`);

    try {
        const params = new URLSearchParams({ container_name: containerName });
        const response = await fetch(`/files?${params.toString()}`, {
            cache: "no-store"
        });
        const payload = await response.json();

        if (!response.ok || !payload.ok) {
            throw new Error(payload.error || "Could not load files.");
        }

        renderFileSystem(containerName, payload.files || []);
    } catch (error) {
        fileTableWrap.hidden = true;
        setFileSystemStatus(error.message || "Could not load files.", "error");
    } finally {
        refreshFilesButton.disabled = false;
    }
}

["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.add("is-dragover");
    });
});

["dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.remove("is-dragover");
    });
});

dropzone.addEventListener("drop", (event) => {
    const files = event.dataTransfer.files;
    if (files && files.length > 0) {
        fileInput.files = files;
        handleFileSelection();
    }
});

fileInput.addEventListener("change", handleFileSelection);
blobNameInput.addEventListener("input", updateFileDetails);
containerNameInput.addEventListener("input", () => {
    fileTableWrap.hidden = true;
    setFileSystemStatus("Container changed. Refresh to load downloadable files.");
});
refreshFilesButton.addEventListener("click", loadFileSystem);

form.addEventListener("submit", (event) => {
    event.preventDefault();
    const selectedFile = fileInput.files[0];

    if (!selectedFile) {
        showResult("error", "Please choose a file before uploading.");
        return;
    }

    const data = new FormData(form);
    const uploadId = createUploadId();
    const startedAt = performance.now();
    data.set("overwrite", document.getElementById("overwrite").checked ? "true" : "false");
    data.set("upload_id", uploadId);

    submitButton.disabled = true;
    submitButton.textContent = "Uploading...";
    resultBox.hidden = true;
    setProgress(0, "Starting upload...", "Preparing the file handoff.", "active");
    startProgressPolling(uploadId);

    const request = new XMLHttpRequest();

    request.upload.addEventListener("progress", (progressEvent) => {
        if (!progressEvent.lengthComputable) {
            setProgress(
                Math.max(currentProgressPercent, 8),
                "Sending file to the app...",
                "Upload size is not available from the browser.",
                "active"
            );
            return;
        }

        const browserPercent = (progressEvent.loaded / progressEvent.total) * 35;
        setProgress(
            Math.max(currentProgressPercent, browserPercent),
            "Sending file to the app...",
            describeBrowserUploadProgress(progressEvent, startedAt),
            "active"
        );
    });

    request.upload.addEventListener("load", () => {
        setProgress(
            Math.max(currentProgressPercent, 38),
            "File received by the app...",
            "Preparing the Azure Blob transfer.",
            "active"
        );
    });

    request.addEventListener("load", () => {
        let payload = {};
        try {
            payload = JSON.parse(request.responseText);
        } catch (error) {
            payload = { ok: false, error: "The server returned an unreadable response." };
        }

        if (request.status < 200 || request.status >= 300 || !payload.ok) {
            const message = payload.error || "Upload failed.";
            setProgress(currentProgressPercent, "Upload failed.", message, "error");
            showResult("error", message);
        } else {
            setProgress(100, "Upload complete.", "Azure Blob link is ready.", "success");
            showResult(
                "success",
                `Uploaded ${payload.file_name} to ${payload.container_name} as ${payload.blob_name}.`,
                payload.blob_url
            );
            loadFileSystem();
        }

        stopProgressPolling();
        submitButton.disabled = false;
        submitButton.textContent = "Upload file";
    });

    request.addEventListener("error", () => {
        const message = "The upload could not reach the server.";
        stopProgressPolling();
        setProgress(currentProgressPercent, "Upload failed.", message, "error");
        showResult("error", message);
        submitButton.disabled = false;
        submitButton.textContent = "Upload file";
    });

    request.open("POST", "/upload");
    request.send(data);
});

updateFileDetails();
resetFilePreview();
resetProgress();
if (containerNameInput.value.trim()) {
    loadFileSystem();
}
