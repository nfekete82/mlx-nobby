"""Safe, backwards-compatible error and progress metadata for Shorts."""


def failure_fields(job, error, child=None):
    child = child or {}
    stage = job.get('phase', 'render')
    scenes = job.get('project', {}).get('scenes', [])
    index = min(max(0, int(job.get('current_scene') or 0)), max(0, len(scenes)-1))
    if stage == 'failed':
        current = int(job.get('current_scene') or 0)
        frames = {r.get('scene_id') for r in job.get('keyframe_results', []) if r.get('status') == 'completed'}
        stage = ('keyframe' if job.get('project', {}).get('consistency_mode') and current < len(scenes) and scenes[index].get('id') not in frames
                 else 'video' if current < len(scenes) else 'tts' if job.get('tts_status') == 'failed' else 'compose')
    diagnosis = getattr(error, 'diagnosis', {}) or child
    incompatible = 'inkompatibel' in str(error).lower() or 'nicht kompatibel' in str(error).lower()
    code = diagnosis.get('error_code') or ('IMAGE_PROVIDER_INCOMPATIBLE' if stage == 'keyframe' and incompatible else 'SHORTS_RENDER_FAILED')
    messages = {'keyframe': 'Der lokale Bildgenerator konnte den Keyframe nicht erstellen.',
                'video': 'Das Szenenvideo konnte nicht gerendert werden.',
                'tts': 'Die Sprache konnte nicht erzeugt werden.',
                'compose': 'Das finale Video konnte nicht zusammengesetzt werden.'}
    message = ('Der Keyframe-Generator ist mit der installierten MFLUX-Version nicht kompatibel.'
               if code == 'IMAGE_PROVIDER_INCOMPATIBLE' else messages.get(stage, 'Der Short konnte nicht gerendert werden.'))
    fields = {'error_code': code, 'error_stage': stage,
            'error_scene_id': scenes[index].get('id') if scenes and stage in {'keyframe', 'video'} else None,
            'error_scene_number': index+1 if scenes and stage in {'keyframe', 'video'} else None,
            'error_provider': diagnosis.get('error_provider') or child.get('provider') or ('mflux' if 'mflux' in str(error).lower() else None),
            'error_model': diagnosis.get('error_model') or child.get('model'),
            'error_message': message,
            'error_detail_safe': diagnosis.get('error_detail_safe') or 'Stage: ' + stage}

    if code == 'VOICEOVER_TOO_LONG':
        fields.update({key: diagnosis[key] for key in (
            'error_scene_id', 'error_scene_number', 'error_audio_duration', 'error_scene_duration'
        ) if key in diagnosis})
        fields['error_message'] = (
            f"Sprechertext in Szene {fields.get('error_scene_number')} ist zu lang. "
            f"{fields.get('error_audio_duration', 0):.1f} s Sprache für "
            f"{fields.get('error_scene_duration', 0):.1f} s Szene. "
            "Bitte Text kürzen oder Sprechgeschwindigkeit erhöhen."
        )
        fields['error_detail_safe'] = fields['error_message']
    return fields


def progress_fields(job):
    scenes = job.get('project', {}).get('scenes', [])
    count = len(scenes)
    current = max(0, min(int(job.get('current_scene') or 0), count))
    phase = job.get('phase', job.get('status'))
    child = max(0., min(float(job.get('child_progress') or 0), 1.))
    fraction = (current + (child * .25 if phase == 'keyframe' else .25 + child * .75 if phase == 'video' else 0)) / max(1, count)
    progress = min(.8, fraction * .8)
    if phase in {'video_completed', 'tts'}: progress = .82
    if phase == 'tts_completed': progress = .9
    if phase == 'compose': progress = .95
    if job.get('status') == 'completed': progress = 1.
    return {'progress': round(progress, 4), 'scene_number': min(current+1, count), 'scene_count': count}
