import logging
import asyncio
from typing import Dict

from .game_history import GameHistory
from .agent import DiplomacyAgent

logger = logging.getLogger(__name__)


async def planning_phase(
    game,
    agents: Dict[str, DiplomacyAgent],
    game_history: GameHistory,
    model_error_stats,
    log_file_path: str,
):
    """
    Lets each power generate a strategic plan using their DiplomacyAgent.
    """
    logger.info(f"Starting planning phase for {game.current_short_phase}...")
    active_powers = [p_name for p_name, p_obj in game.powers.items() if not p_obj.is_eliminated()]
    eliminated_powers = [p_name for p_name, p_obj in game.powers.items() if p_obj.is_eliminated()]

    logger.info(f"Active powers for planning: {active_powers}")
    if eliminated_powers:
        logger.info(f"Eliminated powers (skipped): {eliminated_powers}")
    else:
        logger.info("No eliminated powers yet.")

    board_state = game.get_state()

    async def get_plan(power_name: str):
        agent = agents[power_name]
        plan = await agent.client.get_plan(
            game, board_state, power_name, game_history, log_file_path,
            agent_goals=agent.goals,
            agent_relationships=agent.relationships,
            agent_private_diary_str=agent.format_private_diary_for_prompt(),
        )
        return power_name, agent, plan

    active = [name for name in active_powers if name in agents]
    results = await asyncio.gather(*(get_plan(name) for name in active), return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error("Planning call failed: %s", result, exc_info=result)
            continue
        power_name, agent, plan_result = result
        if not plan_result or plan_result.startswith("Error:"):
            model_error_stats.setdefault(power_name, {}).setdefault("planning_generation_errors", 0)
            model_error_stats[power_name]["planning_generation_errors"] += 1
            continue
        logger.info("Received planning result from %s.", power_name)
        agent.add_journal_entry(f"Generated plan for {game.current_short_phase}: {plan_result[:100]}...")
        game_history.add_plan(game.current_short_phase, power_name, plan_result)

    logger.info("Planning phase processing complete.")
    return game_history
