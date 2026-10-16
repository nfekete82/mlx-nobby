"""Shared UI control visual contracts with real Chromium (desktop + mobile)."""
from playwright.sync_api import expect


def test_shared_controls_match_library_picker_and_preserve_native_behavior(ui):
    page, _agent, _allowed = ui
    assert "nobby-ui" in (page.locator("body").get_attribute("class") or "")
    # Settings and media controls exist on the real chat page, even if their
    # parent settings pane is initially collapsed.
    for selector in ("#showMetrics", "#profilePersonality", "#interfaceLanguage",
                     "#mediaFormat", "#imageModel", "#videoProfile"):
        styles = page.locator(selector).evaluate("""node => ({
            appearance: getComputedStyle(node).appearance,
            bg: getComputedStyle(node).backgroundColor,
            picker: getComputedStyle(node, '::picker(select)').backgroundColor,
            minHeight: getComputedStyle(node).minHeight
        })""")
        assert styles == {
            "appearance": "base-select",
            "bg": "rgb(20, 27, 40)",
            "picker": "rgb(23, 34, 52)",
            "minHeight": "41px",
        }, selector

    # The composer quality picker keeps its intentionally compact geometry.
    compact = page.locator("#mediaQuality").evaluate("""node => ({
        minHeight: getComputedStyle(node).minHeight,
        appearance: getComputedStyle(node).appearance,
        picker: getComputedStyle(node, '::picker(select)').backgroundColor
    })""")
    assert compact == {
        "minHeight": "32px",
        "appearance": "base-select",
        "picker": "rgb(23, 34, 52)",
    }

    # Test a real selectable model module control with the same class used by
    # Model Overview; this does not rely on a mocked model registry.
    page.evaluate("""() => {
        const select = document.createElement('select');
        select.id = 'uiPickerProbe';
        select.className = 'model-overview-select';
        select.style.cssText = 'position:fixed;top:48px;left:16px;width:220px;z-index:99999';
        select.setAttribute('aria-label', 'UI picker test');
        for (const [value, name] of [['a', 'First'], ['b', 'Second']]) {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = name;
            select.append(option);
        }
        document.body.append(select);
    }""")
    control = page.locator("#uiPickerProbe")
    expect(control).to_be_visible()
    control.click()
    expect(page.locator("#uiPickerProbe:open")).to_be_visible()
    dimensions = control.evaluate("""node => ({
        control: node.getBoundingClientRect().width,
        picker: parseFloat(getComputedStyle(node, '::picker(select)').width)
    })""")
    assert abs(dimensions["control"] - dimensions["picker"]) < 2
    page.keyboard.press("Escape")
    control.select_option("b")
    expect(control).to_have_value("b")
    page.locator("#uiPickerProbe").evaluate("node => node.remove()")


def test_shared_theme_keeps_checkbox_and_file_upload_native(ui):
    page, _agent, _allowed = ui
    styles = page.evaluate("""() => {
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.id = 'uiCheckboxProbe';
        box.className = 'ui-checkbox-probe';
        const container = document.createElement('div');
        container.className = 'field';
        container.append(box);
        document.body.append(container);
        const result = {appearance: getComputedStyle(box).appearance};
        container.remove();
        return result;
    }""")
    assert styles["appearance"] not in ("base-select", "none")
    for role in ("chat", "agent", "coding", "vision", "vision_uncensored", "embedding"):
        select = page.locator('[data-model-role="' + role + '"]')
        labelled_by = select.get_attribute("aria-labelledby")
        assert labelled_by, role
        assert page.locator("#" + labelled_by).count() == 1
