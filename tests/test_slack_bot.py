from src.slack_bot.formatters import format_update_blocks, format_task_list_blocks


class TestFormatters:
    def test_format_update_with_action_items(self):
        blocks = format_update_blocks(
            source_label="Slack #engineering",
            summary="Alice asked Bob to review PR #42.",
            action_items=["Review PR #42", "Update deployment docs"],
        )
        assert len(blocks) == 4  # header, summary, action items, divider
        assert blocks[0]["type"] == "header"
        assert "engineering" in blocks[0]["text"]["text"]
        assert "Alice asked" in blocks[1]["text"]["text"]
        assert "Action Items" in blocks[2]["text"]["text"]
        assert "Review PR #42" in blocks[2]["text"]["text"]

    def test_format_update_without_action_items(self):
        blocks = format_update_blocks(
            source_label="Email from alice@example.com",
            summary="FYI about the upcoming holiday schedule.",
            action_items=[],
        )
        # No action items block
        assert len(blocks) == 3  # header, summary, divider
        assert blocks[0]["type"] == "header"

    def test_format_task_list_with_tasks(self):
        tasks = [
            {
                "title": "Review PR #42",
                "description": "From Alice",
                "priority": "high",
                "assigned_to": "Bob",
                "due_date": "2026-02-25",
            },
            {
                "title": "Update docs",
                "description": "From Slack",
                "priority": "low",
                "assigned_to": None,
                "due_date": None,
            },
        ]
        blocks = format_task_list_blocks(tasks)
        assert blocks[0]["type"] == "header"
        assert "Open Tasks" in blocks[0]["text"]["text"]
        # One section per task + header + divider
        assert len(blocks) == 4

    def test_format_task_list_empty(self):
        blocks = format_task_list_blocks([])
        assert len(blocks) == 1
        assert "No open tasks" in blocks[0]["text"]["text"]
