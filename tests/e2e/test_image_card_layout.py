"""Offline Chromium acceptance: real card renderer/CSS; synthetic PNGs, no services."""
import io
import os
import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[2]


def mount(page, width=1440, height=1000):
    page.set_viewport_size({'width': width, 'height': height})
    page.set_content('<main class="messages"><div class="messages-inner">'
                     '<article class="message"><div>Ordinary chat message</div></article>'
                     '<article class="message image-message"><div id="result"></div></article>'
                     '</div></main>')
    page.add_style_tag(content=(ROOT / 'frontend/assets/chat.css').read_text())
    page.add_style_tag(content=(ROOT / 'frontend/assets/chat/media-privacy.css').read_text())
    page.evaluate('''() => {
        window.rt = window.referenceText = (_key, fallback) => fallback;
        window.calls = [];
        window.MLXRegionEditor = {open: async () => calls.push('region')};
        window.MLXImageCompare = {open: () => calls.push('compare')};
        window.MLXChatGeneration = {createImageUpscaleMenu: () => {
            const fragment = document.createDocumentFragment();
            for (const label of ['Neu generieren', 'Bild verbessern']) {
                const button = document.createElement('button');
                button.className = 'message-action-btn'; button.textContent = label;
                button.onclick = () => calls.push(label); fragment.append(button);
            }
            return fragment;
        }};
    }''')
    source = (ROOT / 'frontend/assets/chat/rendering.js').read_text()
    page.add_script_tag(content=source[source.index('function prepareImagePreview('):
                                       source.index('function renderImageJobCard(')])
    page.add_script_tag(content=(ROOT / 'frontend/assets/chat/image-preview.js').read_text())

    def image_response(route):
        match = re.search(r'synthetic-(\d+)-(\d+)', route.request.url)
        image = Image.new('RGB', tuple(map(int, match.groups())), '#263e51')
        draw = ImageDraw.Draw(image)
        draw.ellipse((160, 250, 1088, 1178), fill='#db9e66')
        draw.rectangle((0, 1250, 1248, 1664), fill='#395d65')
        data = io.BytesIO()
        image.save(data, 'PNG')
        headers = {'Content-Disposition': 'attachment; filename="synthetic-original.png"'} if 'download=1' in route.request.url else {}
        route.fulfill(body=data.getvalue(), content_type='image/png', headers=headers)
    page.route('http://fixture.test/api/mlx/images/**', image_response)
    page.evaluate('''() => { const base = document.createElement('base');
        base.href = 'http://fixture.test/'; document.head.append(base); }''')


def render(page, width=1248, height=1664, restoring=False):
    page.evaluate('''({width, height, restoring}) => {
        const artifact = {image_id: `synthetic-${width}-${height}`, source_image_id: 'original',
            width, height, model: 'juggernaut-xl', provider: 'sdxl',
            quality: 'ultra_plus', steps: 40, seed: 42,
            prompt: 'Synthetic acceptance prompt. ' + 'longword'.repeat(200)};
        const message = {tool_result: {tool: 'image_edit', artifacts: [artifact]},
            image_job: restoring ? {status: 'saving', phase: 'restoring_chat'} : undefined};
        document.querySelector('#result').append(renderImageArtifactCard(message));
    }''', dict(width=width, height=height, restoring=restoring))
    page.locator('.image-artifact-preview').last.evaluate('(img) => img.decode()')


def bounds(page):
    return page.locator('.image-artifact-card').first.evaluate('''card => {
        const image = card.querySelector('img').getBoundingClientRect();
        const details = card.querySelector('.image-artifact-details').getBoundingClientRect();
        return {width: card.getBoundingClientRect().width, imageRight: image.right,
                detailsLeft: details.left, imageBottom: image.bottom, detailsTop: details.top,
                imageHeight: image.height, overflow: document.documentElement.scrollWidth > innerWidth};
    }''')


@pytest.mark.parametrize('viewport,container,two_columns', [(1440, None, True), (1440, 600, False), (390, None, False)])
def test_image_card_layout(browser, viewport, container, two_columns):
    page = browser.new_page()
    mount(page, viewport)
    if container:
        page.locator('main').evaluate('(el) => el.style.width = "600px"')
    for width, height in [(1248, 1664), (1664, 1248), (1440, 1440)]:
        render(page, width, height)
    first = bounds(page)
    assert not first['overflow']
    assert first['imageHeight'] <= 680
    if two_columns:
        assert first['width'] > 1000
        assert first['detailsLeft'] >= first['imageRight']
        assert page.locator('.message').first.bounding_box()['width'] == 900
    else:
        assert first['detailsTop'] >= first['imageBottom']
    page.locator('.image-artifact-info summary').first.click()
    assert page.locator('.image-artifact-prompt').first.is_visible()
    assert not bounds(page)['overflow']
    # The second card stays closed; long prompts never affect neighbouring cards.
    assert not page.locator('.image-artifact-info').nth(1).get_attribute('open')
    output = os.environ.get('MLX_IMAGE_CARD_EVIDENCE')
    if output:
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        page.locator('.image-artifact-info summary').first.click()
        page.locator('.image-artifact-card').first.screenshot(
            path=str(directory / f'layout-{viewport}-{container or "full"}.png'))
    page.close()


def test_image_card_interactions_and_restore(browser):
    page = browser.new_page()
    mount(page)
    render(page)
    image = page.locator('.image-artifact-preview')
    image.focus()
    image.press('Enter')
    expect(page.locator('.image-preview-dialog')).to_be_visible()
    page.keyboard.press('Escape')
    expect(image).to_be_focused()
    page.get_by_role('button', name='Edit region', exact=True).click()
    page.get_by_role('button', name='Before / after', exact=True).click()
    page.get_by_role('button', name='Neu generieren', exact=True).click()
    page.get_by_role('button', name='Bild verbessern', exact=True).click()
    assert page.evaluate('calls') == ['region', 'compare', 'Neu generieren', 'Bild verbessern']
    with page.expect_download() as download:
        page.get_by_role('link', name='Download', exact=True).click()
    with Image.open(download.value.path()) as downloaded:
        assert downloaded.size == (1248, 1664)
    page.mouse.move(0, 0)
    page.locator('html').evaluate('(el) => el.classList.add("mlx-media-privacy-on")')
    page.wait_for_function("getComputedStyle(document.querySelector('.image-artifact-preview')).filter.includes('blur(30px)')")
    # Light theme tokens must reach the new card as well.
    page.add_style_tag(content=':root {--text: #17202a; --panel: #fff; --panel2: #eee; --border: #bbb; --muted: #444}')
    assert page.locator('.image-artifact-card').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(255, 255, 255)'
    page.locator('#result').evaluate('(el) => el.replaceChildren()')
    render(page, restoring=True)
    expect(page.locator('.image-artifact-preview')).to_be_visible()
    expect(page.get_by_role('link', name='Download', exact=True)).to_be_visible()
    assert page.locator('.image-artifact-card button').count() == 0
    page.close()
