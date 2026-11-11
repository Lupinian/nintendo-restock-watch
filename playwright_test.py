
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL = (
    "https://store-jp.nintendo.com/item/goods/"
    "VM_NSJ_8_AFAC4"
)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            locale="ja-JP",
            viewport={"width": 1280, "height": 900},
        )

        try:
            print("商品ページにアクセスします。")

            page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            print("ページタイトル:", page.title())

            try:
                button = page.locator(
                    "#productDetail_CartButton"
                )

                button.wait_for(
                    state="attached",
                    timeout=30000,
                )

                print("購入ボタンを検出しました。")
                print("ボタン表示:", button.inner_text())
                print("無効状態:", button.is_disabled())

            except PlaywrightTimeoutError:
                print("購入ボタンが見つかりませんでした。")
                print("現在のURL:", urlsplit(page.url)._replace(
                    query="", fragment=""
                ).geturl())
                print("ページ本文:")
                print(page.locator("body").inner_text()[:1000])
                raise RuntimeError(
                    "商品ページの購入ボタンを取得できません。"
                )

        finally:
            browser.close()


if __name__ == "__main__":
    main()
