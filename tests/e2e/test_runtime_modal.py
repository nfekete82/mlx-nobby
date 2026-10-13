"""Systeminfo geometry and lifecycle through the production page in Chromium."""
import json

import pytest
from playwright.sync_api import expect


def open_systeminfo(page, collapsed=False):
    if collapsed:
        # The icon rail is a desktop control. Open there, then resize back to
        # mobile to verify that an already-open modal follows the viewport.
        viewport = page.viewport_size
        if viewport['width'] <= 900:
            page.set_viewport_size({'width': 1440, 'height': 1000})
        page.locator('#sidebarCollapseButton').click()
        launcher = page.locator('#railRuntimeInfo')
        launcher.click()
        page.set_viewport_size(viewport)
    elif page.viewport_size['width'] <= 900:
        page.locator('#sidebarToggle').click()
        launcher = page.locator('#runtimeInfoButton')
        launcher.locator('svg').click()
    else:
        launcher = page.locator('#runtimeInfoButton')
        launcher.locator('.sidebar-action-label').click()
    expect(page.locator('#runtimePopover')).to_be_visible()
    expect(page.locator('#runtimeInfoContent .runtime-info-model')).to_be_visible()
    return launcher


def assert_geometry(page):
    geometry = page.locator('#runtimePopover').evaluate("""dialog => {
        const r = dialog.getBoundingClientRect(), s = getComputedStyle(dialog);
        return {x: r.x, y: r.y, width: r.width, height: r.height,
                viewportWidth: innerWidth, viewportHeight: innerHeight,
                top: s.top, left: s.left, transform: s.transform, margin: s.margin};
    }""")
    print('Systeminfo computed layout:', json.dumps(geometry))
    assert abs(geometry['x']) <= 2 and abs(geometry['y']) <= 2, geometry
    assert abs(geometry['width'] - geometry['viewportWidth']) <= 2, geometry
    assert abs(geometry['height'] - geometry['viewportHeight']) <= 2, geometry
    close = page.locator('#runtimeModalClose').bounding_box()
    assert close and close['y'] >= 0
    assert close['y'] + close['height'] <= geometry['viewportHeight']


@pytest.mark.parametrize('collapsed', [False, True], ids=['sidebar-open', 'sidebar-collapsed'])
@pytest.mark.parametrize('chat_started', [False, True], ids=['empty-chat', 'active-chat'])
def test_runtime_modal_viewport_geometry(ui, collapsed, chat_started):
    page, agent, _allowed = ui
    if chat_started:
        page.locator('#input').fill('Hello')
        page.locator('#sendButton').click()
        expect(page.locator('.message.assistant')).to_contain_text(agent.answer)
    open_systeminfo(page, collapsed)
    assert_geometry(page)
    # Budget and reliability must share the scroll region with runtime data.
    for selector in ['#runtimeInfoContent', '#mlxRuntimeBudget', '#mlxRuntimeReliability']:
        expect(page.locator('.runtime-modal-body').locator(selector)).to_have_count(1)
    # Small phones and landscape windows, including live viewport changes.
    for width, height in [(320, 568), (844, 390), (1440, 320)]:
        page.set_viewport_size({'width': width, 'height': height})
        assert_geometry(page)
        body = page.locator('.runtime-modal-body')
        assert body.evaluate('(node) => node.scrollHeight > node.clientHeight')
        body.evaluate('(node) => node.scrollTop = node.scrollHeight')
        expect(page.locator('#mlxRuntimeReliability')).to_be_in_viewport()
        assert_geometry(page)


@pytest.mark.parametrize('dismiss', ['x', 'escape', 'native-close'])
def test_runtime_modal_dismiss_and_focus(ui, dismiss):
    page, _agent, _allowed = ui
    launcher = open_systeminfo(page, collapsed=page.viewport_size['width'] > 900)
    modal = page.locator('#runtimePopover')
    close = page.locator('#runtimeModalClose')
    expect(close).to_be_focused()
    page.keyboard.press('Shift+Tab')
    expect(page.locator('#runtimeInfoContent button')).to_be_focused()
    page.keyboard.press('Tab')
    expect(close).to_be_focused()
    # The dialog's own empty padding is inside; it is not the backdrop.
    box = modal.bounding_box()
    page.mouse.click(box['x'] + 4, box['y'] + 4)
    expect(modal).to_be_visible()
    # A drag from dialog content ending on the backdrop must not dismiss it.
    page.mouse.move(box['x'] + 4, box['y'] + 4)
    page.mouse.down()
    page.mouse.move(2, 2)
    page.mouse.up()
    expect(modal).to_be_visible()
    if dismiss == 'x':
        close.click()
    elif dismiss == 'escape':
        page.keyboard.press('Escape')
    else:
        modal.evaluate('(node) => node.close()')
    expect(modal).to_be_hidden()
    expect(launcher).to_be_focused()
    expect(page.locator('#runtimeInfoButton')).to_have_attribute('aria-expanded', 'false')
    launcher.click()
    expect(modal).to_be_visible()
    expect(close).to_be_focused()
    assert_geometry(page)
    page.keyboard.press('Escape')
    expect(modal).to_be_hidden()


def test_runtime_modal_live_information_and_focus(ui):
    page, agent, _allowed = ui
    # Use the real session metrics contract without issuing an inference call.
    page.evaluate("""() => MLXChatSessions.currentSession().messages.push({
        role: 'assistant', content: 'Measured response', metrics: {
            total_ms: 2500, first_content_ms: 250, thinking_ms: 500,
            estimated_tokens: 42, tokens_per_second: 16.8
        }
    })""")
    open_systeminfo(page)
    content = page.locator('#runtimeInfoContent')
    expect(content).to_contain_text('fixture/Qwen-4-bit')
    for label in ['Thinking', 'RAM', 'PID', 'Port', 'Uptime', 'Tokens', 'Tokens/s', 'First token', 'Gesamt']:
        expect(content).to_contain_text(label)
    expect(content).to_contain_text('1234')
    expect(content).to_contain_text('42')
    thinking = content.locator('button')
    thinking.focus()
    agent.model_pid = 5678
    expect(content).to_contain_text('5678', timeout=8000)
    expect(thinking).to_be_focused()
    assert_geometry(page)
    page.keyboard.press('Escape')
    expect(page.locator('#runtimePopover')).to_be_hidden()
    # No runtime/system polling while closed (budget uses the same endpoint).
    before = agent.count('/api/system')
    page.wait_for_timeout(3500)
    assert agent.count('/api/system') == before


def test_runtime_modal_unavailable_api_stays_usable(ui):
    page, _agent, _allowed = ui
    page.route('**/api/mlx/status', lambda route: route.fulfill(
        status=200, content_type='application/json', body='invalid json'))
    if page.viewport_size['width'] <= 900:
        page.locator('#sidebarToggle').click()
    page.locator('#runtimeInfoButton').click()
    expect(page.locator('#runtimeInfoContent')).to_contain_text('unavailable')
    assert_geometry(page)
    page.keyboard.press('Escape')
    expect(page.locator('#runtimePopover')).to_be_hidden()


def test_workspace_panels_fill_viewport_and_close(ui):
    """Settings and Help keep controls accessible at desktop and mobile sizes."""
    page, _agent, _allowed = ui

    page.wait_for_function('Boolean(window.MLXChatSettings) && Boolean(window.MLXSettingsLayout)')
    page.evaluate("window.MLXChatSettings.open('general')")
    settings = page.locator('#settings')
    expect(settings).to_be_visible()
    expect(settings).to_have_class(__import__('re').compile(r'.*settings-organized.*'))
    for selector in ['#settings', '#settings .settings-organizer-main']:
        expect(page.locator(selector)).to_be_visible()
    dimensions = settings.evaluate("""element => {
        const r = element.getBoundingClientRect();
        return {x:r.x,y:r.y,w:r.width,h:r.height,
                vw:innerWidth,vh:innerHeight};
    }""")
    assert abs(dimensions['x']) <= 2 and abs(dimensions['y']) <= 2, dimensions
    assert abs(dimensions['w'] - dimensions['vw']) <= 2, dimensions
    assert abs(dimensions['h'] - dimensions['vh']) <= 2, dimensions
    expect(page.locator('#settingsClose')).to_be_in_viewport()
    page.locator('#settingsClose').click()
    expect(settings).to_be_hidden()

    page.wait_for_function('Boolean(window.MLXHelp)')
    page.evaluate('window.MLXHelp.open()')
    help_panel = page.locator('#mlxHelpPanel')
    expect(help_panel).to_be_visible()
    bounds = help_panel.evaluate("""element => {
        const r = element.getBoundingClientRect();
        return {x:r.x,y:r.y,w:r.width,h:r.height,
                vw:innerWidth,vh:innerHeight};
    }""")
    assert abs(bounds['x']) <= 2 and abs(bounds['y']) <= 2, bounds
    assert abs(bounds['w'] - bounds['vw']) <= 2, bounds
    assert abs(bounds['h'] - bounds['vh']) <= 2, bounds
    search = page.locator('#mlxHelpSearch')
    expect(search).to_be_visible()
    assert search.evaluate('(node) => getComputedStyle(node).height') != '0px'
    expect(page.locator('#mlxHelpClose')).to_be_in_viewport()
    # Sidebar and help content must scroll independently without overflowing.
    assert page.locator('#mlxHelpContent').evaluate(
        '(node) => ["auto", "scroll"].includes(getComputedStyle(node).overflowY)')
    page.locator('#mlxHelpClose').click()
    expect(help_panel).to_be_hidden()
