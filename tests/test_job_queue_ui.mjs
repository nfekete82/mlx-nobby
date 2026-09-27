import assert from 'node:assert/strict';
import fs from 'node:fs';

const common = fs.readFileSync('frontend/assets/common.js', 'utf8');
const queue = fs.readFileSync('frontend/assets/chat/job-queue.js', 'utf8');
const proxy = fs.readFileSync('agent/service_proxy.py', 'utf8');
const imageApi = fs.readFileSync('agent/image_api.py', 'utf8');
const videoApi = fs.readFileSync('agent/video_api.py', 'utf8');

assert.match(common, /\/assets\/chat\/job-queue\.js\?v=20260927-unified-queue-v1/);
assert.match(common, /mlx-unified-job-queue/);

assert.match(queue, /sidebarJobsButton/);
assert.match(queue, /\/api\/system\/job-queue\?limit=40/);
assert.match(queue, /\/api\/mlx\/batch/);
assert.match(queue, /queue_position/);
assert.match(queue, /active_count/);
assert.match(queue, /waiting_count/);
assert.match(queue, /encodeURIComponent\(job\.kind\)/);
assert.match(queue, /\/cancel'/);
assert.match(queue, /setInterval/);
assert.match(queue, /2000/);
assert.match(queue, /stopImmediatePropagation/);
assert.match(queue, /window\.MLXJobQueue/);

assert.match(proxy, /@app\.get\("\/api\/system\/job-queue"\)/);
assert.match(proxy, /@app\.post\("\/api\/system\/job-queue\/\{kind\}\/\{job_id\}\/cancel"\)/);
assert.match(proxy, /media_queue\.ensure_worker\(\)/);

assert.match(imageApi, /media_queue\.enqueue\("image", payload\)/);
assert.match(videoApi, /media_queue\.enqueue\("video", payload\)/);
assert.match(imageApi, /media_queue\.cancel_chat/);

console.log('Unified media queue API, routing, polling UI, and cancellation wiring passed.');
