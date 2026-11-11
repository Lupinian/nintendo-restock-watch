
import json
import os
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

STATE_FILE = Path("stock_state.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

PRODUCTS = [
    {
        "key": "official",
        "name": "任天堂公式 時のオカリナ",
        "check_url": (
            "https://store-jp.nintendo.com/item/goods/"
            "VM_NSJ_8_AFAC4"
        ),
        "notify_url": (
            "https://share.nsapp.nintendo.com/home/product/"
            "NSJ_8_AFAC4?pt=P&l=ja-JP"
        ),
    },
    {
        "key": "hori",
        "name": "ホリ製 エレクトリック時のオカリナ",
        "check_url": (
            "https://store-jp.nintendo.com/item/goods/"
            "VM_MNS_8_MAAAA"
        ),
        "notify_url": (
            "https://share.nsapp.nintendo.com/home/product/"
            "MNS_8_MAAAA?pt=P&l=ja-JP"
        ),
    },
]


class CartButtonParser(HTMLParser):
    """旧方式との互換用ではなく、ボタン状態の判定基準を明確にするための定義。"""

    def __init__(self):
        super().__init__()
        self.in_button = False
        self.found = False
        self.attrs = {}
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if (
            tag == "button"
            and dict(attrs).get("id") == "productDetail_CartButton"
            and not self.found
        ):
            self.found = True
            self.in_button = True
            self.attrs = dict(attrs)
            self.parts = []

    def handle_data(self, data):
        if self.in_button:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "button" and self.in_button:
            self.in_button = False


def check_stock(browser, product):
    started = time.monotonic()
    page = browser.new_page(
        locale="ja-JP",
        viewport={"width": 1280, "height": 900},
    )

    try:
        print(f"ページ取得開始: {product['name']}")

        response = page.goto(
            product["check_url"],
            wait_until="domcontentloaded",
            timeout=90000,
        )

        if response is not None:
            print(f"HTTP status: {response.status}")

            if response.status >= 400:
                raise RuntimeError(
                    f"商品ページの取得に失敗しました: HTTP {response.status}"
                )

        button = page.locator("#productDetail_CartButton")

        # JavaScriptによるページ遷移後、購入ボタンが現れるまで待つ
        button.wait_for(
            state="attached",
            timeout=60000,
        )

        text = button.inner_text().strip()
        disabled = button.is_disabled()

        print(f"ページタイトル: {page.title()}")
        print(f"ボタン表示: {text}")
        print(f"無効状態: {disabled}")

        if "品切れ" in text:
            status = "out_of_stock"

        elif "カートに入れる" in text and not disabled:
            status = "in_stock"

        else:
            raise RuntimeError(
                f"判定できないボタン状態です: "
                f"text={text!r}, disabled={disabled}"
            )

        elapsed = time.monotonic() - started
        print(f"取得時間: {elapsed:.1f}秒")

        return status

    except Exception:
        # エラー時は原因調査に必要な情報だけを記録
        safe_url = urlsplit(page.url)._replace(
            query="", fragment=""
        ).geturl()

        print(f"取得時のURL: {safe_url}")

        try:
            body = page.locator("body").inner_text(timeout=5000)
            print(f"ページ本文（先頭500文字）: {body[:500]}")
        except Exception:
            print("ページ本文を取得できませんでした。")

        raise

    finally:
        page.close()


def send_notification(product, new_status):
    if new_status == "in_stock":
        message = (
            f"【再入荷】{product['name']}\n"
            "購入可能な状態を検知しました。\n"
            "商品ページを開いて在庫を確認してください。"
        )
        tags = "tada"
    else:
        message = (
            f"【再び品切れ】{product['name']}\n"
            "品切れ状態に変わりました。"
        )
        tags = "no_entry"

    request = Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": "Nintendo Store Stock Alert",
            "Priority": "4",
            "Tags": tags,
            "Click": product["notify_url"],
            "Content-Type": "text/plain; charset=utf-8",
        },
        method="POST",
    )

    with urlopen(request, timeout=20) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(
                f"ntfy notification failed: HTTP {response.status}"
            )


def load_state():
    if not STATE_FILE.exists():
        return {}

    with STATE_FILE.open("r", encoding="utf-8") as file:
        state = json.load(file)

    if not isinstance(state, dict):
        raise RuntimeError("在庫状態ファイルの形式が不正です。")

    return state


def main():
    if not NTFY_TOPIC:
        raise RuntimeError("NTFY_TOPIC が設定されていません。")

    previous = load_state()
    updated = previous.copy()
    errors = False

    # Chromiumは1回だけ起動し、2商品を順番に確認する
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        try:
            for product in PRODUCTS:
                key = product["key"]

                try:
                    current = check_stock(browser, product)
                    old = previous.get(key)

                    print(f"{product['name']}: {current}")

                    if old is None:
                        print(
                            "初回チェック：通知せず状態を記録します。"
                        )
                        updated[key] = current

                    elif old != current:
                        print(f"状態変化: {old} -> {current}")

                        # 通知成功後にのみ状態を更新
                        send_notification(product, current)
                        updated[key] = current
                        print("通知を送信しました。")

                    else:
                        print("状態変化なし。通知は送りません。")

                except Exception as error:
                    errors = True
                    print(f"ERROR [{key}]: {error}")

        finally:
            browser.close()

    if updated != previous:
        STATE_FILE.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("在庫状態を更新しました。")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
