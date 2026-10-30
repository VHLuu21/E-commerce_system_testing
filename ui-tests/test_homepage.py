
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://localhost:5173"


def test_homepage_loads():
    # Tạo thư mục lưu ảnh chụp màn hình
    Path("screenshots").mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        try:
            page = browser.new_page()

            # Mở trang chủ MarketNest
            page.goto(
                BASE_URL,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            # Chụp ảnh làm minh chứng
            page.screenshot(
                path="screenshots/homepage.png",
                full_page=True,
            )

            # Kiểm tra trang có nội dung hiển thị
            assert page.locator("body").is_visible()
            assert page.locator("body").inner_text().strip(), (
                "Trang chủ không có nội dung văn bản"
            )

            print("Trang chủ MarketNest tải thành công!")
            print("URL:", page.url)
            print("Tiêu đề:", page.title())

        finally:
            browser.close()
