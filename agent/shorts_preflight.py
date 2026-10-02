"""Provider readiness for the existing Shorts consistency worker."""
from agent import image_api


class ShortsPreflightError(ValueError):
    def __init__(self, message, models):
        super().__init__(message)
        self.models = models


def preflight_project(project, *, request_fn=None, scene_results=None, keyframe_results=None):
    from agent.shorts_jobs import valid_media_file
    videos = {r.get('scene_id') for r in scene_results or []
              if r.get('status') == 'completed' and valid_media_file(r.get('path'))}
    frames = {r.get('scene_id') for r in keyframe_results or []
              if r.get('status') == 'completed' and valid_media_file(r.get('path'))}
    if not project.consistency_mode or all(s.id in videos or s.id in frames for s in project.scenes):
        return {'available': True, 'warnings': [], 'models': []}
    try:
        payload = (request_fn or image_api.request)('GET', '/models', timeout=15)
    except Exception as exc:
        raise ValueError('Der lokale Bildgenerator ist nicht erreichbar. Bitte den Image-Dienst prüfen.') from exc
    ready = [m for m in payload.get('models', []) if m.get('enabled') and m.get('available') is True]
    models = [{'model': m['id'], 'provider': m.get('provider'), 'model_family': m.get('model_family'),
               'available': m.get('available') is True,
               'reason': (m.get('availability_note') or '') if m.get('provider') == 'mflux' and (m.get('availability_note') or '').startswith(('MFLUX', 'Qwen')) else '',
               'cli_version': (m.get('cli_capabilities') or {}).get('version')}
              for m in payload.get('models', []) if m.get('enabled')]
    generators = [m for m in ready if 'text_to_image' in m.get('capabilities', [])]
    if not generators:
        raise ShortsPreflightError('Kein kompatibler lokaler Keyframe-Generator verfügbar. Bitte den Image-Provider prüfen.', models)
    warnings = []
    if project.character_consistency and not any('image_edit' in m.get('capabilities', []) for m in ready):
        warnings.append('character_anchor_fallback')
    return {'available': True, 'warnings': warnings,
            'models': models}
