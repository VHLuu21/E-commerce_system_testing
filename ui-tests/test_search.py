
import os
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


BASE_URL = "http://localhost:5173"
LOGIN_URL = f"{BASE_URL}/login"
SCREENSHOTS = Path("screenshots")


def test_search_existing_product():
    """Đăng nhập rồi tìm kiếm sản phẩm có tồn tại."""

    email = os.getenv("MARKETNEST_TEST_EMAIL")
    password = os.getenv("MARKETNEST_TEST_PASSWORD")

    assert email and password, (
        "Chưa cấu hình tài khoản kiểm thử trong biến môi trường."
    )

    SCREENSHOTS.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        try:
            page = browser.new_page()

            # Bước 1: Đăng nhập
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.get_by_label("Email").fill(email)
            page.locator("#password").fill(password)

            page.get_by_role(
                "button", name="Đăng nhập ngay"
            ).click()

            # Xác nhận đã rời trang đăng nhập
            expect(page).not_to_have_url(
                LOGIN_URL,
                timeout=10000,
            )

            # Bước 2: Truy cập trang chủ sau khi đăng nhập
            page.goto(BASE_URL, wait_until="domcontentloaded")

            # Bước 3: Tìm kiếm sản phẩm
            search_box = page.get_by_placeholder(
                "Tìm kiếm sản phẩm, thương hiệu, danh mục..."
            )
            search_box.fill("Alex-15_White")

            page.get_by_role(
                "button", name="Tìm kiếm"
            ).click()

            # Bước 4: Xác nhận kết quả
            expect(
                page.get_by_text(
                    "Alex-15_White", exact=False
                ).first
            ).to_be_visible(timeout=15000)

            page.screenshot(
                path=str(SCREENSHOTS / "search-product.png"),
                full_page=True,
            )

            print("Đăng nhập và tìm kiếm sản phẩm thành công!")

        finally:
            browser.close()
