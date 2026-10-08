"""Finance APIs share the AgentRuntime registry and its permission engine."""
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from agent.run_state import RunContext
from .contracts import FinanceError
from backend.finance_intent import TOOLS


class FinanceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str = Field(default='', max_length=10000)
    options: dict | None = None
    chat_id: str | None = Field(default=None, min_length=1, max_length=200)


def install_routes(app, registry):
    @app.post('/api/finance/{tool}')
    def finance_request(tool: str, request: FinanceRequest):
        action = 'finance_' + tool
        if action not in TOOLS:
            raise HTTPException(404, detail={'code': 'unknown_finance_tool'})
        try:
            return registry.execute(action, run_context=RunContext.start(chat_id=request.chat_id, user_goal=request.prompt),
                                    goal=request.prompt, options=request.options)
        except FinanceError as exc:
            raise HTTPException(422 if str(exc) in {'invalid_symbol', 'symbol_required', 'market_selection_required',
                 'ambiguous_symbol', 'invalid_quantity', 'duplicate_positions', 'single_symbol_required',
                 'comparison_symbols_required', 'invalid_currency', 'invalid_exchange', 'tracking_owner_required',
                 'invalid_finance_options', 'portfolio_positions_required'} else 503, detail={'code': str(exc)}) from None
        except OSError:
            raise HTTPException(503, detail={'code': 'finance_unavailable'}) from None
