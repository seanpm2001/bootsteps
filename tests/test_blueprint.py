from unittest.mock import call

import pytest
import trio
from asynctest import MagicMock, Mock

from bootsteps import AsyncStep, Blueprint
from bootsteps.blueprint import BlueprintState, ExecutionOrder
from tests.mocks import TrioCoroutineMock, create_mock_step, create_start_stop_mock_step


@pytest.fixture
def mock_execution_order_strategy_class():
    return MagicMock(name="ExecutionOrder", spec_set=ExecutionOrder)


@pytest.fixture(autouse=True)
def mock_inspect_isawaitable(mocker):
    return mocker.patch(
        "bootsteps.blueprint.inspect.isawaitable",
        side_effect=lambda o: isinstance(o, TrioCoroutineMock),
    )


def assert_parallelized_steps_are_in_order(
    actual_execution_order, expected_execution_order
):
    __tracebackhide__ = True

    begin = 0

    # Test that all the steps were parallelized in the same order
    for steps in expected_execution_order:
        end = begin + len(steps)
        assert sorted(steps) == sorted(actual_execution_order[begin:end])
        begin = end

    # Ensure no further calls were made
    assert not actual_execution_order[begin:]


def test_init(bootsteps_graph, mock_execution_order_strategy_class):
    b = Blueprint(
        bootsteps_graph,
        name="Test",
        execution_order_strategy_class=mock_execution_order_strategy_class,
    )

    assert b.name == "Test"
    assert b._steps == bootsteps_graph
    assert b.state == BlueprintState.INITIALIZED
    assert b.execution_order_strategy_class == mock_execution_order_strategy_class


async def test_blueprint_start(bootsteps_graph, mock_execution_order_strategy_class):
    mock_step1 = create_mock_step("step1")
    mock_step2 = create_start_stop_mock_step("step2")
    mock_step3 = create_mock_step("step3")
    mock_step4 = create_start_stop_mock_step("step4", mock_class=TrioCoroutineMock)
    mock_step5 = create_mock_step("step5")
    mock_step6 = create_mock_step("step6", spec=AsyncStep, mock_class=TrioCoroutineMock)

    # We're using a parent mock simply to record the order of calls to different
    # steps
    m = Mock()
    m.attach_mock(mock_step1, "mock_step1")
    m.attach_mock(mock_step2, "mock_step2")
    m.attach_mock(mock_step3, "mock_step3")
    m.attach_mock(mock_step4, "mock_step4")
    m.attach_mock(mock_step5, "mock_step5")
    m.attach_mock(mock_step6, "mock_step6")

    expected_execution_order = [
        [m.mock_step1, m.mock_step2],
        [m.mock_step3, m.mock_step4, m.mock_step5],
        [m.mock_step6],
    ]
    mock_iterator = MagicMock()
    mock_iterator.__iter__.return_value = expected_execution_order
    mock_execution_order_strategy_class.return_value = mock_iterator

    blueprint = Blueprint(
        bootsteps_graph,
        name="Test",
        execution_order_strategy_class=mock_execution_order_strategy_class,
    )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(blueprint.start)

        with trio.fail_after(1):
            assert (
                await blueprint.state_changes_receive_channel.receive()
                == BlueprintState.RUNNING
            )
        with trio.fail_after(1):
            assert (
                await blueprint.state_changes_receive_channel.receive()
                == BlueprintState.COMPLETED
            )

    mock_execution_order_strategy_class.assert_called_once_with(blueprint._steps)

    assert_parallelized_steps_are_in_order(
        m.method_calls,
        [
            [call.mock_step1(), call.mock_step2.start()],
            [call.mock_step3(), call.mock_step4.start(), call.mock_step5()],
            [call.mock_step6()],
        ],
    )

    mock_step6.assert_awaited_once_with()
    mock_step4.start.assert_awaited_once_with()


async def test_blueprint_start_failure(
    bootsteps_graph, mock_execution_order_strategy_class
):
    mock_step1 = create_mock_step("step1")
    mock_step1.side_effect = expected_exception = RuntimeError("Expected Failure")
    mock_step2 = create_start_stop_mock_step("step2")
    mock_step3 = create_mock_step("step3")
    mock_step4 = create_start_stop_mock_step("step4", mock_class=TrioCoroutineMock)
    mock_step5 = create_mock_step("step5")
    mock_step6 = create_mock_step("step6", spec=AsyncStep, mock_class=TrioCoroutineMock)

    # We're using a parent mock simply to record the order of calls to different
    # steps
    m = Mock()
    m.attach_mock(mock_step1, "mock_step1")
    m.attach_mock(mock_step2, "mock_step2")
    m.attach_mock(mock_step3, "mock_step3")
    m.attach_mock(mock_step4, "mock_step4")
    m.attach_mock(mock_step5, "mock_step5")
    m.attach_mock(mock_step6, "mock_step6")

    expected_execution_order = [
        [m.mock_step1, m.mock_step2],
        [m.mock_step3, m.mock_step4, m.mock_step5],
        [m.mock_step6],
    ]
    mock_iterator = MagicMock()
    mock_iterator.__iter__.return_value = expected_execution_order
    mock_execution_order_strategy_class.return_value = mock_iterator

    blueprint = Blueprint(
        bootsteps_graph,
        name="Test",
        execution_order_strategy_class=mock_execution_order_strategy_class,
    )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(blueprint.start)

    with trio.fail_after(1):
        assert (
            await blueprint.state_changes_receive_channel.receive()
            == BlueprintState.RUNNING
        )

    with trio.fail_after(1):
        assert await blueprint.state_changes_receive_channel.receive() == (
            BlueprintState.FAILED,
            expected_exception,
        )

    mock_execution_order_strategy_class.assert_called_once_with(blueprint._steps)

    assert_parallelized_steps_are_in_order(
        m.method_calls, [[call.mock_step1(), call.mock_step2.start()]]
    )
    mock_step3.assert_not_called()
    mock_step4.start.assert_not_called()
    mock_step5.assert_not_called()
    mock_step6.assert_not_called()


async def test_blueprint_stop(bootsteps_graph, mock_execution_order_strategy_class):
    mock_step1 = create_mock_step("step1")
    mock_step2 = create_start_stop_mock_step("step2")
    mock_step3 = create_mock_step("step3")
    mock_step4 = create_start_stop_mock_step("step4", mock_class=TrioCoroutineMock)
    mock_step5 = create_mock_step("step5")
    mock_step6 = create_mock_step("step6", spec=AsyncStep, mock_class=TrioCoroutineMock)

    # We're using a parent mock simply to record the order of calls to different
    # steps
    m = Mock()
    m.attach_mock(mock_step1, "mock_step1")
    m.attach_mock(mock_step2, "mock_step2")
    m.attach_mock(mock_step3, "mock_step3")
    m.attach_mock(mock_step4, "mock_step4")
    m.attach_mock(mock_step5, "mock_step5")
    m.attach_mock(mock_step6, "mock_step6")

    expected_execution_order = [
        [m.mock_step1, m.mock_step2],
        [m.mock_step3, m.mock_step4, m.mock_step5],
        [m.mock_step6],
    ]
    mock_iterator = MagicMock()
    reversed_func = Mock(return_value=reversed(expected_execution_order))
    mock_iterator.__reversed__ = reversed_func
    mock_iterator.__iter__.return_value = expected_execution_order
    mock_execution_order_strategy_class.return_value = mock_iterator

    blueprint = Blueprint(
        bootsteps_graph,
        name="Test",
        execution_order_strategy_class=mock_execution_order_strategy_class,
    )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(blueprint.stop)

        with trio.fail_after(1):
            assert (
                await blueprint.state_changes_receive_channel.receive()
                == BlueprintState.TERMINATING
            )
        with trio.fail_after(1):
            assert (
                await blueprint.state_changes_receive_channel.receive()
                == BlueprintState.TERMINATED
            )

    mock_execution_order_strategy_class.assert_called_once_with(blueprint._steps)

    assert_parallelized_steps_are_in_order(
        m.method_calls, [[call.mock_step4.stop()], [call.mock_step2.stop()]]
    )

    mock_step4.stop.assert_awaited_once_with()

    mock_step1.assert_not_called()
    mock_step3.assert_not_called()
    mock_step5.assert_not_called()
    mock_step6.assert_not_called()


async def test_blueprint_stop_failure(
    bootsteps_graph, mock_execution_order_strategy_class
):
    mock_step1 = create_mock_step("step1")
    mock_step2 = create_start_stop_mock_step("step2")
    mock_step3 = create_mock_step("step3")
    mock_step4 = create_start_stop_mock_step("step4", mock_class=TrioCoroutineMock)
    mock_step4.stop.side_effect = expected_exception = RuntimeError("Expected Failure")
    mock_step5 = create_mock_step("step5")
    mock_step6 = create_mock_step("step6", spec=AsyncStep, mock_class=TrioCoroutineMock)

    # We're using a parent mock simply to record the order of calls to different
    # steps
    m = Mock()
    m.attach_mock(mock_step1, "mock_step1")
    m.attach_mock(mock_step2, "mock_step2")
    m.attach_mock(mock_step3, "mock_step3")
    m.attach_mock(mock_step4, "mock_step4")
    m.attach_mock(mock_step5, "mock_step5")
    m.attach_mock(mock_step6, "mock_step6")

    expected_execution_order = [
        [m.mock_step1, m.mock_step2],
        [m.mock_step3, m.mock_step4, m.mock_step5],
        [m.mock_step6],
    ]
    mock_iterator = MagicMock()
    mock_iterator.__iter__.return_value = expected_execution_order
    reversed_func = Mock(return_value=reversed(expected_execution_order))
    mock_iterator.__reversed__ = reversed_func
    mock_execution_order_strategy_class.return_value = mock_iterator

    blueprint = Blueprint(
        bootsteps_graph,
        name="Test",
        execution_order_strategy_class=mock_execution_order_strategy_class,
    )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(blueprint.stop)

    with trio.fail_after(1):
        assert (
            await blueprint.state_changes_receive_channel.receive()
            == BlueprintState.TERMINATING
        )

    with trio.fail_after(1):
        assert await blueprint.state_changes_receive_channel.receive() == (
            BlueprintState.FAILED,
            expected_exception,
        )

    mock_execution_order_strategy_class.assert_called_once_with(blueprint._steps)

    assert_parallelized_steps_are_in_order(m.method_calls, [[call.mock_step4.stop()]])

    mock_step1.assert_not_called()
    mock_step2.stop.assert_not_called()
    mock_step3.assert_not_called()
    mock_step5.assert_not_called()
    mock_step6.assert_not_called()


async def test_blueprint_async_context_manager(
    bootsteps_graph, mock_execution_order_strategy_class
):
    mock_step1 = create_mock_step("step1")
    mock_step2 = create_start_stop_mock_step("step2")
    mock_step3 = create_mock_step("step3")
    mock_step4 = create_start_stop_mock_step("step4", mock_class=TrioCoroutineMock)
    mock_step5 = create_mock_step("step5")
    mock_step6 = create_mock_step("step6", spec=AsyncStep, mock_class=TrioCoroutineMock)

    # We're using a parent mock simply to record the order of calls to different
    # steps
    m = Mock()
    m.attach_mock(mock_step1, "mock_step1")
    m.attach_mock(mock_step2, "mock_step2")
    m.attach_mock(mock_step3, "mock_step3")
    m.attach_mock(mock_step4, "mock_step4")
    m.attach_mock(mock_step5, "mock_step5")
    m.attach_mock(mock_step6, "mock_step6")

    expected_execution_order = [
        [m.mock_step1, m.mock_step2],
        [m.mock_step3, m.mock_step4, m.mock_step5],
        [m.mock_step6],
    ]
    mock_iterator = MagicMock()
    reversed_func = Mock(return_value=reversed(expected_execution_order))
    mock_iterator.__reversed__ = reversed_func
    mock_iterator.__iter__.return_value = expected_execution_order
    mock_execution_order_strategy_class.return_value = mock_iterator

    blueprint = Blueprint(
        bootsteps_graph,
        name="Test",
        execution_order_strategy_class=mock_execution_order_strategy_class,
    )

    async with blueprint:
        with trio.fail_after(1):
            assert (
                await blueprint.state_changes_receive_channel.receive()
                == BlueprintState.RUNNING
            )
        with trio.fail_after(1):
            assert (
                await blueprint.state_changes_receive_channel.receive()
                == BlueprintState.COMPLETED
            )

    with trio.fail_after(1):
        assert (
            await blueprint.state_changes_receive_channel.receive()
            == BlueprintState.TERMINATING
        )
    with trio.fail_after(1):
        assert (
            await blueprint.state_changes_receive_channel.receive()
            == BlueprintState.TERMINATED
        )

    assert_parallelized_steps_are_in_order(
        m.method_calls,
        [
            [call.mock_step1(), call.mock_step2.start()],
            [call.mock_step3(), call.mock_step4.start(), call.mock_step5()],
            [call.mock_step6()],
            [call.mock_step4.stop()],
            [call.mock_step2.stop()],
        ],
    )

    mock_step6.assert_awaited_once_with()
    mock_step4.start.assert_awaited_once_with()
    mock_step4.stop.assert_awaited_once_with()
