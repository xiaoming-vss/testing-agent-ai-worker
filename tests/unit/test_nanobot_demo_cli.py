import unittest

from testing_agent_ai_worker.cli.nanobot_demo import run_cli_demo


class _Printer:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, value: str) -> None:
        self.lines.append(value)


class NanobotDemoCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_cli_demo_forwards_arguments_and_prints_content(self) -> None:
        printer = _Printer()
        captured: dict[str, str | None] = {}

        async def fake_runner(
            *,
            message: str,
            session_key: str,
            config_path: str | None,
            workspace: str | None,
        ) -> str:
            captured.update(
                {
                    "message": message,
                    "session_key": session_key,
                    "config_path": config_path,
                    "workspace": workspace,
                }
            )
            return "demo reply"

        result = await run_cli_demo(
            message="hello",
            session_key="demo:session",
            config_path="D:/tmp/config.json",
            workspace="D:/tmp/workspace",
            runner=fake_runner,
            printer=printer,
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            captured,
            {
                "message": "hello",
                "session_key": "demo:session",
                "config_path": "D:/tmp/config.json",
                "workspace": "D:/tmp/workspace",
            },
        )
        self.assertEqual(printer.lines, ["demo reply"])


if __name__ == "__main__":
    unittest.main()
