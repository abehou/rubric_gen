import json

import pytest

from rubric_gen.runtime.agents.codex_completion import TurnCompletionBuffer


def command(method, item, thread="thread", turn="turn"):
    return json.dumps({"method": method, "params": {
        "threadId": thread, "turnId": turn,
        "item": {"type": "commandExecution", "id": item},
    }})


def complete(status="completed", thread="thread", turn="turn"):
    return json.dumps({"method": "turn/completed", "params": {
        "threadId": thread, "turn": {"id": turn, "status": status},
    }})


def test_successful_turn_waits_for_every_issued_command_without_rewriting_payloads():
    buffer = TurnCompletionBuffer()
    for item in ("a", "b"):
        started = command("item/started", item)
        assert buffer.accept(started) == (started,)
    finished = complete()
    assert buffer.accept(finished) == ()
    output = json.dumps({"method": "item/commandExecution/outputDelta", "params": {
        "threadId": "thread", "turnId": "turn", "delta": "late computation output",
    }})
    assert buffer.accept(output) == (output,)
    a = command("item/completed", "a")
    b = command("item/completed", "b")
    assert buffer.accept(a) == (a,)
    assert buffer.accept(b) == (b, finished)


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_unsuccessful_completion_is_not_blocked_by_running_commands(status):
    buffer = TurnCompletionBuffer()
    buffer.accept(command("item/started", "a"))
    finished = complete(status)
    assert buffer.accept(finished) == (finished,)


def test_completion_never_waits_for_another_thread_or_already_finished_command():
    buffer = TurnCompletionBuffer()
    buffer.accept(command("item/started", "a", thread="other"))
    buffer.accept(command("item/started", "b"))
    buffer.accept(command("item/completed", "b"))
    finished = complete()
    assert buffer.accept(finished) == (finished,)
    response = json.dumps({"id": "initialize", "result": {"serverInfo": {}}})
    assert buffer.accept(response) == (response,)
