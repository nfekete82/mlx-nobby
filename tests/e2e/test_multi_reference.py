"""Real desktop/mobile composer; inference transport is controlled."""
from playwright.sync_api import expect
from .harness import image_fixture


def test_multiple_references_reorder_remove_and_edit_options(ui):
    page, agent, _ = ui
    files = [{'name': f'person-{index}.png', 'mimeType': 'image/png', 'buffer': image_fixture()} for index in range(10)]
    page.locator('#fileInput').set_input_files(files)
    expect(page.locator('#attachmentBar .image-attachment-chip')).to_have_count(10)
    page.locator('#attachmentBar .image-attachment-chip').first.focus()
    page.keyboard.press('Alt+ArrowRight')
    expect(page.locator('#attachmentBar .attachment-name').first).to_contain_text('person-1.png')
    page.locator('#attachmentBar .attachment-remove').last.click()
    expect(page.locator('#attachmentBar .image-attachment-chip')).to_have_count(9)
    # Analysis must remain the first-class, compact option. Editing controls
    # are hidden until explicitly requested, on desktop and mobile.
    mode = page.locator('.image-attachment-mode-select')
    expect(mode).to_have_value('auto')
    expect(page.locator('.image-edit-options')).to_have_count(0)
    mode.select_option('describe')
    expect(mode).to_have_value('describe')
    expect(page.locator('.image-edit-options')).to_have_count(0)
    mode.select_option('edit')
    expect(page.locator('.image-edit-model-field select')).to_have_value('auto')
    assert page.locator('.image-edit-options input[type=number]').count() == 0
    assert page.locator('.image-edit-advanced').evaluate('(el) => el.open') is False
    assert page.locator('#attachmentBar').evaluate(
        '(el) => getComputedStyle(el).overflowY') == 'auto'
    page.locator('.image-edit-advanced summary').click()
    expect(page.locator('.image-edit-advanced-fields')).to_be_visible()
    page.locator('.image-edit-advanced input[type=text]').fill('text, watermark')
    page.locator('.image-edit-advanced input[type=text]').dispatch_event('change')
    assert page.evaluate('MLXChatAttachments.getEditOptions().negative_prompt') == 'text, watermark'
    mode.select_option('describe')
    assert page.evaluate('MLXChatAttachments.getEditOptions()') == {}
    expect(page.locator('.image-edit-options')).to_have_count(0)
    mode.select_option('edit')
    assert page.evaluate('MLXChatAttachments.getEditOptions().negative_prompt') == 'text, watermark'
    assert page.evaluate('MLXChatAttachments.getAttachments().map(x => x.name)')[0] == 'person-1.png'
    assert page.evaluate('MLXChatAttachments.getAttachments().length') == 9


def test_reference_limit_and_clipboard(ui):
    page, _, _ = ui
    alerts = []
    page.on('dialog', lambda dialog: (alerts.append(dialog.message), dialog.accept()))
    page.locator('#fileInput').set_input_files([
        {'name': f'person-{index}.png', 'mimeType':'image/png', 'buffer': image_fixture()} for index in range(11)])
    expect(page.locator('#attachmentBar .image-attachment-chip')).to_have_count(10)
    assert len(alerts) == 1
    page.evaluate('MLXChatAttachments.clearAttachments()')
    page.locator('#input').focus()
    # Dispatch the paste payload itself: Meta+V is macOS-specific and can
    # resolve to no clipboard data in headless Linux Chromium CI.
    # This exercises the real document paste handler without OS clipboard access.
    page.evaluate('''async () => {
        const canvas = document.createElement('canvas'); canvas.width = 32; canvas.height = 32;
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
        const transfer = new DataTransfer();
        transfer.items.add(new File([blob], 'clipboard.png', {type: 'image/png'}));
        document.getElementById('input').dispatchEvent(new ClipboardEvent('paste', {
            bubbles: true, cancelable: true, clipboardData: transfer
        }));
    }''')
    expect(page.locator('#attachmentBar .image-attachment-chip')).to_have_count(1)
