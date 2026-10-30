import os
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright


BASE_URL = "http://localhost:5173"
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


def api_path(response) -> str:
    """Return only the API path so backend host/port changes do not matter."""

    return urlparse(response.url).path.rstrip("/") or "/"


def assert_success(response, action: str) -> None:
    """Fail with the backend response body when an API action is unsuccessful."""

    if response.status not in (200, 201):
        pytest.fail(
            f"{action} thất bại: "
            f"HTTP {response.status} - {response.text()}"
        )


def login_as_seller(page, email: str, password: str) -> None:
    """Log in through the real UI and verify the persisted Seller session."""

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
            path=str(SCREENSHOT_DIR / "seller-order-login-failed.png"),
            full_page=True,
        )
        pytest.fail(
            "Đăng nhập Seller thất bại: "
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

    if role != "SELLER":
        page.screenshot(
            path=str(SCREENSHOT_DIR / "seller-order-login-failed.png"),
            full_page=True,
        )
        pytest.fail(
            "Test xử lý đơn hàng cần tài khoản SELLER, "
            f"nhưng tài khoản hiện tại có role {role!r}."
        )


def test_seller_confirms_and_starts_shipping_order():
    """Open a pending Seller order, confirm it, then start shipping it."""

    email = os.getenv("MARKETNEST_TEST_SELLER_EMAIL")
    password = os.getenv("MARKETNEST_TEST_SELLER_PASSWORD")

    if not email or not password:
        pytest.skip(
            "Chưa cấu hình MARKETNEST_TEST_SELLER_EMAIL và "
            "MARKETNEST_TEST_SELLER_PASSWORD."
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)

        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})

            # 1. Đăng nhập bằng tài khoản Seller thử nghiệm.
            login_as_seller(page, email, password)

            # 2. Mở danh sách đơn hàng thật của gian hàng.
            with page.expect_response(
                lambda response: (
                    api_path(response) == "/seller/orders"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as orders_response_info:
                page.goto(
                    f"{BASE_URL}/seller/orders",
                    wait_until="domcontentloaded",
                )

            assert_success(
                orders_response_info.value,
                "Tải danh sách đơn hàng Seller",
            )
            expect(
                page.get_by_role("heading", name="Quản lý đơn hàng")
            ).to_be_visible(timeout=15000)
            expect(page.locator(".seller-order-skeleton")).to_be_hidden(
                timeout=15000
            )

            # Chỉ chọn đơn PENDING vì backend bắt buộc đúng trình tự trạng thái.
            pending_filter = page.locator(
                ".seller-order-tabs button"
            ).filter(has_text="Chờ xác nhận").first
            expect(pending_filter).to_be_visible()
            pending_filter.click()

            pending_row = page.locator(
                ".seller-order-table tbody tr.is-pending"
            ).first
            if pending_row.count() == 0:
                page.screenshot(
                    path=str(
                        SCREENSHOT_DIR / "seller-order-no-pending-order.png"
                    ),
                    full_page=True,
                )
                pytest.skip(
                    "Gian hàng thử nghiệm hiện không có đơn PENDING để xác nhận."
                )

            expect(pending_row).to_be_visible(timeout=10000)
            order_identity = pending_row.locator(
                ".seller-order-identity strong"
            ).inner_text()
            order_id_match = re.search(r"#(\d+)", order_identity)
            assert order_id_match, (
                f"Không đọc được mã đơn hàng từ UI: {order_identity!r}"
            )
            order_id = order_id_match.group(1)

            page.screenshot(
                path=str(SCREENSHOT_DIR / "seller-order-list-pending.png"),
                full_page=True,
            )

            # 3. Mở chi tiết đúng đơn hàng đang chờ xác nhận.
            detail_link = pending_row.get_by_role(
                "link",
                name="Xem / Xử lý",
            )
            expect(detail_link).to_have_attribute(
                "href",
                f"/seller/orders/{order_id}",
            )

            with page.expect_response(
                lambda response: (
                    api_path(response) == f"/seller/orders/{order_id}"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as detail_response_info:
                detail_link.click()

            assert_success(
                detail_response_info.value,
                "Tải chi tiết đơn hàng Seller",
            )
            expect(page).to_have_url(
                re.compile(rf".*/seller/orders/{re.escape(order_id)}/?$"),
                timeout=10000,
            )
            expect(
                page.get_by_role("heading", name="Chi tiết đơn hàng")
            ).to_be_visible(timeout=15000)

            order_status = page.locator(
                ".seller-order-overview .seller-order-status"
            )
            expect(order_status).to_have_text("Chờ xác nhận")

            # 4. Xác nhận đơn qua popup của giao diện.
            actions_card = page.locator(".seller-order-actions-card")
            actions_card.get_by_role(
                "button",
                name="Xác nhận đơn",
                exact=True,
            ).click()

            confirm_dialog = page.get_by_role("dialog")
            expect(confirm_dialog).to_be_visible()
            expect(
                confirm_dialog.get_by_role(
                    "heading",
                    name="Xác nhận đơn hàng?",
                )
            ).to_be_visible()

            with page.expect_response(
                lambda response: (
                    api_path(response)
                    == f"/seller/orders/{order_id}/confirm"
                    and response.request.method == "PATCH"
                ),
                timeout=15000,
            ) as confirm_response_info:
                confirm_dialog.get_by_role(
                    "button",
                    name="Xác nhận đơn",
                    exact=True,
                ).click()

            assert_success(
                confirm_response_info.value,
                "Xác nhận đơn hàng",
            )
            expect(order_status).to_have_text("Đã xác nhận", timeout=15000)
            expect(
                page.get_by_role("status").filter(
                    has_text=f"Đã xác nhận đơn hàng #{order_id}."
                )
            ).to_be_visible(timeout=15000)

            # 5. Chuyển chính đơn đó từ CONFIRMED sang SHIPPING.
            start_shipping_button = actions_card.get_by_role(
                "button",
                name="Bắt đầu giao hàng",
                exact=True,
            )
            expect(start_shipping_button).to_be_visible(timeout=15000)
            start_shipping_button.click()

            shipping_dialog = page.get_by_role("dialog")
            expect(shipping_dialog).to_be_visible()
            expect(
                shipping_dialog.get_by_role(
                    "heading",
                    name="Bắt đầu giao hàng?",
                )
            ).to_be_visible()

            with page.expect_response(
                lambda response: (
                    api_path(response)
                    == f"/seller/orders/{order_id}/shipping"
                    and response.request.method == "PATCH"
                ),
                timeout=15000,
            ) as shipping_response_info:
                shipping_dialog.get_by_role(
                    "button",
                    name="Bắt đầu giao hàng",
                    exact=True,
                ).click()

            assert_success(
                shipping_response_info.value,
                "Cập nhật trạng thái giao hàng",
            )
            expect(order_status).to_have_text("Đang giao hàng", timeout=15000)
            expect(
                page.get_by_role("status").filter(
                    has_text=(
                        "Đơn hàng đã chuyển sang đang giao "
                        f"#{order_id}."
                    )
                )
            ).to_be_visible(timeout=15000)
            expect(
                actions_card.get_by_text(
                    "Đơn hàng đang được giao. "
                    "Chờ khách hàng xác nhận đã nhận hàng.",
                    exact=True,
                )
            ).to_be_visible()

            page.screenshot(
                path=str(SCREENSHOT_DIR / "seller-order-shipping.png"),
                full_page=True,
            )
        finally:
            browser.close()
