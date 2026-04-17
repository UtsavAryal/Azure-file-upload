const form = document.getElementById("uploadForm");
const fileInput = document.getElementById("fileInput");
const blobNameInput = document.getElementById("blobName");
const dropzone = document.getElementById("dropzone");
const submitButton = document.getElementById("submitButton");

const fileName = document.getElementById("fileName");
const fileType = document.getElementById("fileType");
const fileSize = document.getElementById("fileSize");
const targetBlob = document.getElementById("targetBlob");

const resultBox = document.getElementById("resultBox");
const resultTitle = document.getElementById("resultTitle");
const resultMessage = document.getElementById("resultMessage");
const resultLink = document.getElementById("resultLink");

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

function updateFileDetails() {
    const file = fileInput.files[0];
    if (!file) {
        fileName.textContent = "No file selected";
        fileType.textContent = "-";
        fileSize.textContent = "-";
        targetBlob.textContent = blobNameInput.value.trim() || "-";
        return;
    }

    fileName.textContent = file.name;
    fileType.textContent = file.type || "application/octet-stream";
    fileSize.textContent = formatFileSize(file.size);
    targetBlob.textContent = blobNameInput.value.trim() || file.name;
}

function showResult(kind, message, url) {
    resultBox.hidden = false;
    resultBox.classList.remove("success", "error");
    resultBox.classList.add(kind);
    resultTitle.textContent = kind === "success" ? "Upload complete" : "Upload failed";
    resultMessage.textContent = message;

    if (url) {
        resultLink.hidden = false;
        resultLink.href = url;
    } else {
        resultLink.hidden = true;
        resultLink.removeAttribute("href");
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
        updateFileDetails();
    }
});

fileInput.addEventListener("change", updateFileDetails);
blobNameInput.addEventListener("input", updateFileDetails);

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selectedFile = fileInput.files[0];

    if (!selectedFile) {
        showResult("error", "Please choose a file before uploading.");
        return;
    }

    const data = new FormData(form);
    data.set("overwrite", document.getElementById("overwrite").checked ? "true" : "false");

    submitButton.disabled = true;
    submitButton.textContent = "Uploading...";
    resultBox.hidden = true;

    try {
        const response = await fetch("/upload", {
            method: "POST",
            body: data
        });
        const payload = await response.json();

        if (!response.ok || !payload.ok) {
            throw new Error(payload.error || "Upload failed.");
        }

        showResult(
            "success",
            `Uploaded ${payload.file_name} to ${payload.container_name} as ${payload.blob_name}.`,
            payload.blob_url
        );
    } catch (error) {
        showResult("error", error.message);
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = "Upload to Azure";
    }
});

updateFileDetails();
