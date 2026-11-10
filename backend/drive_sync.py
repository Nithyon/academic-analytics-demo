"""Google Drive as a source of faculty sheets.

Two ways to bring workbooks in from Drive:

1. Local folder (recommended, no credentials in this app): install Google Drive for desktop,
   which mirrors a Drive folder to a local path such as "G:/My Drive/Attendance 2026-ODD".
   sync_folder() imports every new or changed .xlsx file in that folder.

2. Drive API (optional): sync_drive_api() lists a Drive folder with the Google Drive API,
   downloads .xlsx files (and exports Google Sheets as .xlsx) into data/drive_cache, then
   imports them. It needs `pip install google-api-python-client google-auth` and a
   service-account key that has been given read access to the folder. This path is written
   against the documented Drive v3 API but has NOT been tested here (no credentials).

Both paths go through excel_io.import_sheets, so the same checks and rules apply.

  python -m backend.drive_sync folder "G:/My Drive/Attendance 2026-ODD"
  python -m backend.drive_sync api FOLDER_ID --key service-account.json
"""
import argparse
import hashlib
import io
import json
from pathlib import Path

from . import config, excel_io

STATE = config.DATA_DIR / "drive_sync_state.json"
CACHE = config.DATA_DIR / "drive_cache"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GSHEET = "application/vnd.google-apps.spreadsheet"


def _load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sync_folder(folder, force=False, db_path=None):
    """Import new or changed workbooks from a local (Drive-mirrored) folder."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    state = _load_state()
    changed, unchanged = [], 0
    for p in sorted(folder.glob("*.xlsx")):
        if p.name.startswith("~$"):  # Excel lock files
            continue
        d = _digest(p)
        if not force and state.get(str(p.resolve())) == d:
            unchanged += 1
            continue
        changed.append((p, d))
    report = {"folder": str(folder), "new_or_changed": len(changed), "unchanged": unchanged,
              "files": 0, "attendance_rows": 0, "assessment_rows": 0, "problems": []}
    if changed:
        rep = excel_io.import_sheets([p for p, _d in changed], db_path)
        report.update({k: rep[k] for k in ("files", "attendance_rows", "assessment_rows", "problems")})
        for p, d in changed:
            state[str(p.resolve())] = d
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return report


def sync_drive_api(folder_id, key_file, db_path=None):  # pragma: no cover - needs credentials
    """Download workbooks from a Drive folder with the Drive v3 API, then import them."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise SystemExit("Install the optional packages first: "
                         "pip install google-api-python-client google-auth") from exc
    creds = service_account.Credentials.from_service_account_file(
        key_file, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    CACHE.mkdir(parents=True, exist_ok=True)
    q = f"'{folder_id}' in parents and trashed = false and (mimeType = '{XLSX}' or mimeType = '{GSHEET}')"
    files, token = [], None
    while True:
        resp = drive.files().list(q=q, fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                                  pageToken=token).execute()
        files += resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            break
    for f in files:
        name = f["name"] if f["name"].lower().endswith(".xlsx") else f["name"] + ".xlsx"
        req = (drive.files().export_media(fileId=f["id"], mimeType=XLSX) if f["mimeType"] == GSHEET
               else drive.files().get_media(fileId=f["id"]))
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _status, done = dl.next_chunk()
        (CACHE / Path(name).name).write_bytes(buf.getvalue())
    return sync_folder(CACHE, db_path=db_path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    f = sub.add_parser("folder")
    f.add_argument("path")
    f.add_argument("--force", action="store_true", help="re-import unchanged files too")
    a = sub.add_parser("api")
    a.add_argument("folder_id")
    a.add_argument("--key", required=True, help="service-account JSON key file")
    args = ap.parse_args()
    rep = sync_folder(args.path, args.force) if args.mode == "folder" else sync_drive_api(args.folder_id, args.key)
    print({k: v for k, v in rep.items() if k != "problems"})
    for p in rep["problems"][:50]:
        print(" -", p)
