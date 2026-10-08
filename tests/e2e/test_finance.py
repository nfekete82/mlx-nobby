"""Production Finance chat assets, tool transport and searchable help."""
import pytest
from playwright.sync_api import expect
from .test_acceptance import send, open_sidebar


@pytest.mark.parametrize('language', ['de', 'en'])
def test_finance_quote_and_searchable_help(ui, language):
    page, agent, _ = ui
    page.evaluate('(language) => window.MLXI18n.setLanguage(language)', language)
    send(page, 'Wie steht AMD gerade?')
    output = page.locator('.message.assistant .message-content').last
    expect(output).to_contain_text('NASDAQ')
    expect(output).to_contain_text('USD')
    expect(output).to_contain_text('VERALTET' if language == 'de' else 'STALE')
    expect(output).to_contain_text('Regular' if page.evaluate('window.MLXI18n?.getLanguage?.()') == 'en' else 'Regulär')
    assert agent.count('/api/runtime/chat/stream', 'POST') == 0
    assert agent.count('/api/chat/actions', 'POST') == 1
    open_sidebar(page)
    page.locator('#mlxSidebarHelpButton').click()
    page.locator('#mlxHelpSearch').fill('Finance')
    expect(page.locator('#mlxHelpPanel')).to_contain_text('Finanzanalyse' if language == 'de' else 'Finance Intelligence')
    page.locator('#mlxHelpSearch').fill('NASDAQ')
    expect(page.locator('#mlxHelpPanel')).to_contain_text('Finanzanalyse' if language == 'de' else 'Finance Intelligence')
    page.locator('[data-help-topic="finance"]').click()
    expect(page.locator('#mlxHelpPanel')).to_contain_text('Yahoo Finance')
    expect(page.locator('#mlxHelpPanel')).to_contain_text('insufficient data')
