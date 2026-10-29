import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const attachments = readFileSync(new URL('../frontend/assets/chat/attachments.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../frontend/chat.html', import.meta.url), 'utf8');
const registry = readFileSync(new URL('../image_registry.py', import.meta.url), 'utf8');
const imageService = readFileSync(new URL('../image_service.py', import.meta.url), 'utf8');
const rendering = readFileSync(new URL('../frontend/assets/chat/rendering.js', import.meta.url), 'utf8');

test('img2img is an explicit edit model, not a global text-to-image setting', () => {
  assert.match(attachments, /model\.capabilities\?\.includes\('image_edit'\)/);
  assert.match(registry, /"img2img"/);
  assert.match(attachments, /select\.value === 'juggernaut-xl'/);
  assert.match(attachments, /delete editOptions\.strength/);
  assert.match(attachments, /strength\.type = 'range'/);
  assert.match(attachments, /strength\.min = '0\.15'/);
  assert.match(attachments, /strength\.max = '0\.85'/);
  assert.match(attachments, /editOptions\.strength = Number\(strength\.value\)/);
  assert.match(attachments, /'steps', 'attachments\.img2img_steps'/);
  assert.match(attachments, /'guidance', 'attachments\.img2img_cfg'/);
  assert.match(attachments, /'seed', 'attachments\.img2img_seed'/);
  assert.match(attachments, /sdxlSampling\.hidden = select\.value !== 'juggernaut-xl'/);
});

test('frontend cache key changes and backend routes through bounded source', () => {
  assert.match(html, /attachments\.js\?v=20261026-eml-consolidated-faq/);
  assert.match(imageService, /prepare_sdxl_img2img_source/);
  assert.match(imageService, /params\["strength"\]/);
  assert.match(imageService, /"strength": params\.get\("strength"\)/);
  assert.match(rendering, /artifact\.strength != null \? 'Strength '/);
  assert.match(html, /rendering\.js\?v=20261029-long-video-sdxl/);
});
