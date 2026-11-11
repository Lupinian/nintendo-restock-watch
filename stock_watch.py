
import json
import os
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

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


def check_stock(product):
    request = Request(
        product["check_url"],
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Safari/605.1.15"
            ),
            "Accept-Language": "ja-JP,ja;q=0.9",
        },
    )

    with urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")

    parser = CartButtonParser()
    parser.feed(html)

    if not parser.found:
        raise RuntimeError(
            "購入ボタンが見つかりません。HTML構造を確認してください。"
        )

    text = "".join(parser.parts).strip()
    attrs = parser.attrs

    if "品切れ" in text:
        return "out_of_stock"

    disabled = (
        "disabled" in attrs
        or str(attrs.get("aria-disabled", "")).lower() == "true"
    )

    if "カートに入れる" in text and not disabled:
        return "in_stock"

    raise RuntimeError(
        f"判定できないボタン状態です: text={text!r}, "
        f"disabled={disabled}"
    )


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

    for product in PRODUCTS:
        key = product["key"]

        try:
            current = check_stock(product)
            old = previous.get(key)

            print(f"{product['name']}: {current}")

            if old is None:
                # 初回は通知せず、現在の状態を基準値として保存
                print("初回チェック：通知せず状態を記録します。")
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
