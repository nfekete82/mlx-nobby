import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const src = fs.readFileSync('frontend/assets/chat/generation.js', 'utf8');
const start = src.indexOf('function shouldResumeChatAfterEmptySearch(');
const end = src.indexOf('\nfunction gt(', start);
assert.ok(start > -1 && end > start);
const helper = vm.runInNewContext(src.slice(start, end) + '\nshouldResumeChatAfterEmptySearch');

const web = (data, status='completed', tool='web_search') => ({tool, status, data});
test('Agent-certified empty personal searches resume chat', () => {
    assert.equal(helper(web({results:[],empty_search_chat_fallback:true})), true);
    assert.equal(helper(web({results:[]})), false);
    assert.equal(helper(web({results:[],empty_search_chat_fallback:false})), false);
});
test('External research, weather and news never fall back without verified approval', () => {
    assert.equal(helper(web({results:[],weather_forecast:{status:'available'},
      empty_search_chat_fallback:true})), false);
    assert.equal(helper(web({results:[],news_digest:{answer:'News'},
      empty_search_chat_fallback:true})), false);
    assert.equal(helper(web({results:[{title:'source'}],
      empty_search_chat_fallback:true})), false);
    assert.equal(helper(web({results:[],empty_search_chat_fallback:true}, 'failed')), false);
    assert.equal(helper(web({results:[],empty_search_chat_fallback:true}, 'completed', 'weather')), false);
});
test('Empty web tool recovery resumes inference before generic empty answer', () => {
    const branch = src.slice(src.indexOf('if (!results.length) {'), src.indexOf('const searchContext ='));
    assert.match(branch, /shouldResumeChatAfterEmptySearch\(toolResult\)/);
    assert.match(branch, /await generateAssistant\(session\)/);
    assert.match(branch, /web_search_no_results/);
});
