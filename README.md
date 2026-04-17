# Azure Blob Storage File Uploader

Small interactive Python app built with Streamlit for uploading files to Azure Blob Storage through a polished web UI.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` values into your shell environment or a local `.env` loader workflow.

You can also create a local `.env` file in the project root. The app and Flask server load it automatically.

Required configuration:

- `AZURE_STORAGE_CONNECTION_STRING`
- or both `AZURE_STORAGE_ACCOUNT_URL` and `AZURE_STORAGE_ACCOUNT_KEY`
- optional `AZURE_STORAGE_CONTAINER`

## Run

### Streamlit version

```bash
streamlit run app.py
```

### Local HTML + Python server

```bash
python server.py
```

Then open `http://127.0.0.1:5000` in your browser.

## Features

- Upload a file from the browser
- Styled frontend with a dashboard-like layout
- Choose the Azure container at runtime
- Optionally rename the blob before upload
- Optional overwrite protection
- File metadata preview before upload
- Creates the container automatically if it does not already exist
- Includes a local HTML frontend served by Flask
