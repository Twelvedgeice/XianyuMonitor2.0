import pytest
from src.domain.models.task import Task, TaskUpdate

@pytest.mark.parametrize("strategy", ["fixed", "rotate"])
@pytest.mark.parametrize("patch", [{"is_running": True}, {"is_running": False}, {"enabled": True}, {"max_price": "3000"}])
def test_status_update_preserves_account(strategy, patch):
    task = Task(enabled=True, max_pages=3, personal_only=True, ai_prompt_base_file="", ai_prompt_criteria_file="", id=0, task_name="test", keyword="test", account_strategy=strategy,
                account_state_file="state/personal.json", cron="*/30 * * * * *")
    update = TaskUpdate(**patch)
    assert update.model_dump(exclude_unset=True) == patch
    for _ in range(3):
        task = task.apply_update(update)
        assert task.account_state_file == "state/personal.json"
        assert task.account_strategy == strategy
        assert task.cron == "*/30 * * * * *"
