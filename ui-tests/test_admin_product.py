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


def login_as_admin(page, email: str, password: str) -> None:
    """Log in through the real UI and verify the persisted Admin session."""

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
            path=str(SCREENSHOT_DIR / "admin-product-login-failed.png"),
            full_page=True,
        )
        pytest.fail(
            "Đăng nhập Admin thất bại: "
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

    if role != "ADMIN":
        page.screenshot(
            path=str(SCREENSHOT_DIR / "admin-product-login-failed.png"),
            full_page=True,
        )
        pytest.fail(
            "Test duyệt sản phẩm cần tài khoản ADMIN, "
            f"nhưng tài khoản hiện tại có role {role!r}."
        )


def test_admin_approves_pending_product():
    """Open a pending product, approve it, and verify its persisted status."""

    email = os.getenv("MARKETNEST_TEST_ADMIN_EMAIL")
    password = os.getenv("MARKETNEST_TEST_ADMIN_PASSWORD")

    if not email or not password:
        pytest.skip(
            "Chưa cấu hình MARKETNEST_TEST_ADMIN_EMAIL và "
            "MARKETNEST_TEST_ADMIN_PASSWORD."
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)

        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})

            # 1. Đăng nhập bằng tài khoản Admin thử nghiệm.
            login_as_admin(page, email, password)

            # 2. Mở danh sách sản phẩm Admin.
            with page.expect_response(
                lambda response: (
                    api_path(response) == "/admin/products"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as products_response_info:
                page.goto(
                    f"{BASE_URL}/admin/products",
                    wait_until="domcontentloaded",
                )

            assert_success(
                products_response_info.value,
                "Tải danh sách sản phẩm Admin",
            )
            expect(
                page.get_by_role("heading", name="Quản lý sản phẩm")
            ).to_be_visible(timeout=15000)
            expect(page.locator(".admin-product-skeleton")).to_be_hidden(
                timeout=15000
            )

            # 3. Lọc đúng các sản phẩm đang chờ duyệt.
            status_filter = page.locator(
                ".admin-product-toolbar label"
            ).filter(has_text="Trạng thái").locator("select")
            expect(status_filter).to_have_count(1)
            with page.expect_response(
                lambda response: (
                    api_path(response) == "/admin/products"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as pending_response_info:
                status_filter.select_option("PENDING")

            assert_success(
                pending_response_info.value,
                "Lọc sản phẩm chờ duyệt",
            )
            expect(page.locator(".admin-product-skeleton")).to_be_hidden(
                timeout=15000
            )
            expect(status_filter).to_have_value("PENDING")

            pending_row = page.locator(
                ".admin-product-table tbody tr:has("
                ".admin-product-status.is-pending)"
            ).first
            if pending_row.count() == 0:
                page.screenshot(
                    path=str(
                        SCREENSHOT_DIR / "admin-product-no-pending-item.png"
                    ),
                    full_page=True,
                )
                pytest.skip(
                    "Hệ thống hiện không có sản phẩm PENDING để Admin duyệt."
                )

            expect(pending_row).to_be_visible(timeout=10000)
            expect(
                pending_row.locator(".admin-product-status")
            ).to_have_text("Chờ duyệt")

            product_id_text = pending_row.locator(
                ".admin-product-identity small"
            ).inner_text()
            product_id_match = re.search(r"#(\d+)", product_id_text)
            assert product_id_match, (
                f"Không đọc được mã sản phẩm từ UI: {product_id_text!r}"
            )
            product_id = product_id_match.group(1)
            product_name = pending_row.locator(
                ".admin-product-identity strong"
            ).inner_text().strip()

            page.screenshot(
                path=str(SCREENSHOT_DIR / "admin-product-pending-list.png"),
                full_page=True,
            )

            # 4. Mở trang chi tiết của đúng sản phẩm đã chọn.
            detail_link = pending_row.get_by_role(
                "link",
                name="Xem chi tiết →",
            )
            expect(detail_link).to_have_attribute(
                "href",
                f"/admin/products/{product_id}",
            )

            with page.expect_response(
                lambda response: (
                    api_path(response) == f"/admin/products/{product_id}"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as detail_response_info:
                detail_link.click()

            assert_success(
                detail_response_info.value,
                "Tải chi tiết sản phẩm Admin",
            )
            expect(page).to_have_url(
                re.compile(rf".*/admin/products/{re.escape(product_id)}/?$"),
                timeout=10000,
            )
            expect(
                page.get_by_role("heading", name=product_name, exact=True)
            ).to_be_visible(timeout=15000)

            hero = page.locator(".admin-product-review-hero")
            product_status = hero.locator(".admin-product-status")
            expect(product_status).to_have_text("Chờ duyệt")

            # 5. Duyệt sản phẩm qua popup xác nhận của giao diện.
            hero.get_by_role(
                "button",
                name="Duyệt sản phẩm",
                exact=True,
            ).click()

            approve_dialog = page.get_by_role("dialog")
            expect(approve_dialog).to_be_visible()
            expect(
                approve_dialog.get_by_role(
                    "heading",
                    name="Duyệt sản phẩm?",
                )
            ).to_be_visible()

            # Trang tự GET lại chi tiết sau PATCH; chờ cả hai phản hồi để xác
            # nhận trạng thái mới thực sự được backend lưu và trả về.
            with page.expect_response(
                lambda response: (
                    api_path(response) == f"/admin/products/{product_id}"
                    and response.request.method == "GET"
                ),
                timeout=15000,
            ) as refreshed_detail_info:
                with page.expect_response(
                    lambda response: (
                        api_path(response)
                        == f"/admin/products/{product_id}/approve"
                        and response.request.method == "PATCH"
                    ),
                    timeout=15000,
                ) as approve_response_info:
                    approve_dialog.get_by_role(
                        "button",
                        name="Duyệt sản phẩm",
                        exact=True,
                    ).click()

            assert_success(
                approve_response_info.value,
                "Duyệt sản phẩm",
            )
            assert_success(
                refreshed_detail_info.value,
                "Tải lại trạng thái sản phẩm sau khi duyệt",
            )

            # 6. Xác nhận UI đã nhận trạng thái APPROVED mới từ backend.
            expect(product_status).to_have_text("Đã duyệt", timeout=15000)
            expect(
                page.get_by_role("status").filter(
                    has_text="Đã duyệt sản phẩm."
                )
            ).to_be_visible(timeout=15000)
            expect(
                hero.get_by_role(
                    "button",
                    name="Duyệt sản phẩm",
                    exact=True,
                )
            ).to_have_count(0)

            page.screenshot(
                path=str(SCREENSHOT_DIR / "admin-product-approved.png"),
                full_page=True,
            )
        finally:
            browser.close()
