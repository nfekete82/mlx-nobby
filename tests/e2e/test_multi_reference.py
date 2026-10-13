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
    page.locator('.image-edit-options summary').click()
    page.locator('.image-edit-options input[type=number]').first.fill('42')
    page.locator('.image-edit-options input[type=number]').first.dispatch_event('change')
    assert page.evaluate('MLXChatAttachments.getEditOptions().seed') == 42
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
    page.evaluate('''async () => {
        const canvas = document.createElement('canvas'); canvas.width=32; canvas.height=32;
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
        await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);
    }''')
    page.keyboard.press('Meta+V')
    expect(page.locator('#attachmentBar .image-attachment-chip')).to_have_count(1)
