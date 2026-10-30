import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright


BASE_URL = "http://localhost:5173"
PRODUCT_ID = os.getenv("MARKETNEST_TEST_PRODUCT_ID", "80")
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


def api_path(response) -> str:
    """Return only the API path so backend host/port changes do not matter."""

    return urlparse(response.url).path.rstrip("/") or "/"


def login_as_customer(page, email: str, password: str) -> None:
    """Log in through the UI and verify that a Customer session was stored."""

    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    expect(
        page.get_by_role("heading", name="Đăng nhập tài khoản")
    ).to_be_visible(timeout=10000)
    page.get_by_label("Email").fill(email)
    page.locator("#password").fill(password)

    with page.expect_response(
        lambda response: (
            api_path(response) == "/auth/login"
            and response.request.method == "POST"
        ),
        timeout=15000,
    ) as login_response_info:
        page.get_by_role("button", name="Đăng nhập ngay").click()

    login_response = login_response_info.value
    if login_response.status not in (200, 201):
        page.screenshot(
            path=str(SCREENSHOT_DIR / "wishlist-login-failed.png"),
            full_page=True,
        )
        pytest.fail(
            "Đăng nhập thất bại: "
            f"HTTP {login_response.status} - {login_response.text()}"
        )

    page.wait_for_function(
        """
        () => Boolean(
          window.localStorage.getItem('marketplace.auth.accessToken')
          && window.localStorage.getItem('marketplace.auth.user')
        )
        """,
        timeout=10000,
    )
    role = page.evaluate(
        """
        () => JSON.parse(
          window.localStorage.getItem('marketplace.auth.user')
        ).role
        """
    )

    if role != "CUSTOMER":
        page.screenshot(
            path=str(SCREENSHOT_DIR / "wishlist-login-failed.png"),
            full_page=True,
        )
        pytest.fail(
            "Test danh sách yêu thích cần tài khoản CUSTOMER, "
            f"nhưng tài khoản hiện tại có role {role!r}."
        )


def assert_success(response, action: str) -> None:
    """Fail with the backend response body when an API action is unsuccessful."""

    if response.status not in (200, 201):
        pytest.fail(
            f"{action} thất bại: "
            f"HTTP {response.status} - {response.text()}"
        )


def test_manage_wishlist():
    """Add a product to wishlist, verify it in the list, then remove it."""

    email = os.getenv("MARKETNEST_TEST_EMAIL")
    password = os.getenv("MARKETNEST_TEST_PASSWORD")

    if not email or not password:
        pytest.skip(
            "Chưa cấu hình MARKETNEST_TEST_EMAIL và "
            "MARKETNEST_TEST_PASSWORD."
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)

        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})

            # 1. Đăng nhập bằng tài khoản Customer thử nghiệm.
            login_as_customer(page, email, password)

            # 2. Mở một sản phẩm thật và chờ trạng thái yêu thích được tải.
            with page.expect_response(
                lambda response: (
                    api_path(response) == f"/products/{PRODUCT_ID}"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as product_response_info:
                page.goto(
                    f"{BASE_URL}/products/{PRODUCT_ID}",
                    wait_until="domcontentloaded",
                )

            product_response = product_response_info.value
            assert product_response.status == 200, (
                "Không thể tải sản phẩm dùng cho kiểm thử: "
                f"HTTP {product_response.status} - {product_response.text()}"
            )

            product_title = page.locator("#product-title")
            expect(product_title).to_be_visible(timeout=15000)
            product_name = product_title.inner_text().strip()

            wishlist_button = page.locator("button.wishlist-button")
            expect(wishlist_button).to_be_visible(timeout=15000)
            expect(wishlist_button).to_be_enabled(timeout=15000)

            # Đưa dữ liệu về trạng thái chưa yêu thích để test chạy lại ổn định.
            if wishlist_button.get_attribute("aria-pressed") == "true":
                with page.expect_response(
                    lambda response: (
                        api_path(response) == f"/wishlist/{PRODUCT_ID}"
                        and response.request.method == "DELETE"
                    ),
                    timeout=15000,
                ) as reset_response_info:
                    wishlist_button.click()

                assert_success(
                    reset_response_info.value,
                    "Xóa trạng thái yêu thích có sẵn",
                )
                expect(wishlist_button).to_have_attribute(
                    "aria-pressed",
                    "false",
                    timeout=10000,
                )
                expect(wishlist_button).to_contain_text("Yêu thích")

            # 3. Thêm sản phẩm vào danh sách yêu thích từ trang chi tiết.
            with page.expect_response(
                lambda response: (
                    api_path(response) == f"/wishlist/{PRODUCT_ID}"
                    and response.request.method == "POST"
                ),
                timeout=15000,
            ) as add_response_info:
                wishlist_button.click()

            assert_success(
                add_response_info.value,
                "Thêm sản phẩm vào danh sách yêu thích",
            )
            expect(wishlist_button).to_have_attribute(
                "aria-pressed",
                "true",
                timeout=10000,
            )
            expect(wishlist_button).to_contain_text("Đã yêu thích")
            expect(
                page.get_by_text(
                    "Đã thêm sản phẩm vào danh sách yêu thích",
                    exact=True,
                )
            ).to_be_visible()

            # 4. Mở trang yêu thích và xác nhận đúng sản phẩm vừa thêm.
            with page.expect_response(
                lambda response: (
                    api_path(response) == "/wishlist"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as wishlist_response_info:
                page.goto(f"{BASE_URL}/wishlist", wait_until="domcontentloaded")

            assert_success(
                wishlist_response_info.value,
                "Tải danh sách yêu thích",
            )
            expect(
                page.get_by_role("heading", name="Sản phẩm yêu thích")
            ).to_be_visible(timeout=15000)
            expect(page.locator(".wishlist-loading")).to_be_hidden(timeout=15000)

            wishlist_card = page.locator(
                "article.wishlist-card"
                f':has(a[href="/products/{PRODUCT_ID}"])'
            )
            expect(wishlist_card).to_have_count(1, timeout=15000)
            expect(wishlist_card).to_be_visible()
            expect(wishlist_card).to_contain_text(product_name)

            page.screenshot(
                path=str(SCREENSHOT_DIR / "wishlist-product-added.png"),
                full_page=True,
            )

            # 5. Bỏ yêu thích ngay trên danh sách và xác nhận card biến mất.
            remove_button = wishlist_card.locator(".wishlist-card__remove")
            expect(remove_button).to_be_enabled()

            with page.expect_response(
                lambda response: (
                    api_path(response) == f"/wishlist/{PRODUCT_ID}"
                    and response.request.method == "DELETE"
                ),
                timeout=15000,
            ) as remove_response_info:
                remove_button.click()

            assert_success(
                remove_response_info.value,
                "Xóa sản phẩm khỏi danh sách yêu thích",
            )
            expect(wishlist_card).to_have_count(0, timeout=10000)

            page.screenshot(
                path=str(SCREENSHOT_DIR / "wishlist-product-removed.png"),
                full_page=True,
            )
        finally:
            browser.close()
