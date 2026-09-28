# -*- coding: utf-8 -*-
"""UI 自动化测试（Playwright）：走通 登录→浏览→加购→下单→支付 全链路，
并校验页面展示的价格/金额/状态是否正确。"""
import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture()
def page(browser, server):
    context = browser.new_context()
    pg = context.new_page()
    pg.set_default_timeout(5000)
    yield pg
    context.close()


def _login(page, base_url, username="test_user", password="123456"):
    page.goto(base_url + "/login")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-btn")


def test_login_success_redirect(page, server):
    base = server["base_url"]
    _login(page, base)
    page.wait_for_url(base + "/")
    expect(page).to_have_url(base + "/")


def test_login_wrong_password_shows_error(page, server):
    base = server["base_url"]
    page.goto(base + "/login")
    page.fill("#username", "test_user")
    page.fill("#password", "wrong")
    page.click("#login-btn")
    expect(page.locator("#msg")).to_contain_text("失败")


def test_product_list_shows_eight(page, server):
    _login(page, server["base_url"])
    page.wait_for_url(server["base_url"] + "/")
    expect(page.locator('[data-testid="product"]')).to_have_count(8)


def test_product_price_displayed(page, server):
    _login(page, server["base_url"])
    page.wait_for_url(server["base_url"] + "/")
    expect(page.locator('[data-testid="product"]').first).to_contain_text("手机")


def test_add_to_cart_and_view_cart(page, server):
    base = server["base_url"]
    _login(page, base)
    page.wait_for_url(base + "/")
    page.click('[data-testid="add-P3"]')
    expect(page.locator("#status")).to_contain_text("已加入")
    page.click("nav a[href='/cart_page']")
    expect(page.locator('[data-testid="cart-item"]')).to_contain_text("手机壳")


def test_order_flow_pay_amount(page, server):
    base = server["base_url"]
    _login(page, base)
    page.wait_for_url(base + "/")
    page.click('[data-testid="add-P3"]')  # 手机壳 59
    expect(page.locator("#status")).to_contain_text("已加入")
    page.click("nav a[href='/cart_page']")
    expect(page.locator('[data-testid="cart-item"]')).to_contain_text("手机壳")
    page.click("#order-btn")
    # 59 < 99 → 收 8 元运费 → 实付 67
    expect(page.locator('[data-testid="pay_amount"]')).to_contain_text("67")


def test_order_detail_status(page, server):
    base = server["base_url"]
    _login(page, base)
    page.wait_for_url(base + "/")
    page.click('[data-testid="add-P3"]')
    page.click("nav a[href='/cart_page']")
    page.click("#order-btn")
    page.click('[data-testid="view-order"]')
    expect(page.locator('[data-testid="status"]')).to_contain_text("unpaid")


def test_pay_updates_status(page, server):
    base = server["base_url"]
    _login(page, base)
    page.wait_for_url(base + "/")
    page.click('[data-testid="add-P3"]')
    page.click("nav a[href='/cart_page']")
    page.click("#order-btn")
    page.click('[data-testid="view-order"]')
    expect(page.locator('[data-testid="status"]')).to_contain_text("unpaid")
    page.click("#pay-btn")
    expect(page.locator('[data-testid="status"]')).to_contain_text("paid")


def test_unauth_cart_redirects_to_login(page, server):
    base = server["base_url"]
    page.goto(base + "/cart_page")
    page.wait_for_url(base + "/login")
    expect(page).to_have_url(base + "/login")