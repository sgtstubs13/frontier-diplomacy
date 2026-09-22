"""Offline regressions for the bugs found during the one-year audit."""
import asyncio
import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from diplomacy import Game
from ai_diplomacy.agent import DiplomacyAgent
from ai_diplomacy.game_history import GameHistory
from ai_diplomacy.utils import gather_stage
from frontier_diplomacy.accounting import BudgetExceeded


def test_stage_settles_other_calls_but_propagates_budget_pause():
    settled = []

    async def denied():
        raise BudgetExceeded('budget exhausted')

    async def already_authorized():
        await asyncio.sleep(0)
        settled.append(True)
        return 'finished'

    async def stage():
        await gather_stage(denied(), already_authorized())

    with pytest.raises(BudgetExceeded):
        asyncio.run(stage())
    assert settled == [True]


def test_initialization_template_contains_parseable_required_schema():
    template = Path('ai_diplomacy/prompts_simple/initial_state_prompt.txt').read_text()
    prompt = template.format(power_name='FRANCE', allowed_labels_str='neutral')
    value = json.loads(prompt[prompt.index('{'):prompt.rindex('}')+1])
    assert isinstance(value['initial_goals'], list)
    assert isinstance(value['initial_relationships'], dict)


def test_reflection_uses_completed_phase_press_without_other_private_messages():
    game = Game()
    history = GameHistory()
    history.add_phase('S1901M')
    history.add_message('S1901M', 'ENGLAND', 'FRANCE', 'OUR_SPRING_AGREEMENT')
    history.add_message('S1901M', 'ITALY', 'GERMANY', 'OTHER_PRIVATE_SECRET')
    history.add_message('S1901M', 'ITALY', 'GLOBAL', 'PUBLIC_SPRING_NEWS')
    game.process()  # Engine is in Fall when reflection on Spring runs.
    history.add_phase(game.current_short_phase)
    history.add_message(game.current_short_phase, 'ENGLAND', 'FRANCE', 'FUTURE_PHASE_MESSAGE')
    agent = SimpleNamespace(power_name='FRANCE', prompts_dir='ai_diplomacy/prompts_simple',
        client=SimpleNamespace(model_name='mock'), goals=[], relationships={},
        format_private_diary_for_prompt=lambda: '', add_diary_entry=Mock())
    call = AsyncMock(return_value='My private note.')
    with patch('ai_diplomacy.agent.run_llm_and_log', call), patch('ai_diplomacy.agent.log_llm_response_async', AsyncMock()):
        asyncio.run(DiplomacyAgent.generate_phase_result_diary_entry(
            agent, game, history, 'phase completed', {}, '', 'S1901M'))
    prompt = call.call_args.kwargs['prompt']
    assert 'OUR_SPRING_AGREEMENT' in prompt
    assert 'PUBLIC_SPRING_NEWS' in prompt
    assert 'OTHER_PRIVATE_SECRET' not in prompt
    assert 'FUTURE_PHASE_MESSAGE' not in prompt
    agent.add_diary_entry.assert_called_once_with('My private note.', 'S1901M')
