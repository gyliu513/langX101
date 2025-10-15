'''
这个例子展示了什么？

标准 OAuth 2.0 Device Authorization Flow

第一步向 GitHub 申请 device_code 与 user_code

用户在浏览器打开 https://github.com/login/device 输入 user_code

程序用 device_code 轮询令牌端点，换取 access_token

用 access_token 调用受保护 API（示例里是 /user 和 /user/emails）
'''

# github_device_oauth.py
import time
import webbrowser
import requests

from dotenv import load_dotenv
import os

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")       # ← 替换成你的 GitHub OAuth App 的 Client ID
# CLIENT_ID = "YOUR_CLIENT_ID_HERE"       # ← 替换成你的 GitHub OAuth App 的 Client ID
SCOPE = "read:user user:email"          # 需要的权限范围（可按需精简）

DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
VERIFY_URL = "https://github.com/login/device"

def get_device_code():
    resp = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": CLIENT_ID, "scope": SCOPE},
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()

def poll_token(device_code, interval):
    while True:
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "access_token" in data:
            return data["access_token"]

        error = data.get("error")
        if error == "authorization_pending":
            time.sleep(interval)
            continue
        elif error == "slow_down":
            interval += 5
            time.sleep(interval)
            continue
        elif error in ("expired_token", "access_denied"):
            raise RuntimeError(f"Stopped: {error}")
        else:
            raise RuntimeError(f"Unexpected token error: {data}")

def api_get(url, token):
    r = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def main():
    # 1) 申请 device_code
    dc = get_device_code()
    user_code = dc["user_code"]
    device_code = dc["device_code"]
    verification_uri = dc.get("verification_uri", VERIFY_URL)
    interval = int(dc.get("interval", 5))

    print("=== GitHub OAuth Device Flow ===")
    print(f"打开这个网址并输入代码：{verification_uri}")
    print(f"用户代码（User Code）：{user_code}")
    try:
        webbrowser.open(verification_uri)
    except Exception:
        pass

    # 2) 轮询换取 access_token（等你在浏览器完成授权）
    print("等待你在浏览器完成授权中...")
    token = poll_token(device_code, interval)
    print("授权成功，拿到 access_token：", token[:6] + "..." )

    # 3) 用 access_token 调 GitHub API（示例：获取个人信息与邮箱）
    me = api_get("https://api.github.com/user", token)
    emails = api_get("https://api.github.com/user/emails", token)

    print("\n== 你的 GitHub 账号信息 ==")
    print("Login:", me.get("login"))
    print("Name :", me.get("name"))
    print("ID   :", me.get("id"))

    primary_email = next((e["email"] for e in emails if e.get("primary")), None)
    print("Primary email:", primary_email or "(无主邮箱或未授权 user:email)")

if __name__ == "__main__":
    main()

