"""Normalize optional editor settings against local capabilities, without queuing work."""
from copy import deepcopy

STYLE_PRESETS = {
    'auto': '',
    'cinematic': 'Cinematic storytelling, controlled lighting, filmic color palette, deliberate camera movement.',
    'luxury_commercial': 'Luxury commercial, premium product hero shots, precise tracking shots, rich contrast, elegant studio lighting, dry restrained presentation.',
    'funny_meme': 'Funny social meme, expressive visual beats, clear punchline, playful framing and bold color.',
    'documentary': 'Documentary realism, natural lighting, observational framing, grounded environments.',
    'futuristic': 'Futuristic imagery, coherent speculative design, cool luminous palette and smooth camera movement.',
    'product_ad': 'Product advertisement, clean product detail shots, readable silhouettes, polished lighting.',
    'social_viral': 'Social viral storytelling, immediate visual hook, energetic pacing, clear readable action.',
}


def allocate_durations(duration, count, allowed):
    """Find an exact supported timeline, favoring evenly paced scenes."""
    states = {0: (0, [])}
    target = duration / count
    for _ in range(count):
        following = {}
        for total, (cost, values) in states.items():
            for value in allowed:
                new_total = total + value
                if new_total > duration:
                    continue
                option = (cost + (value - target) ** 2, values + [value])
                if new_total not in following or option[0] < following[new_total][0]:
                    following[new_total] = option
        states = following
    if duration not in states:
        raise ValueError(f"{duration}s cannot be divided into {count} scenes at this quality; choose a compatible duration or scene count")
    return states[duration][1]


def normalize_short_for_available_runtime(project, *, planning=False, scene_count=None):
    from agent import shorts_jobs
    from agent.shorts_composer import library_tracks
    from agent.shorts_planner import ShortProject, quality_capabilities, CaptionSettings
    data = deepcopy(project.model_dump(mode='json') if isinstance(project, ShortProject) else project)
    warnings = []
    if not isinstance(data, dict):
        raise ValueError('short plan must be one JSON object')
    scenes = data.get('scenes', [])
    if not isinstance(scenes, list) or not scenes:
        raise ValueError('at least one scene is required')
    if scene_count is not None and len(scenes) != scene_count:
        raise ValueError(f'exactly {scene_count} scenes required')
    qualities = quality_capabilities()
    quality = data.get('quality', 'fast')
    if quality not in qualities:
        raise ValueError('unsupported render quality')
    if planning:
        duration = data.get('duration')
        if isinstance(duration, bool) or not isinstance(duration, int) or not 5 <= duration <= 300:
            raise ValueError('project duration must be an integer from 5 to 300')
        current = [scene.get('duration') for scene in scenes if isinstance(scene, dict)]
        if len(current) != len(scenes):
            raise ValueError('scene must be an object')
        if any(type(d) is not int or d not in qualities[quality]['durations'] for d in current) or sum(current) != duration:
            durations = allocate_durations(duration, len(scenes), qualities[quality]['durations'])
            for scene, value in zip(scenes, durations):
                scene['duration'] = value
            warnings.append('timeline_normalized')
    caption_defaults = CaptionSettings().model_dump()
    captions = data.get('captions')
    if not isinstance(captions, dict):
        data['captions'] = caption_defaults
        if captions is not None: warnings.append('caption_defaults')
    elif isinstance(captions, dict):
        for key, default in caption_defaults.items():
            value = captions.get(key, default)
            valid = (value in ('bottom', 'center', 'top') if key == 'position' else
                     value in ('bold', 'plain') if key == 'style' else type(value) is int and 20 <= value <= 100)
            if not valid:
                captions[key] = default
                warnings.append('caption_defaults')
    music = library_tracks(shorts_jobs.MUSIC_DIRECTORY)
    sfx = library_tracks(shorts_jobs.MUSIC_DIRECTORY.parent / 'sfx')
    music_paths = {track['track'] for track in music}
    sfx_paths = {track['track'] for track in sfx}
    styles = ('cinematic', 'futuristic', 'dark', 'emotional', 'energetic', 'ambient')

    def normalize_music(settings, prefix='', inherit=None):
        def key(name): return prefix + name
        inherit = inherit or {}
        enabled = settings.get(key('enabled'))
        if enabled is None: enabled = inherit.get('enabled', True)
        style = settings.get(key('style')) or inherit.get('style') or 'cinematic'
        track = settings.get(key('track')) or inherit.get('track')
        if style not in styles:
            style = 'cinematic'; settings[key('style')] = style; warnings.append('music_defaults')
        if track == 'auto':
            track = None; settings[key('track')] = None
        if track and track not in music_paths:
            settings[key('track')] = None; track = None; warnings.append('music_track_missing')
        matching = [item for item in music if item['style'] == style]
        if enabled and not track and not matching:
            settings[key('enabled')] = False
            warnings.append('music_unavailable')
        for name, default, maximum in (('volume', .18, 1), ('start_offset', 0., 3600), ('fade_in', 0., 10), ('fade_out', 0., 10)):
            item_key = key(name)
            if prefix and name != 'volume': continue
            if item_key in settings and settings[item_key] is not None:
                value = settings[item_key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= maximum:
                    settings[item_key] = default; warnings.append('music_defaults')
        return {'enabled': settings.get(key('enabled'), enabled), 'style': style, 'track': track,
                'volume': settings.get(key('volume'), .18)}

    if data.get('music_selection') == 'off':
        data['music_enabled'] = False; data['music_mode'] = 'off'
    elif data.get('music_selection') == 'auto':
        data['music_enabled'] = True
        if data.get('music_mode') == 'off': data['music_mode'] = 'global'
        if not data.get('music_style') and music:
            data['music_style'] = music[0]['style'] if music[0]['style'] in styles else 'cinematic'
    global_music = normalize_music(data, 'music_')
    if data.get('music_mode') == 'off':
        data['music_enabled'] = False
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict): raise ValueError('scene must be an object')
        if planning:
            scene['title'] = scene.get('title') or f'Scene {index+1}'
            scene['description'] = scene.get('description') or scene.get('video_prompt') or ''
            scene['video_prompt'] = scene.get('video_prompt') or scene['description']
            scene['camera'] = scene.get('camera') or 'steady cinematic framing'
            scene['caption'] = scene.get('caption') or ((scene.get('narration') or scene['description'])[:180] if data.get('subtitles_enabled', True) else '')
            if not data.get('voice_enabled', True) or (not scene.get('dialogue') and not scene.get('narration', '').strip()):
                scene['voice_enabled'] = False
        transition = scene.get('transition')
        if not isinstance(transition, dict):
            scene['transition'] = {'type': 'cut', 'duration': 0.0}
            if transition is not None: warnings.append('transition_defaults')
        elif isinstance(transition, dict):
            kind = transition.get('type', 'cut'); amount = transition.get('duration', 0)
            if kind == 'cut': transition['duration'] = 0.0
            elif kind not in ('fade', 'fadeblack', 'fadewhite', 'flash'):
                scene['transition'] = {'type': 'cut', 'duration': 0.0}; warnings.append('transition_defaults')
            elif isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 < amount <= 2:
                transition['duration'] = .5; warnings.append('transition_defaults')
        if scene.get('music') is not None and not isinstance(scene['music'], dict):
            scene['music'] = None; warnings.append('music_defaults')
        if isinstance(scene.get('music'), dict):
            normalize_music(scene['music'], inherit=global_music)
        effect = scene.get('sfx')
        if not isinstance(effect, dict):
            scene['sfx'] = {'enabled': False, 'track': None, 'volume': .5, 'offset': 0.}
            if effect is not None: warnings.append('sfx_defaults')
        if isinstance(effect, dict):
            if effect.get('enabled') and effect.get('track') not in sfx_paths:
                effect.update(enabled=False, track=None); warnings.append('sfx_unavailable')
            elif effect.get('track') and effect['track'] not in sfx_paths:
                effect['track'] = None
            scene_duration = scene.get('duration', 5)
            max_offset = max(0, scene_duration - .01) if type(scene_duration) is int else 0
            for key, default, maximum in (('volume', .5, 1), ('offset', 0., max_offset)):
                value = effect.get(key, default)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= maximum:
                    effect[key] = default; warnings.append('sfx_defaults')
    scenes[-1]['transition'] = {'type': 'cut', 'duration': 0.0}
    preset = data.get('style_preset', 'auto')
    if planning and preset in STYLE_PRESETS and STYLE_PRESETS[preset]:
        bible = data.get('visual_bible') or {}
        bible.setdefault('style', STYLE_PRESETS[preset])
        if not bible.get('style'): bible['style'] = STYLE_PRESETS[preset]
        data['visual_bible'] = bible
    return data, list(dict.fromkeys(warnings))
