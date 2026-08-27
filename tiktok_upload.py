import json
import os
import time

import requests

BASE = "https://open.tiktokapis.com"


def get_access_token():
    tk = os.environ.get("TTK_REFRESH_TOKEN", "")
    ky = os.environ.get("TTK_CLIENT_KEY", "")
    sc = os.environ.get("TTK_CLIENT_SECRET", "")
    if not (tk and ky and sc):
        raise RuntimeError("TTK env missing (client_key/secret/refresh_token)")
    r = requests.post(
        f"{BASE}/v2/oauth/token/",
        data={
            "client_key": ky,
            "client_secret": sc,
            "grant_type": "refresh_token",
            "refresh_token": tk,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=60,
    )
    d = r.json()
    if "access_token" not in d:
        raise RuntimeError(f"TTK token refresh failed: {json.dumps(d)}")
    print("TTK access token refreshed", flush=True)
    return d["access_token"]


def _init(headers, privacy, title):
    return requests.post(
        f"{BASE}/v2/post/publish/video/init/",
        headers=headers,
        json={
            "post_info": {
                "title": title[:2200],
                "privacy_level": privacy,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {"source": "FILE_UPLOAD"},
        },
        timeout=120,
    ).json()


def post_video(video_path, title):
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    resp = _init(headers, "PUBLIC_TO_EVERYONE", title)
    err_code = (resp.get("error") or {}).get("code", "")
    if err_code == "unaudited_client_can_only_post_to_private_accounts":
        print("TTK: app unaudited -> posting as SELF_ONLY (private)", flush=True)
        resp = _init(headers, "SELF_ONLY", title)
    data = resp.get("data") or {}
    publish_id = data.get("publish_id")
    upload_url = data.get("upload_url")
    if not (publish_id and upload_url):
        raise RuntimeError(f"TTK init failed: {json.dumps(resp, ensure_ascii=False)}")

    size = os.path.getsize(video_path)
    with open(video_path, "rb") as fh:
        up = requests.put(
            upload_url,
            data=fh,
            headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
            timeout=1200,
        )
    if up.status_code >= 300:
        raise RuntimeError(f"TTK upload HTTP {up.status_code}: {up.text[:500]}")

    for _ in range(90):
        time.sleep(10)
        st = requests.post(
            f"{BASE}/v2/post/publish/status/fetch/",
            headers=headers,
            json={"publish_id": publish_id},
            timeout=60,
        ).json()
        s = ((st.get("data") or {}).get("status") or "")
        print(f"TTK status: {s}", flush=True)
        if s in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            print(f"TTK PUBLISHED publish_id={publish_id}", flush=True)
            return True
        if s == "FAILED":
            raise RuntimeError(f"TTK publish FAILED: {json.dumps(st, ensure_ascii=False)}")
    raise RuntimeError("TTK status poll timeout")