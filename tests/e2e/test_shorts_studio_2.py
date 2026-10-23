"""Text workflow in the production page, desktop and mobile, with isolated jobs."""
import json
from copy import deepcopy

from playwright.sync_api import expect

from .harness import image_fixture


def test_shorts_text_storyboard_edit_images_and_render(ui):
    page, _agent, _allowed = ui
    _allowed.append('502 (Bad Gateway)')  # Deliberate first planning failure below.
    project = {
        'schema_version':2, 'title':'Neuer Short', 'duration':20, 'quality':'fast', 'briefing':'',
        'language':'de', 'voice':'Lana Weiss', 'voice_enabled':True, 'voice_speed':1,
        'captions':{'position':'bottom','size':54,'style':'bold'}, 'music_selection':'auto',
        'music_enabled':False, 'music_mode':'off', 'cast':[], 'style_preset':'auto',
        'consistency_mode':False, 'scenes':[
            {'id':f'scene-{i}', 'duration':5, 'title':'', 'description':'', 'narration':'',
             'caption':'', 'camera':'', 'video_prompt':'', 'voice_enabled':True,
             'transition':{'type':'cut','duration':0}, 'sfx':{'enabled':False}, 'music':None}
            for i in range(4)]}
    draft = {'id':'fixture-draft','kind':'shorts_draft','version':1,'project':project}
    calls = []
    fail_plan = [True]

    def respond(route):
        request = route.request
        path = request.url.split('/api/mlx/shorts')[1].split('?')[0]
        payload = request.post_data_json if request.method in ('POST','PUT') else None
        calls.append((request.method, path, deepcopy(payload)))
        if path == '/capabilities':
            data = {'qualities':{'fast':{'durations':[5,6,8,10,20]}, 'standard':{'durations':[5,6,8,10]},
                                 'quality':{'durations':[5]}}, 'music':[], 'sfx':[]}
        elif path == '/scene-images':
            data = {'images':[{'id':'a'*32,'url':'/api/mlx/shorts/scene-images/'+'a'*32}]}
        elif path.startswith('/scene-images/'):
            route.fulfill(content_type='image/png', body=image_fixture()); return
        elif path.endswith('/plan'):
            if fail_plan[0]:
                fail_plan[0] = False
                route.fulfill(status=502, json={'detail':{'code':'invalid_plan','error_id':'fixture'}}); return
            assert payload['scene_count'] == 3
            draft['project']['title'] = 'Venus'
            draft['project']['scenes'] = [
                dict(project['scenes'][0], id=f'scene-{i}', title=title, duration=10,
                     description='Venus in space', narration='Ein Tag dauert 243 Erdtage.',
                     video_prompt='Photoreal Venus in space')
                for i, title in enumerate(['Anflug','Rotation','Oberfläche'])]
            draft['version'] += 1; data = {'draft':draft}
        elif path.endswith('/render'):
            assert draft['project']['voice'] == 'Lana Weiss'
            assert draft['project']['scenes'][0]['scene_image_id'] == 'a'*32
            data = {'job':{'id':'fixture-job','status':'queued','project':draft['project']}}
        elif request.method == 'PUT':
            assert payload['expected_version'] == draft['version']
            draft['project'] = payload['project']; draft['version'] += 1; data = {'draft':draft}
        else:
            data = {'draft':draft}
        route.fulfill(json=data)

    page.route('**/api/mlx/shorts/**', respond)
    page.route('**/api/mlx/audio/voices/manage', lambda route: route.fulfill(json={
        'voices':[{'id':'Lana Weiss','label':'Lana Weiss'}]}))
    page.evaluate("window.MLXI18n.setLanguage('de')")
    page.wait_for_function('!!window.MLXShortsStudio')
    page.evaluate('window.MLXShortsStudio.open()')
    page.wait_for_function('!!window.MLXShortsProjectEditor')
    page.evaluate('window.MLXShortsProjectEditor.newDraft()')
    studio = page.locator('.mlx-shorts-project-overlay')
    expect(studio).to_be_visible()
    advanced = studio.locator('.mlx-shorts-advanced-view')
    expect(advanced).not_to_have_attribute('open', '')
    expect(advanced.locator('summary').first).to_have_text('Erweiterte Bearbeitung öffnen')
    geometry = studio.locator('.mlx-shorts-studio-panel').evaluate('e => ({width:e.clientWidth, viewport:innerWidth, overflow:e.scrollWidth > e.clientWidth})')
    assert geometry['width'] >= geometry['viewport'] * .94
    assert not geometry['overflow']
    prompt = studio.get_by_label('Beschreibe deinen Short')
    prompt.fill('Erstelle eine fotorealistische 30 Sekunden lange Venus-Dokumentation mit drei Szenen.')
    studio.get_by_label('Länge', exact=True).select_option('30')
    studio.get_by_label('Szenen', exact=True).select_option('3')
    studio.get_by_label('Sprecherstimme', exact=True).select_option('Lana Weiss')
    plan = studio.get_by_role('button', name='Mit KI planen', exact=True).filter(visible=True)
    plan.click()
    expect(studio.locator('.mlx-shorts-studio-feedback')).to_contain_text('keinen gültigen Szenenplan')
    expect(prompt).to_have_value('Erstelle eine fotorealistische 30 Sekunden lange Venus-Dokumentation mit drei Szenen.')
    plan.click()
    expect(studio.get_by_role('heading', name='Dein Storyboard')).to_be_visible()
    expect(studio.locator('.mlx-shorts-simple-scene')).to_have_count(3)
    expect(studio.locator('.mlx-shorts-studio-feedback')).not_to_contain_text('keinen gültigen Szenenplan')
    assert not any(path.endswith('/render') for _, path, _ in calls)
    first = studio.locator('.mlx-shorts-simple-scene').first
    first.locator('summary').click()
    first.get_by_role('button', name='Aus Bibliothek wählen').click()
    first.get_by_role('button', name='Bild wählen', exact=True).click()
    expect(first.locator('.mlx-shorts-scene-thumb')).to_be_visible()
    first.get_by_role('button', name='Bearbeiten', exact=True).click()
    expect(advanced).to_have_attribute('open', '')
    expect(advanced.locator('summary').first).to_have_text('Erweiterte Bearbeitung schließen')
    advanced.locator('summary').first.click()
    expect(advanced.locator('summary').first).to_have_text('Erweiterte Bearbeitung öffnen')
    # Force another render of the editor: old detached details toggle events must not reopen it.
    studio.get_by_label('Expertenmodus').check()
    studio.get_by_label('Expertenmodus').uncheck()
    expect(advanced).not_to_have_attribute('open', '')
    expect(advanced.locator('summary').first).to_have_text('Erweiterte Bearbeitung öffnen')
    page.evaluate("window.MLXI18n.setLanguage('en')")
    expect(studio.get_by_label('Describe your Short')).to_be_visible()
    expect(studio.get_by_text('Create videos from a simple description.', exact=True)).to_be_visible()
    expect(studio.get_by_label('Expert mode')).to_be_visible()
    page.evaluate("window.MLXI18n.setLanguage('de')")
    page.evaluate("window.MLXShortsStudio.setActiveJob = job => window.__shortsRendered = job; window.MLXShortsStudio.openJob = () => {}")
    studio.get_by_role('button', name='Video erstellen', exact=True).click()
    page.wait_for_function('window.__shortsRendered?.id === "fixture-job"')
    assert len([path for _, path, _ in calls if path.endswith('/render')]) == 1
