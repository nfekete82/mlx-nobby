"""Passive, process-local routing observations. Never retains request content."""
from collections import Counter, deque
from copy import deepcopy
from contextvars import ContextVar
import hashlib
import json
import math
import statistics
import threading
import time
import uuid

from backend.observability import ensure_trace_id, safe_model_metadata

MAX_EVENTS = 500
_LOCK = threading.RLock()
_EVENTS = deque(maxlen=MAX_EVENTS)
_CURRENT_EVENT = ContextVar('routing_event_id', default=None)


def record_event(*, prompt='', source='router', route=None, request_id=None,
                 model=None, role=None, confidence=None, reason=None, guards=(),
                 signals=(), fallback=False, fallback_reason=None, attachments=(),
                 vision=False, routing_ms=None, total_ms=None, success=None,
                 error_code=None, event_id=None, phase='execution'):
    """Explicit fields only: arbitrary payloads and error messages cannot leak."""
    event = {
        'id': event_id or uuid.uuid4().hex, 'timestamp': time.time(),
        'request_id': ensure_trace_id(request_id), 'source': source,
        'phase': phase, 'selected_route': route, 'selected_model_role': role,
        'model': model, 'confidence': confidence, 'decision_reason': reason,
        'guards': list(guards), 'intent_signals': list(signals),
        'fallback': bool(fallback), 'fallback_reason': fallback_reason,
        'attachment_types': list(attachments), 'attachment_count': len(attachments),
        'vision': bool(vision), 'prompt_hash': hashlib.sha256(prompt.encode()).hexdigest(),
        'prompt_length': len(prompt), 'prompt_preview': '[redacted]',
        'latency_ms': {'routing': routing_ms, 'runtime_wait': None,
                       'first_semantic_output': None, 'total': total_ms},
        'success': success, 'error_code': error_code,
    }
    # Legacy UI/API fields remain readable without duplicating observations.
    event.update(created_at=event['timestamp'], target=route, reason=reason,
                 prompt_sha256=event['prompt_hash'], prompt_chars=len(prompt),
                 duration_ms=routing_ms, guarded=bool(guards))
    with _LOCK:
        _EVENTS.append(event)
    return deepcopy(event)


def update_event(event_id, **fields):
    with _LOCK:
        for event in reversed(_EVENTS):
            if event['id'] == event_id:
                if event['selected_model_role'] and fields.get('selected_model_role', event['selected_model_role']) is None:
                    fields['selected_model_role'] = event['selected_model_role']
                    fields['model'] = event['model']
                if event['fallback'] and fields.get('fallback') is False:
                    fields['fallback'] = True
                    fields['fallback_reason'] = event['fallback_reason']
                event.update(deepcopy(fields))
                return


def observe_fallback(reason):
    event_id = _CURRENT_EVENT.get()
    if event_id:
        update_event(event_id, fallback=True, fallback_reason=reason)


def observe_vision_selection(metadata):
    """Observe the returned role selection, including the existing vision fallback."""
    event_id = _CURRENT_EVENT.get()
    role = metadata.get('role')
    if not event_id or role not in {'vision', 'vision_uncensored'}:
        return
    runtime = metadata.get('runtime') or {}
    resolved = runtime.get('resolved') or {}
    model = safe_model_metadata(model=resolved.get('repo'), alias=resolved.get('alias'))
    update_event(event_id, selected_model_role=role,
                 model=model['alias'] or model['identifier'])
    if role == 'vision':
        observe_fallback('vision_role_fallback')


def events(*, route=None, source=None, success=None, fallback=None,
           model_role=None, limit=50):
    safe_limit = max(1, min(int(limit), MAX_EVENTS))
    with _LOCK:
        selected = []
        for event in reversed(_EVENTS):
            if ((route is None or event['selected_route'] == route)
                    and (source is None or event['source'] == source)
                    and (success is None or event['success'] == success)
                    and (fallback is None or event['fallback'] == fallback)
                    and (model_role is None or event['selected_model_role'] == model_role)):
                selected.append(deepcopy(event))
                if len(selected) == safe_limit:
                    break
        return selected


def event_for_job(job_id):
    with _LOCK:
        return next((deepcopy(e) for e in reversed(_EVENTS) if e.get('job_id') == job_id), None)


def clear_events():
    with _LOCK:
        _EVENTS.clear()


def stats(**filters):
    selected = events(limit=MAX_EVENTS, **filters)
    n = len(selected)
    times = sorted(e['latency_ms']['routing'] for e in selected
                   if e['latency_ms']['routing'] is not None)
    outcomes = [e for e in selected if e['success'] is not None]
    return {
        'total_events': n, 'by_route': dict(Counter(e['selected_route'] or 'unknown' for e in selected)),
        'by_model_role': dict(Counter(e['selected_model_role'] or 'unknown' for e in selected)),
        'fallback_rate': sum(e['fallback'] for e in selected) / n if n else 0,
        'error_rate': sum(e['success'] is False for e in outcomes) / len(outcomes) if outcomes else 0,
        'outcomes_known': len(outcomes), 'routing_samples': len(times),
        'routing_mean_ms': statistics.mean(times) if times else None,
        'routing_p50_ms': statistics.median(times) if times else None,
        'routing_p95_ms': times[max(0, math.ceil(len(times) * .95) - 1)] if times else None,
        'decision_reasons': dict(Counter(e['decision_reason'] or 'unknown' for e in selected).most_common(10)),
    }


def install_routes(app):
    @app.get('/api/routing/events')
    def get_events(route: str | None = None, source: str | None = None,
                   success: bool | None = None, fallback: bool | None = None,
                   model_role: str | None = None, limit: int = 50):
        return {'events': events(route=route, source=source, success=success,
                                 fallback=fallback, model_role=model_role, limit=limit),
                'max_retained': MAX_EVENTS}

    @app.get('/api/routing/stats')
    def get_stats(route: str | None = None, source: str | None = None,
                  success: bool | None = None, fallback: bool | None = None,
                  model_role: str | None = None):
        return stats(route=route, source=source, success=success,
                     fallback=fallback, model_role=model_role)

    @app.delete('/api/routing/events')
    def delete_events():
        clear_events()
        return {'cleared': True}


PATHS = {
    '/api/mlx/images/generate': ('image', 'image'),
    '/api/image/generate': ('image', 'image'),
    '/api/mlx/video/jobs': ('video', 'video'),
    '/api/chat/stream': ('chat', 'chat'),
    '/api/chat/reliable-stream': ('chat', 'chat'),
    '/api/mlx/chat/actions': ('media', None),
    '/api/mlx/agent/run': ('agent', 'agent'),
    '/api/mlx/chat/files/route': ('router', None),
}
MAX_CAPTURE = 16 * 1024 * 1024


def request_metadata(payload):
    prompt = str(payload.get('prompt') or payload.get('goal') or '')
    attachments = []
    for attachment in payload.get('attachments') or []:
        if isinstance(attachment, dict):
            attachments.append('image' if str(attachment.get('mime_type', '')).startswith('image/') or attachment.get('kind') == 'image' or attachment.get('artifact_id') else 'document')
    context = payload.get('file_context')
    if isinstance(context, dict):
        attachments.append('image' if str(context.get('mime_type', '')).startswith('image/')
                           or context.get('kind') == 'image' else 'document')
    if payload.get('active_artifact_id') and 'image' not in attachments:
        attachments.append('image')
    messages = payload.get('messages') or []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get('content')
        if isinstance(content, list):
            attachments.extend('image' for p in content if isinstance(p, dict) and p.get('type') == 'image_url')
        if message.get('role') == 'user':
            prompt = content if isinstance(content, str) else ''.join(
                str(p.get('text') or '') for p in (content or []) if isinstance(p, dict) and p.get('type') == 'text')
    return prompt, attachments


def apply_response(event, payload):
    """Read authoritative routing and model metrics, never model-generated text."""
    if not isinstance(payload, dict):
        return
    data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    routing = data.get('routing') or payload.get('routing') or {}
    if not isinstance(routing, dict):
        routing = {}
    target = payload.get('target') or routing.get('target')
    action = payload.get('action') or payload.get('tool') or routing.get('intent')
    if not target and action:
        if action.startswith('image_'):
            target = 'image'
        elif action.startswith('video_') or action == 'shorts_generate':
            target = 'video' if action != 'shorts_generate' else action
        elif action in {'research_agent', 'diagnostic_agent', 'coding_agent', 'orchestrator'}:
            target = 'agent'
        elif action == 'normal_chat':
            target = 'chat'
    if target:
        event['selected_route'] = event['target'] = target
        if target in {'image', 'image_edit', 'video', 'video_generate', 'shorts_generate', 'agent'}:
            event['source'] = 'video' if target in {'video', 'video_generate', 'shorts_generate'} else 'image' if target.startswith('image') else 'agent'
        if event['phase'] != 'preflight' and target in {'image', 'image_edit', 'video', 'video_generate', 'shorts_generate', 'agent'}:
            event['selected_model_role'] = 'image' if target.startswith('image') else 'agent' if target == 'agent' else 'video'
        if target == 'chat' and event['source'] == 'media':
            event['source'] = 'vision' if event['vision'] else 'chat'
    if action:
        event['selected_tool'] = action
    if routing:
        event['confidence'] = routing.get('confidence')
        event['decision_reason'] = event['reason'] = routing.get('guard') or routing.get('method') or 'runtime_routing'
        event['guards'] = [routing['guard']] if routing.get('guard') else []
        event['intent_signals'] = [routing['intent']] if routing.get('intent') else []
        if routing.get('fallback') or 'fallback' in str(routing.get('method') or ''):
            event['fallback'] = True
            event['fallback_reason'] = 'router_fallback'
    job = data.get('job') or (payload if 'operation' in payload and 'status' in payload else None)
    if isinstance(job, dict):
        job_payload = job.get('payload') or {}
        result = job.get('result') or {}
        selected = result.get('model') or job.get('model') or job_payload.get('model')
        event['job_id'] = job.get('id')
        if job.get('status') in {'completed', 'failed', 'cancelled'}:
            event['phase'] = 'execution'
            event['success'] = job.get('status') == 'completed'
            if event['success'] is False:
                event['error_code'] = 'job_' + job['status']
            if job.get('finished_at'):
                event['latency_ms']['total'] = max(0, round((job['finished_at'] - event['timestamp']) * 1000, 3))
        if job.get('started_at') and job.get('created_at'):
            event['latency_ms']['runtime_wait'] = max(0, round((job['started_at'] - job['created_at']) * 1000, 3))
        if selected and selected != 'auto':
            event['model'] = safe_model_metadata(model=selected)['identifier']
            event['selected_model_role'] = 'video' if event['source'] == 'video' else 'image'
    if payload.get('status') in {'queued', 'running', 'pending'}:
        event['phase'] = 'dispatch'
    if payload.get('error') or payload.get('status') in {'failed', 'error'}:
        event['success'] = False
        event['error_code'] = event['error_code'] or 'runtime_error'
    metrics = payload.get('model_metrics') or payload
    calls = metrics.get('calls') if isinstance(metrics, dict) else None
    if isinstance(calls, list) and calls:
        routers = [c for c in calls if (c.get('model') or {}).get('role') == 'router']
        if routers:
            event['router_model'] = routers[-1]['model'].get('alias') or routers[-1]['model'].get('identifier')
        relevant = calls if event['phase'] == 'preflight' else [
            c for c in calls if (c.get('model') or {}).get('role') != 'router'
            and event['source'] not in {'image', 'video'}]
        event['request_id'] = ensure_trace_id(metrics.get('trace_id') or calls[-1].get('trace_id'))
        if not relevant:
            return
        call = relevant[-1]
        model = call.get('model') or {}
        event['selected_model_role'] = model.get('role')
        if str(model.get('role') or '').startswith('vision'):
            event['source'] = 'vision'
            event['vision'] = True
        event['model'] = model.get('alias') or model.get('identifier')
        event['request_id'] = ensure_trace_id(call.get('trace_id') or metrics.get('trace_id'))
        timings = call.get('timings_ms') or {}
        event['latency_ms']['runtime_wait'] = timings.get('queue_wait')
        if call.get('status') == 'failed':
            event['success'] = False
            event['error_code'] = call.get('error_type') or 'model_call_failed'


class RoutingObservationMiddleware:
    """One passive hook per web execution; streams are forwarded immediately."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path')
        if scope.get('type') == 'http' and scope.get('method') == 'GET' and (
                str(path).startswith('/api/mlx/image-jobs/') or str(path).startswith('/api/mlx/video-jobs/')):
            job_id = path.rsplit('/', 1)[-1]
            event = event_for_job(job_id)
            if event:
                return await self._observe_job(scope, receive, send, event)
        if scope.get('type') != 'http' or scope.get('method') != 'POST' or path not in PATHS:
            return await self.app(scope, receive, send)
        source, route = PATHS[path]
        started = time.perf_counter()
        request_body = bytearray()
        response_body = bytearray()
        event = None
        sse = False
        status = 200
        event_id = uuid.uuid4().hex
        context_token = _CURRENT_EVENT.set(event_id)
        request_overflow = False
        response_overflow = False

        async def observed_receive():
            nonlocal event, request_overflow
            message = await receive()
            if message.get('type') == 'http.request':
                body = message.get('body', b'')
                if len(request_body) + len(body) <= MAX_CAPTURE and not request_overflow:
                    request_body.extend(body)
                else:
                    request_overflow = True
                    request_body.clear()
                if not message.get('more_body'):
                    try:
                        payload = json.loads(request_body)
                        prompt, attachments = request_metadata(payload)
                        event = record_event(event_id=event_id, prompt=prompt, source='vision' if 'image' in attachments and source == 'chat' else source,
                                             route=route, request_id=payload.get('trace_id'),
                                             attachments=attachments, vision='image' in attachments,
                                             reason='vision_input' if 'image' in attachments and source == 'chat' else 'chat_runtime' if source == 'chat' else None)
                    except (ValueError, TypeError, AttributeError):
                        event = record_event(event_id=event_id, source=source, route=route, reason='metadata_unavailable')
                    request_body.clear()
            return message

        def inspect_frame(frame):
            if event is None:
                return
            try:
                lines = frame.decode('utf-8').splitlines()
                name = next((line[6:].strip() for line in lines if line.startswith('event:')), '')
                raw = '\n'.join(line[5:].strip() for line in lines if line.startswith('data:'))
                payload = json.loads(raw)
                if name == 'metrics':
                    apply_response(event, payload)
                elif name == 'error' or payload.get('error') or payload.get('type') == 'error':
                    event['success'] = False
                    code = payload.get('code')
                    event['error_code'] = code if code in {
                        'recovery_timeout', 'recovery_blocked', 'stream_stalled',
                        'empty_stream', 'stream_start_failed', 'stream_failed',
                        'empty_response', 'stream_interrupted'
                    } else 'stream_error'
                elif name in {'retry', 'recovery'} or payload.get('type') in {'retry', 'recovery'}:
                    event['fallback'] = True
                    event['fallback_reason'] = 'stream_recovery'
                elif payload.get('type') == 'content' and payload.get('text'):
                    if event['latency_ms']['first_semantic_output'] is None:
                        event['latency_ms']['first_semantic_output'] = round((time.perf_counter() - started) * 1000, 3)
            except (ValueError, TypeError, AttributeError, KeyError, UnicodeDecodeError):
                pass

        async def observed_send(message):
            nonlocal sse, status, response_overflow
            if message['type'] == 'http.response.start':
                status = message['status']
                sse = any(k.lower() == b'content-type' and b'text/event-stream' in v for k, v in message.get('headers', []))
            elif message['type'] == 'http.response.body':
                body = message.get('body', b'')
                if sse:
                    # Bounded frame parsing handles arbitrary ASGI chunk boundaries.
                    for offset in range(0, len(body), 8192):
                        response_body.extend(body[offset:offset + 8192])
                        while b'\n\n' in response_body:
                            frame, _, tail = response_body.partition(b'\n\n')
                            if not response_overflow and len(frame) <= 65536:
                                inspect_frame(bytes(frame))
                            response_body[:] = tail
                            response_overflow = False
                        if len(response_body) > 65536:
                            response_body[:] = response_body[-1:]
                            response_overflow = True
                elif not response_overflow:
                    if len(response_body) + len(body) <= 1024 * 1024:
                        response_body.extend(body)
                    else:
                        response_overflow = True
                        response_body.clear()
                if not message.get('more_body') and not sse and event is not None:
                    try:
                        apply_response(event, json.loads(response_body))
                    except (ValueError, TypeError, AttributeError, KeyError):
                        pass
                    response_body.clear()
            await send(message)

        try:
            await self.app(scope, observed_receive, observed_send)
        except BaseException:
            if event:
                event['success'] = False
                event['error_code'] = 'request_interrupted'
            raise
        finally:
            if event:
                if event['success'] is None:
                    event['success'] = status < 400
                if status >= 400:
                    event['success'] = False
                    event['error_code'] = f'http_{status}'
                event['latency_ms']['total'] = round((time.perf_counter() - started) * 1000, 3)
                update_event(event['id'], **{k: v for k, v in event.items() if k != 'id'})
            _CURRENT_EVENT.reset(context_token)

    async def _observe_job(self, scope, receive, send, event):
        """Consume existing job progress responses; never issue extra polls."""
        body = bytearray()
        status = 200
        overflow = False

        async def observed_send(message):
            nonlocal status, overflow
            if message['type'] == 'http.response.start':
                status = message['status']
            elif message['type'] == 'http.response.body' and not overflow:
                chunk = message.get('body', b'')
                if len(body) + len(chunk) <= 1024 * 1024:
                    body.extend(chunk)
                else:
                    overflow = True
                    body.clear()
                if not message.get('more_body') and status < 400 and not overflow:
                    try:
                        apply_response(event, json.loads(body))
                        update_event(event['id'], **{k: v for k, v in event.items() if k != 'id'})
                    except (ValueError, TypeError, AttributeError, KeyError):
                        pass
                    body.clear()
            await send(message)

        await self.app(scope, receive, observed_send)
