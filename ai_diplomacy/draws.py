"""Private, simultaneous draw-ballot collection for league games."""

import asyncio
import json

from diplomacy.utils import strings

from .utils import run_llm_and_log


async def collect_draw_votes(game, agents, log_file_path: str) -> bool:
    """Collect one private yes/no ballot from every surviving power.

    Votes are not added to press or exposed to other agents. A provider failure
    is re-raised so the worker pauses rather than inventing a strategic ballot.
    """
    active = [power for power in agents if not game.powers[power].is_eliminated()]
    board = json.dumps(game.get_state(), sort_keys=True)

    async def ballot(power: str):
        agent = agents[power]
        prompt = (
            "DRAW BALLOT (private). You are not told other ballots. A draw ends the game for all surviving powers. "
            "Return only JSON: {\"draw\": true} or {\"draw\": false}.\n"
            f"Power: {power}\nBoard: {board}\nPrivate memory: {agent.format_private_diary_for_prompt()}"
        )
        response = await run_llm_and_log(agent.client, prompt, power, game.current_short_phase, "draw_ballot")
        try:
            value = json.loads(response)
            return power, bool(value.get("draw") is True)
        except (json.JSONDecodeError, AttributeError):
            return power, False

    votes = await asyncio.gather(*(ballot(power) for power in active))
    for power, vote in votes:
        game.powers[power].vote = strings.YES if vote else strings.NO
    if game.has_draw_vote():
        game.draw()
        return True
    game.clear_vote()
    return False
