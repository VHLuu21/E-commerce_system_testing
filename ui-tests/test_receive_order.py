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


def login_as_customer(page, email: str, password: str) -> None:
    """Log in through the real UI and verify the persisted Customer session."""

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
            path=str(SCREENSHOT_DIR / "receive-order-login-failed.png"),
            full_page=True,
        )
        pytest.fail(
            "Đăng nhập Customer thất bại: "
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
            path=str(SCREENSHOT_DIR / "receive-order-login-failed.png"),
            full_page=True,
        )
        pytest.fail(
            "Test xác nhận nhận hàng cần tài khoản CUSTOMER, "
            f"nhưng tài khoản hiện tại có role {role!r}."
        )


def test_customer_confirms_shipping_order_received():
    """Open a shipping order and confirm that the customer received it."""

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

            # 2. Mở lịch sử đơn hàng và lọc các đơn đang giao.
            with page.expect_response(
                lambda response: (
                    api_path(response) == "/orders"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as orders_response_info:
                page.goto(f"{BASE_URL}/orders", wait_until="domcontentloaded")

            assert_success(
                orders_response_info.value,
                "Tải lịch sử đơn hàng",
            )
            expect(
                page.get_by_role("heading", name="Đơn hàng của tôi")
            ).to_be_visible(timeout=15000)
            expect(page.locator(".order-history-loading")).to_be_hidden(
                timeout=15000
            )

            shipping_filter = page.locator(
                ".order-history-tabs button"
            ).filter(has_text="Đang giao").first
            if shipping_filter.count() == 0:
                pytest.skip(
                    "Tài khoản thử nghiệm chưa có lịch sử đơn hàng để lọc."
                )

            expect(shipping_filter).to_be_visible()
            shipping_filter.click()

            shipping_group = page.locator(
                "article.order-history-group:has("
                ".order-history-shop .order-status.is-shipping)"
            ).first
            if shipping_group.count() == 0:
                page.screenshot(
                    path=str(
                        SCREENSHOT_DIR / "receive-order-no-shipping-order.png"
                    ),
                    full_page=True,
                )
                pytest.skip(
                    "Tài khoản thử nghiệm hiện không có đơn SHIPPING "
                    "để xác nhận đã nhận hàng."
                )

            expect(shipping_group).to_be_visible(timeout=10000)

            group_identity = shipping_group.locator(
                ".order-history-group__identity strong"
            ).inner_text()
            group_id_match = re.search(r"#(\d+)", group_identity)
            assert group_id_match, (
                f"Không đọc được mã nhóm đơn từ UI: {group_identity!r}"
            )
            order_group_id = group_id_match.group(1)

            shipping_shop_order = shipping_group.locator(
                ".order-history-shop:has(.order-status.is-shipping)"
            ).first
            order_identity = shipping_shop_order.locator(
                ".order-history-shop__meta > div > span"
            ).inner_text()
            order_id_match = re.search(r"#(\d+)", order_identity)
            assert order_id_match, (
                f"Không đọc được mã đơn hàng từ UI: {order_identity!r}"
            )
            order_id = order_id_match.group(1)

            expect(
                shipping_shop_order.locator(".order-status")
            ).to_have_text("Đang giao hàng")

            page.screenshot(
                path=str(SCREENSHOT_DIR / "receive-order-shipping-list.png"),
                full_page=True,
            )

            # 3. Mở chi tiết nhóm chứa đúng đơn hàng đang giao.
            detail_link = shipping_group.get_by_role(
                "link",
                name="Xem chi tiết",
            )
            expect(detail_link).to_have_attribute(
                "href",
                f"/orders/{order_group_id}",
            )

            with page.expect_response(
                lambda response: (
                    api_path(response) == f"/orders/{order_group_id}"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as detail_response_info:
                detail_link.click()

            assert_success(
                detail_response_info.value,
                "Tải chi tiết nhóm đơn hàng",
            )
            expect(page).to_have_url(
                re.compile(rf".*/orders/{re.escape(order_group_id)}/?$"),
                timeout=10000,
            )
            expect(
                page.get_by_role("heading", name="Chi tiết đơn hàng")
            ).to_be_visible(timeout=15000)

            order_card = page.locator(f"#order-{order_id}")
            expect(order_card).to_be_visible(timeout=15000)
            order_status = order_card.locator(
                ".order-detail-card__meta .order-status"
            )
            expect(order_status).to_have_text("Đang giao hàng")

            # 4. Mở popup và xác nhận khách hàng đã nhận đúng đơn hàng.
            order_card.get_by_role(
                "button",
                name="Đã nhận được hàng",
                exact=True,
            ).click()

            receive_dialog = page.get_by_role("dialog")
            expect(receive_dialog).to_be_visible()
            expect(
                receive_dialog.get_by_role(
                    "heading",
                    name="Xác nhận đã nhận hàng?",
                )
            ).to_be_visible()
            expect(receive_dialog).to_contain_text(f"#{order_id}")

            # Sau PATCH, trang tự tải lại chi tiết nhóm đơn từ backend.
            with page.expect_response(
                lambda response: (
                    api_path(response) == f"/orders/{order_group_id}"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as refreshed_detail_info:
                with page.expect_response(
                    lambda response: (
                        api_path(response) == f"/orders/{order_id}/received"
                        and response.request.method == "PATCH"
                    ),
                    timeout=15000,
                ) as received_response_info:
                    receive_dialog.get_by_role(
                        "button",
                        name="Xác nhận đã nhận",
                        exact=True,
                    ).click()

            assert_success(
                received_response_info.value,
                "Xác nhận đã nhận hàng",
            )
            assert_success(
                refreshed_detail_info.value,
                "Tải lại trạng thái đơn hàng sau khi xác nhận",
            )

            # 5. Xác nhận trạng thái COMPLETED được hiển thị trên đúng đơn.
            expect(order_status).to_have_text("Hoàn thành", timeout=15000)
            expect(
                order_card.locator(".order-timeline")
            ).to_have_attribute("aria-label", "Trạng thái: Hoàn thành")
            expect(
                page.get_by_role("status").filter(
                    has_text=f"Đã xác nhận nhận đơn hàng #{order_id}."
                )
            ).to_be_visible(timeout=15000)
            expect(
                order_card.get_by_role(
                    "button",
                    name="Đã nhận được hàng",
                    exact=True,
                )
            ).to_have_count(0)

            page.screenshot(
                path=str(SCREENSHOT_DIR / "receive-order-completed.png"),
                full_page=True,
            )
        finally:
            browser.close()
