
import os
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


BASE_URL = "http://localhost:5173"
SCREENSHOTS = Path("screenshots")


def test_add_product_to_cart():
    """Đăng nhập và thêm sản phẩm vào giỏ hàng."""

    email = os.getenv("MARKETNEST_TEST_EMAIL")
    password = os.getenv("MARKETNEST_TEST_PASSWORD")

    assert email and password, (
        "Chưa cấu hình tài khoản kiểm thử."
    )

    SCREENSHOTS.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        try:
            page = browser.new_page()

            # 1. Đăng nhập
            page.goto(
                f"{BASE_URL}/login",
                wait_until="domcontentloaded",
            )
            page.get_by_label("Email").fill(email)
            page.locator("#password").fill(password)

            page.get_by_role(
                "button", name="Đăng nhập ngay"
            ).click()

            expect(page).not_to_have_url(
                __import__("re").compile(r".*/login/?$"),
                timeout=10000,
            )

            # 2. Mở trang chi tiết sản phẩm
            page.goto(
                f"{BASE_URL}/products/80",
                wait_until="domcontentloaded",
            )

            # 3. Nhấn nút thêm vào giỏ hàng và chờ API phản hồi
            with page.expect_response(
                lambda response:
                    "/cart/items" in response.url
                    and response.request.method == "POST"
            ) as response_info:
                page.get_by_role(
                    "button", name="Thêm vào giỏ hàng"
                ).click()

            response = response_info.value
            assert response.status in (200, 201), (
                f"Thêm vào giỏ hàng thất bại: HTTP {response.status}"
            )

            # 4. Mở giỏ hàng để xác nhận sản phẩm
            page.goto(
                f"{BASE_URL}/cart",
                wait_until="domcontentloaded",
            )

            expect(
                page.get_by_text(
                    "Alex-15_White", exact=False
                ).first
            ).to_be_visible(timeout=15000)

            # 5. Lưu ảnh minh chứng
            page.screenshot(
                path=str(SCREENSHOTS / "cart-product.png"),
                full_page=True,
            )

            print("Thêm sản phẩm vào giỏ hàng thành công!")
            print("API status:", response.status)

        finally:
            browser.close()
