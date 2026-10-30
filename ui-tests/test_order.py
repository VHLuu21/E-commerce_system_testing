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
    """Return only the URL path so frontend and backend hosts do not matter."""

    return urlparse(response.url).path.rstrip("/") or "/"


def money_digits(value: str) -> str:
    """Keep only digits so differently spaced VND strings can be compared."""

    return re.sub(r"\D", "", value)


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
        page.get_by_role(
            "button",
            name="Đăng nhập ngay",
        ).click()

    login_response = login_response_info.value

    if login_response.status not in (200, 201):
        page.screenshot(
            path=str(SCREENSHOT_DIR / "order-login-failed.png"),
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
            path=str(SCREENSHOT_DIR / "order-login-failed.png"),
            full_page=True,
        )
        pytest.fail(
            "Test lịch sử đơn hàng cần tài khoản CUSTOMER, "
            f"nhưng tài khoản hiện tại có role {role!r}."
        )


def test_view_order_detail():
    """Open an existing order group and verify its main order information."""

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

            # 2. Mở lịch sử và chọn một nhóm đơn thật có sản phẩm.
            with page.expect_response(
                lambda response: (
                    api_path(response) == "/orders"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as orders_response_info:
                page.goto(f"{BASE_URL}/orders", wait_until="domcontentloaded")

            orders_response = orders_response_info.value
            assert orders_response.status == 200, (
                "Không thể tải lịch sử đơn hàng: "
                f"HTTP {orders_response.status} - {orders_response.text()}"
            )

            expect(
                page.get_by_role(
                    "heading",
                    name="Đơn hàng của tôi",
                )
            ).to_be_visible(timeout=15000)
            expect(
                page.locator(".order-history-loading")
            ).to_be_hidden(timeout=15000)

            order_group_card = page.locator(
                ".order-history-group:has(.order-history-product)"
            ).first

            if order_group_card.count() == 0:
                pytest.skip(
                    "Tài khoản thử nghiệm chưa có nhóm đơn hàng chứa sản phẩm."
                )

            expect(order_group_card).to_be_visible(timeout=15000)

            detail_link = order_group_card.get_by_role(
                "link",
                name="Xem chi tiết",
            )
            detail_href = detail_link.get_attribute("href") or ""
            group_id_match = re.fullmatch(r"/orders/(\d+)", detail_href)
            assert group_id_match, (
                f"Route chi tiết nhóm đơn không hợp lệ: {detail_href!r}"
            )
            order_group_id = group_id_match.group(1)

            history_order = order_group_card.locator(
                ".order-history-shop:has(.order-history-product)"
            ).first
            order_meta_text = history_order.locator(
                ".order-history-shop__meta"
            ).inner_text()
            order_id_match = re.search(r"Đơn hàng #(\d+)", order_meta_text)
            assert order_id_match, (
                f"Không đọc được mã đơn từ UI: {order_meta_text!r}"
            )
            order_id = order_id_match.group(1)

            history_product = history_order.locator(
                ".order-history-product"
            ).first
            product_name = history_product.locator(
                ".order-history-product__copy > a"
            ).inner_text().strip()
            quantity_text = history_product.locator(
                ".order-history-product__copy > span"
            ).inner_text()
            quantity_match = re.search(r"×\s*(\d+)", quantity_text)
            assert quantity_match, (
                f"Không đọc được số lượng sản phẩm từ UI: {quantity_text!r}"
            )
            product_quantity = quantity_match.group(1)
            expected_order_total = history_order.locator(
                ".order-history-shop__total strong"
            ).inner_text()
            expected_group_total = order_group_card.locator(
                ".order-history-group__total strong"
            ).inner_text()

            # 3. Bấm đúng nút Xem chi tiết của nhóm đơn đã chọn.
            with page.expect_response(
                lambda response: (
                    api_path(response) == f"/orders/{order_group_id}"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as detail_response_info:
                detail_link.click()

            detail_response = detail_response_info.value
            assert detail_response.status == 200, (
                "Không thể tải chi tiết đơn hàng: "
                f"HTTP {detail_response.status} - {detail_response.text()}"
            )

            expect(page).to_have_url(
                re.compile(rf".*/orders/{re.escape(order_group_id)}/?$"),
                timeout=10000,
            )
            expect(
                page.get_by_role(
                    "heading",
                    name="Chi tiết đơn hàng",
                )
            ).to_be_visible(timeout=15000)
            expect(
                page.get_by_text(
                    f"Nhóm đơn hàng #{order_group_id}",
                    exact=True,
                )
            ).to_be_visible()

            # 4. Đối chiếu mã đơn, sản phẩm, số lượng và tổng tiền.
            order_card = page.locator(f"#order-{order_id}")

            expect(order_card).to_be_visible()
            expect(order_card).to_contain_text(f"Đơn hàng #{order_id}")

            product_row = order_card.locator(".order-detail-product").filter(
                has_text=product_name
            ).first
            expect(product_row).to_be_visible()
            expect(
                product_row.get_by_role(
                    "link",
                    name=product_name,
                    exact=True,
                )
            ).to_be_visible()
            expect(
                product_row.locator(".order-detail-product__content small")
            ).to_contain_text(f"× {product_quantity}")

            order_total_text = order_card.locator(
                ".order-totals dd"
            ).last.inner_text()
            assert money_digits(order_total_text) == money_digits(
                expected_order_total
            ), (
                "Tổng tiền đơn hàng không khớp giữa danh sách và chi tiết: "
                f"list={expected_order_total!r}, detail={order_total_text!r}"
            )

            group_total_text = page.locator(
                ".order-detail-summary__total > div strong"
            ).inner_text()
            assert money_digits(group_total_text) == money_digits(
                expected_group_total
            ), (
                "Tổng nhóm đơn không khớp giữa danh sách và chi tiết: "
                f"list={expected_group_total!r}, detail={group_total_text!r}"
            )

            page.screenshot(
                path=str(SCREENSHOT_DIR / "order-detail.png"),
                full_page=True,
            )
        finally:
            browser.close()
