from src.ai.tools import (
    set_tool_dependencies,
    _post_slack_update,
    _save_task,
    _list_open_tasks,
)


class TestAITools:
    def test_post_slack_update(self, mock_slack_bot, task_store):
        set_tool_dependencies(mock_slack_bot, task_store)

        result = _post_slack_update(channel_id="C123", message="Test update")

        assert "posted" in result.lower()
        assert len(mock_slack_bot.posted_messages) == 1
        assert mock_slack_bot.posted_messages[0]["channel_id"] == "C123"
        assert mock_slack_bot.posted_messages[0]["text"] == "Test update"

    def test_save_task(self, mock_slack_bot, task_store):
        set_tool_dependencies(mock_slack_bot, task_store)

        result = _save_task(
            title="Review PR",
            description="Alice needs a review",
            source_type="slack",
            source_id="ts-1",
            source_channel="engineering",
            assigned_to="Bob",
            priority="high",
            due_date="2026-03-01",
        )

        assert "saved" in result.lower()
        tasks = task_store.get_open_tasks()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Review PR"
        assert tasks[0]["assigned_to"] == "Bob"

    def test_save_task_with_empty_optional_fields(self, mock_slack_bot, task_store):
        set_tool_dependencies(mock_slack_bot, task_store)

        result = _save_task(
            title="General task",
            description="No assignee",
            source_type="gmail",
            source_id="msg-1",
            source_channel="",
            assigned_to="",
            priority="medium",
            due_date="",
        )

        assert "saved" in result.lower()
        tasks = task_store.get_open_tasks()
        assert len(tasks) == 1
        assert tasks[0]["assigned_to"] is None
        assert tasks[0]["due_date"] is None

    def test_list_open_tasks_empty(self, mock_slack_bot, task_store):
        set_tool_dependencies(mock_slack_bot, task_store)

        result = _list_open_tasks()
        assert "no open tasks" in result.lower()

    def test_list_open_tasks_with_data(self, mock_slack_bot, task_store):
        set_tool_dependencies(mock_slack_bot, task_store)

        task_store.create_task(
            title="Test task",
            description="A test",
            source_type="slack",
            source_id="ts-1",
        )

        result = _list_open_tasks()
        assert "Test task" in result
