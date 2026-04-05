from src.storage.models import TaskStore


class TestTaskStore:
    def test_create_and_retrieve_task(self, task_store: TaskStore):
        task_id = task_store.create_task(
            title="Review PR #42",
            description="Alice asked for a review",
            source_type="slack",
            source_id="1234567890.123456",
            source_channel="engineering",
            assigned_to="Bob",
            priority="high",
        )
        assert task_id is not None

        tasks = task_store.get_open_tasks()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Review PR #42"
        assert tasks[0]["assigned_to"] == "Bob"
        assert tasks[0]["priority"] == "high"
        assert tasks[0]["status"] == "open"

    def test_update_task_status(self, task_store: TaskStore):
        task_id = task_store.create_task(
            title="Fix bug",
            description="Critical bug in login",
            source_type="gmail",
            source_id="msg-abc-123",
        )

        task_store.update_task_status(task_id, "done")

        tasks = task_store.get_open_tasks()
        assert len(tasks) == 0

    def test_get_tasks_by_source(self, task_store: TaskStore):
        task_store.create_task(
            title="Slack task",
            description="From Slack",
            source_type="slack",
            source_id="ts-1",
        )
        task_store.create_task(
            title="Email task",
            description="From Gmail",
            source_type="gmail",
            source_id="msg-1",
        )

        slack_tasks = task_store.get_tasks_by_source("slack")
        assert len(slack_tasks) == 1
        assert slack_tasks[0]["title"] == "Slack task"

        gmail_tasks = task_store.get_tasks_by_source("gmail")
        assert len(gmail_tasks) == 1
        assert gmail_tasks[0]["title"] == "Email task"

    def test_message_deduplication(self, task_store: TaskStore):
        assert not task_store.is_message_processed("slack", "ts-1")

        task_store.mark_message_processed("slack", "ts-1")
        assert task_store.is_message_processed("slack", "ts-1")

        # Different source type with same ID is not a duplicate
        assert not task_store.is_message_processed("gmail", "ts-1")

    def test_duplicate_mark_is_idempotent(self, task_store: TaskStore):
        task_store.mark_message_processed("slack", "ts-1")
        # Should not raise
        task_store.mark_message_processed("slack", "ts-1")
        assert task_store.is_message_processed("slack", "ts-1")

    def test_gmail_history_id(self, task_store: TaskStore):
        assert task_store.get_gmail_history_id() is None

        task_store.set_gmail_history_id("12345")
        assert task_store.get_gmail_history_id() == "12345"

        task_store.set_gmail_history_id("67890")
        assert task_store.get_gmail_history_id() == "67890"

    def test_task_defaults(self, task_store: TaskStore):
        task_id = task_store.create_task(
            title="Minimal task",
            description="No optional fields",
            source_type="slack",
            source_id="ts-minimal",
        )

        tasks = task_store.get_open_tasks()
        assert len(tasks) == 1
        task = tasks[0]
        assert task["priority"] == "medium"
        assert task["status"] == "open"
        assert task["assigned_to"] is None
        assert task["due_date"] is None
        assert task["source_channel"] is None
