"""Rolling portrait settings through the real browser; downstream models are fixtures."""
import io

import pytest
from PIL import Image
from playwright.sync_api import expect

from .conftest import navigate_chat_page
from .test_acceptance import MEDIA, send


@pytest.mark.parametrize('viewport', [{'width':1440,'height':1000},{'width':390,'height':844}],ids=['desktop','mobile'])
def test_rolling_portrait_settings_reach_job_and_player(browser,web,viewport):
    url,agent=web
    agent.reset()
    context=browser.new_context(viewport=viewport)
    # Supply the unrelated discovery endpoint missing from the shared AgentFixture.
    # Install before navigation, retaining strict console checks for this test.
    context.route('**/api/mlx/video/edit/jobs',lambda route:route.fulfill(json={'jobs':[]}))
    context.route('**/api/mlx/batch/upload',lambda route:route.fulfill(json={
        'path':'/managed/uploads/123456abcdef.png','stored_name':'123456abcdef.png'}))
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' else None)
    try:
        navigate_chat_page(page,url)
        image=io.BytesIO()
        Image.new('RGB',(64,128),'blue').save(image,format='PNG')
        page.locator('#fileInput').set_input_files({
            'name':'portrait.png','mimeType':'image/png','buffer':image.getvalue()})
        send(page,'Generate a video with Rolling-Window-Test: A red ball moves naturally')
        expect(page.locator('#mediaQualityModal')).to_be_visible()
        expect(page.locator('#mediaFormat')).to_have_value('portrait')
        page.locator('#mediaFormat').select_option('portrait')
        page.locator('[data-media-quality="standard"]').click()
        page.locator('#videoDuration').select_option('10')
        page.evaluate(MEDIA)
        page.locator('#mediaQualityModalConfirm').click()
        expect(page.locator('.video-artifact-player')).to_be_visible()
        action=next(body for method,path,body in agent.calls if path=='/api/chat/actions')
        assert action['quality']=='standard'
        assert action['video_options']['aspect_ratio']=='9:16'
        assert action['video_options']['duration']==10
        assert action['video_options']['continuation_mode']=='rolling'
        assert action['file_context']['stored_path']=='/managed/uploads/123456abcdef.png'
        assert not errors,errors
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    finally:
        context.close()
