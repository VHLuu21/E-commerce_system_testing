import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


BASE_URL = "http://localhost:5173"
PRODUCT_ID = os.getenv("MARKETNEST_TEST_PRODUCT_ID", "80")
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


def test_checkout_success():
    """Đăng nhập, chọn sản phẩm trong giỏ và hoàn tất đặt hàng COD."""

    email = os.getenv("MARKETNEST_TEST_EMAIL")
    password = os.getenv("MARKETNEST_TEST_PASSWORD")

    assert email and password, (
        "Chưa cấu hình MARKETNEST_TEST_EMAIL và MARKETNEST_TEST_PASSWORD."
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)

        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})

            # 1. Đăng nhập bằng tài khoản khách hàng.
            page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
            page.locator("#email").fill(email)
            page.locator("#password").fill(password)

            with page.expect_response(
                lambda response: (
                    "/auth/login" in response.url
                    and response.request.method == "POST"
                ),
                timeout=15000,
            ) as response_info:
                page.get_by_role(
                    "button",
                    name="Đăng nhập ngay",
                ).click()

            login_response = response_info.value
            assert login_response.status in (200, 201), (
                "Đăng nhập thất bại: "
                f"HTTP {login_response.status} - {login_response.text()}"
            )

            expect(page).not_to_have_url(
                re.compile(r".*/login/?$"),
                timeout=10000,
            )

            # 2. Kiểm tra giỏ hàng trước để test có thể chạy lại nhiều lần.
            page.goto(f"{BASE_URL}/cart", wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            product_row = page.locator(
                f'article.cart-item:has(a[href="/products/{PRODUCT_ID}"])'
            )

            if product_row.count() == 0:
                page.goto(
                    f"{BASE_URL}/products/{PRODUCT_ID}",
                    wait_until="domcontentloaded",
                )

                with page.expect_response(
                    lambda response: (
                        "/cart/items" in response.url
                        and response.request.method == "POST"
                    ),
                    timeout=15000,
                ) as cart_response_info:
                    page.get_by_role(
                        "button",
                        name="Thêm vào giỏ hàng",
                    ).click()

                cart_response = cart_response_info.value
                assert cart_response.status in (200, 201), (
                    "Thêm sản phẩm vào giỏ hàng thất bại: "
                    f"HTTP {cart_response.status} - {cart_response.text()}"
                )

                page.goto(f"{BASE_URL}/cart", wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                product_row = page.locator(
                    f'article.cart-item:has(a[href="/products/{PRODUCT_ID}"])'
                )

            expect(product_row).to_have_count(1, timeout=15000)
            expect(product_row).to_be_visible(timeout=15000)

            page.screenshot(
                path=str(SCREENSHOT_DIR / "cart-checkout-debug.png"),
                full_page=True,
            )

            # 3. Chọn đúng CartItem rồi đi qua nút checkout của giao diện.
            product_checkbox = product_row.locator('input[type="checkbox"]')
            expect(product_checkbox).to_be_enabled()

            if not product_checkbox.is_checked():
                product_checkbox.check()

            checkout_button = page.get_by_role(
                "button",
                name=re.compile(r"Tiến hành đặt hàng", re.IGNORECASE),
            )
            expect(checkout_button).to_be_enabled()
            checkout_button.click()

            expect(page).to_have_url(
                re.compile(r".*/checkout/?$"),
                timeout=10000,
            )

            confirm_button = page.get_by_role(
                "button",
                name="Xác nhận đặt hàng",
            )
            expect(confirm_button).to_be_visible(timeout=15000)
            expect(confirm_button).to_be_enabled()

            # 4. Xác nhận đơn hàng; COD là phương thức mặc định của trang.
            confirm_button.click()

            # 5. Kiểm tra trang kết quả và mã nhóm đơn hàng.
            expect(page).to_have_url(
                re.compile(r".*/checkout/payment/result$"),
                timeout=20000,
            )
            expect(
                page.get_by_role(
                    "heading",
                    name="Đặt hàng thành công!",
                )
            ).to_be_visible(timeout=10000)
            expect(
                page.get_by_text(re.compile(r"MN-\d+"))
            ).to_be_visible(timeout=10000)

            page.screenshot(
                path=str(SCREENSHOT_DIR / "checkout-success.png"),
                full_page=True,
            )
        finally:
            browser.close()
