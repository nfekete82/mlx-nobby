"""Multi-image UI uses the existing production video action and player."""
import re
import uuid

from playwright.sync_api import expect

from .harness import image_fixture
from .test_acceptance import MEDIA, send


def test_multi_image_order_replace_library_and_existing_player(ui):
    page, agent, _ = ui
    def upload(route):
        name = uuid.uuid4().hex[:12] + '.png'
        route.fulfill(json={'path': '/managed/uploads/' + name, 'stored_name': name})
    page.route('**/api/mlx/batch/upload', upload)
    page.route('**/api/mlx/video/models', lambda route: route.fulfill(
        json={'models': [], 'profiles': {'uncensored_available': False},
              'multi_image': {'native_keyframes': True}}))
    asset_id = '1791579990-f04fe5195fe0'
    page.route('**/api/library/assets?kind=image&limit=100', lambda route: route.fulfill(
        json={'assets': [{'kind': 'image', 'id': asset_id, 'url': '/test-library.png'}]}))
    page.route('**/test-library.png', lambda route: route.fulfill(
        content_type='image/png', body=image_fixture()))
    page.locator('#fileInput').set_input_files([
        {'name': f'frame-{index}.png', 'mimeType': 'image/png', 'buffer': image_fixture()}
        for index in range(3)])
    send(page, 'Generate a video: A red ball moves slowly in soft light')
    expect(page.locator('#mediaQualityModal')).to_be_visible()
    expect(page.locator('#multiVideoEnabled')).to_be_checked()
    expect(page.locator('#multiVideoImages > div')).to_have_count(3)
    expect(page.locator('#multiVideoMode')).to_have_value('keyframes')
    before = page.evaluate("MLXMultiImageVideo.selection('fast').multi_images.map(x => x.stored_path)")
    cards = page.locator('#multiVideoImages > div')
    # HTML drag/drop uses the actual handlers; keyboard controls cover touch users.
    transfer = page.evaluate_handle('new DataTransfer()')
    cards.first.dispatch_event('dragstart', {'dataTransfer': transfer})
    cards.last.dispatch_event('drop', {'dataTransfer': transfer})
    after = page.evaluate("MLXMultiImageVideo.selection('fast').multi_images.map(x => x.stored_path)")
    assert after == before[1:] + before[:1]
    cards.first.locator('input[type=file]').set_input_files(
        {'name': 'replacement.png', 'mimeType': 'image/png', 'buffer': image_fixture()})
    expect(cards.first.locator('img')).to_have_attribute('alt', 'replacement.png')
    cards.last.get_by_role('button', name=re.compile('Bild entfernen|Remove image')).click()
    expect(cards).to_have_count(2)
    page.locator('.multi-video-body > button').click()
    page.locator('.multi-video-library button').click()
    expect(cards).to_have_count(3)
    page.locator('#multiVideoMode').select_option('scenes')
    page.locator('#multiVideoPrompt').fill('A red ball moves between three scenes')
    page.evaluate(MEDIA)
    page.locator('#mediaQualityModalConfirm').click()
    expect(page.locator('.video-artifact-player')).to_be_visible()
    action = next(body for method, path, body in agent.calls if path == '/api/chat/actions')
    assert action['multi_image_mode'] == 'scenes'
    assert len(action['multi_images']) == 3
    assert action['multi_images'][-1] == {'artifact_id': 'image-' + asset_id}
    assert action['prompt'] == 'A red ball moves between three scenes'


def test_multi_image_limits_and_missing_native_support(ui):
    page, _agent, _ = ui
    send(page, 'Generate a video: A red ball rolls slowly')
    expect(page.locator('#mediaQualityModal')).to_be_visible()
    page.locator('#multiVideoEnabled').check()
    expect(page.locator('#multiVideoMode option[value=keyframes]')).to_have_js_property('disabled', True)
    files = [{'name': f'frame-{i}.png', 'mimeType': 'image/png', 'buffer': image_fixture()}
             for i in range(6)]
    page.locator('#multiVideoFiles').set_input_files(files)
    expect(page.locator('.multi-video-error')).to_contain_text('5')
    expect(page.locator('#multiVideoImages > div')).to_have_count(0)
    page.locator('#mediaQualityModalConfirm').click()
    expect(page.locator('.multi-video-error')).to_contain_text('2–5')
    expect(page.locator('#mediaQualityModal')).to_be_visible()
