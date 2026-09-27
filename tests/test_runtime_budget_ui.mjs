import assert from 'node:assert/strict';
import fs from 'node:fs';

const common = fs.readFileSync('frontend/assets/common.js', 'utf8');
const budget = fs.readFileSync('frontend/assets/chat/runtime-budget.js', 'utf8');

assert.match(common, /\/assets\/chat\/runtime-budget\.js\?v=20260927-runtime-budget-v1/);
assert.match(common, /mlx-runtime-budget/);
assert.match(budget, /\/api\/mlx\/system/);
assert.match(budget, /id = 'mlxRuntimeBudget'/);
assert.match(budget, /ELEVATED_FREE_PERCENT = 18/);
assert.match(budget, /CRITICAL_FREE_PERCENT = 8/);
assert.match(budget, /availableGb/);
assert.match(budget, /swapUsedGb/);
assert.match(budget, /mlxGb/);
assert.match(budget, /window\.MLXRuntimeBudget/);
assert.match(budget, /cache: 'no-store'/);
assert.match(budget, /runtime-budget-meter/);

console.log('Runtime budget loader, memory pressure UI, and cache-safe polling passed.');
