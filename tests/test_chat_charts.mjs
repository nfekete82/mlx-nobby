import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('frontend/assets/chat/charts.js', 'utf8');
const html = fs.readFileSync('frontend/chat.html', 'utf8');
const rendering = fs.readFileSync('frontend/assets/chat/rendering.js', 'utf8');
const generation = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const window = {};
vm.runInNewContext(source, {window, Intl, Date, document: {}});
const api = window.MLXCharts;
const fixture = (labels, values, extra = {}) => ({title:'Values',type:'auto',data:labels.map((label,i)=>({label,value:values[i]})),...extra});

test('automatic representation: dates, categories, tables, shares and KPIs', () => {
  assert.equal(api.normalize(fixture(['2026-01','2026-02','2026-03','2026-04'],[1,3,4,5])).type,'line');
  assert.equal(api.normalize(fixture(['a','b','c','d'],[1,3,4,5])).type,'bar');
  assert.equal(api.normalize(fixture(Array.from({length:20},(_,i)=>'x'+i),Array(20).fill(2))).type,'table');
  assert.equal(api.normalize(fixture(['a','b','c','d'],[20,30,20,30],{part_of_whole:true})).type,'donut');
  assert.equal(api.normalize(fixture(['a','b'],[10,20])).type,'kpi');
});

test('reject malformed or unsafe numeric data, preserve original code when invalid', () => {
  assert.equal(api.normalize({type:'pie',data:[{label:'a',value:2}]}),null);
  assert.equal(api.normalize({type:'line',data:[{label:'A',value:'1'}]}),null);
  assert.equal(api.normalize({type:'line',data:[{label:'A',value:Infinity}]}),null);
  assert.equal(api.normalize({type:'donut',data:[{label:'A',value:-1}]}),null);
  assert.equal(api.normalize(fixture(Array(121).fill('a'),Array(121).fill(1))),null);
  assert.match(source,/textContent\s*=/);
  assert.doesNotMatch(source,/innerHTML\s*=/);
});

test('CSV escaping and frontend integration', () => {
  const spec=api.normalize(fixture(['a,"quoted"','b'],[1,2]));
  assert.match(api.csv(spec), /"a,""quoted"""/);
  assert.match(html,/charts\.js\?v=1-11-2/);
  assert.match(html,/charts\.css\?v=1-11-0/);
  assert.match(rendering,/MLXCharts\?\.enhance\(answer\)/);
  assert.match(generation,/nobby-chart JSON block/);
});

test('model JSON fences are recognized without proprietary language tag', () => {
  assert.match(source, /language-json/);
  assert.match(source, /querySelectorAll\("pre > code"\)/);
  assert.match(source, /Array\.isArray\(parsed\.data\)/);
  assert.doesNotMatch(source, /JSON\.parse\(code\.innerHTML\)/);
});

test('line and bar charts show accessible category and numeric labels', () => {
  assert.match(source, /function labelAt|const labelAt=/);
  assert.match(source, /short\(labels\[i\]\)/);
  assert.match(source, /format\(values\[i\]\)/);
  assert.match(source, /format\(v\)/);
});
