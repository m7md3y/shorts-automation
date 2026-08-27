import json
import os
import pathlib

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE = pathlib.Path(__file__).parent
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
CLIENT_SECRET = BASE / "client_secret.json"
TOKEN = BASE / "token.json"


def get_credentials():
    cid = os.environ.get("YT_CLIENT_ID", "")
    csec = os.environ.get("YT_CLIENT_SECRET", "")
    refresh = os.environ.get("YT_REFRESH_TOKEN", "")
    if cid and csec and refresh:
        creds = Credentials(
            token=None,
            refresh_token=refresh,
            token_uri=TOKEN_URI,
            client_id=cid,
            client_secret=csec,
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return creds

    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET.exists():
                raise RuntimeError("no YT_CLIENT_ID/YT_CLIENT_SECRET/YT_REFRESH_TOKEN and client_secret.json missing")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload_video(meta, privacy="public", publish_at=None):
    creds = get_credentials()
    yt = build("youtube", "v3", credentials=creds)
    status = {"selfDeclaredMadeForKids": False}
    if publish_at:
        status.update({"privacyStatus": "private", "publishAt": publish_at})
    else:
        status["privacyStatus"] = privacy
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["description"],
            "tags": meta.get("tags", []),
            "categoryId": "24",
        },
        "status": status,
    }
    media = MediaFileUpload(meta["file"], chunksize=-1, resumable=True, mimetype="video/mp4")
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        prog, response = request.next_chunk()
        if prog:
            print(f"upload {int(prog.progress() * 100)}%", flush=True)
    if publish_at:
        print(f"SCHEDULED: https://youtu.be/{response['id']} -> {publish_at}", flush=True)
    print(f"UPLOADED: https://youtu.be/{response['id']}", flush=True)
    return response["id"]


if __name__ == "__main__":
    import sys

    meta_path = sys.argv[1]
    privacy = sys.argv[2] if len(sys.argv) > 2 else "public"
    upload_video(json.loads(pathlib.Path(meta_path).read_text(encoding="utf-8")), privacy)