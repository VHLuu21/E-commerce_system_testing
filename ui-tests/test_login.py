
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect


BASE_URL = "http://localhost:5173"
LOGIN_URL = f"{BASE_URL}/login"
SCREENSHOTS = Path("screenshots")


def test_login_invalid_credentials():
    """Thông tin đăng nhập sai phải bị từ chối."""

    SCREENSHOTS.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        try:
            page = browser.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")

            page.get_by_label("Email").fill("wrong-user@example.com")
            page.locator("#password").fill("WrongPassword123!")
            page.get_by_role(
                "button", name="Đăng nhập ngay"
            ).click()

            # Không được chuyển khỏi trang đăng nhập
            expect(page).to_have_url(
                re.compile(r".*/login/?$"),
                timeout=10000,
            )

            # Phải hiển thị thông báo lỗi
            error_message = page.get_by_text(
                re.compile(
                    r"sai|không đúng|không chính xác|"
                    r"không hợp lệ|thất bại|invalid|incorrect|failed",
                    re.IGNORECASE,
                )
            )
            expect(error_message).to_be_visible(timeout=5000)

            page.screenshot(
                path=str(SCREENSHOTS / "login-invalid.png"),
                full_page=True,
            )

        finally:
            browser.close()


def test_login_valid_credentials():
    """Tài khoản hợp lệ phải đăng nhập thành công."""

    email = os.getenv("MARKETNEST_TEST_EMAIL")
    password = os.getenv("MARKETNEST_TEST_PASSWORD")

    if not email or not password:
        pytest.skip(
            "Chưa cấu hình MARKETNEST_TEST_EMAIL và "
            "MARKETNEST_TEST_PASSWORD"
        )

    SCREENSHOTS.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        try:
            page = browser.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")

            page.get_by_label("Email").fill(email)
            page.locator("#password").fill(password)
            page.get_by_role(
                "button", name="Đăng nhập ngay"
            ).click()

            # Chờ ứng dụng rời khỏi trang đăng nhập
            expect(page).not_to_have_url(
                re.compile(r".*/login/?$"),
                timeout=10000,
            )

            page.screenshot(
                path=str(SCREENSHOTS / "login-success.png"),
                full_page=True,
            )

        finally:
            browser.close()
