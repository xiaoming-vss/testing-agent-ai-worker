import unittest

from testing_agent_ai_worker.nanobot.runner import run_demo


class _FakeResult:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeBot:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def __aenter__(self) -> "_FakeBot":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run(self, message: str, session_key: str) -> _FakeResult:
        self.calls.append({"message": message, "session_key": session_key})
        return _FakeResult("demo reply")


class _FakeFactory:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, str | None] | None = None
        self.bot = _FakeBot()

    def __call__(self, **kwargs):
        self.last_kwargs = kwargs
        return self.bot


class RunDemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_demo_passes_message_and_session_key(self) -> None:
        factory = _FakeFactory()

        result = await run_demo(
            message="hello",
            session_key="demo:session",
            from_config=factory,
        )

        self.assertEqual(result, "demo reply")
        self.assertEqual(
            factory.bot.calls,
            [{"message": "hello", "session_key": "demo:session"}],
        )

    async def test_run_demo_passes_config_path_and_workspace(self) -> None:
        factory = _FakeFactory()

        await run_demo(
            message="hello",
            session_key="demo:session",
            config_path="D:/tmp/config.json",
            workspace="D:/tmp/workspace",
            from_config=factory,
        )

        self.assertEqual(
            factory.last_kwargs,
            {
                "config_path": "D:/tmp/config.json",
                "workspace": "D:/tmp/workspace",
            },
        )


if __name__ == "__main__":
    unittest.main()
