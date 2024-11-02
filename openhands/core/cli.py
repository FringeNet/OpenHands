import asyncio
import logging
import os
from typing import Type

from termcolor import colored

import openhands.agenthub  # noqa F401 (we import this to get the agents registered)
from openhands import __version__
from openhands.controller import AgentController
from openhands.controller.agent import Agent
from openhands.core.config import (
    get_parser,
    load_app_config,
)
from openhands.core.logger import openhands_logger as logger
from openhands.core.schema import AgentState
from openhands.events import EventSource, EventStream, EventStreamSubscriber
from openhands.events.action import (
    Action,
    ChangeAgentStateAction,
    CmdRunAction,
    FileEditAction,
    MessageAction,
)
from openhands.events.event import Event
from openhands.events.observation import (
    AgentStateChangedObservation,
    CmdOutputObservation,
    FileEditObservation,
)
from openhands.llm.llm import LLM
from openhands.runtime import get_runtime_cls
from openhands.runtime.base import Runtime
from openhands.storage import get_file_store


def display_message(message: str):
    print(colored('🤖 ' + message + '\n', 'yellow'))


def display_command(command: str):
    print('❯ ' + colored(command + '\n', 'green'))


def display_command_output(output: str):
    lines = output.split('\n')
    for line in lines:
        if line.startswith('[Python Interpreter') or line.startswith('openhands@'):
            # TODO: clean this up once we clean up terminal output
            continue
        print(colored(line, 'blue'))
    print('\n')


def display_file_edit(event: FileEditAction | FileEditObservation):
    print(colored(str(event), 'green'))


def display_event(event: Event):
    if isinstance(event, Action):
        if hasattr(event, 'thought'):
            display_message(event.thought)
    if isinstance(event, MessageAction):
        if event.source == EventSource.AGENT:
            display_message(event.content)
    if isinstance(event, CmdRunAction):
        display_command(event.command)
    if isinstance(event, CmdOutputObservation):
        display_command_output(event.content)
    if isinstance(event, FileEditAction):
        display_file_edit(event)
    if isinstance(event, FileEditObservation):
        if event.source == EventSource.ENVIRONMENT:
            # For file watcher events, use a different color and format
            if not event.prev_exist:
                print(colored(f'📝 File created: {event.path}', 'cyan'))
            elif event.new_content == "":
                print(colored(f'🗑️  File deleted: {event.path}', 'red'))
            else:
                print(colored(f'✏️  File modified: {event.path}', 'yellow'))
        else:
            # For regular file edits, use the standard display
            display_file_edit(event)


async def main():
    """Runs the agent in CLI mode"""

    parser = get_parser()
    # Add the version argument
    parser.add_argument(
        '-v',
        '--version',
        action='version',
        version=f'{__version__}',
        help='Show the version number and exit',
        default=None,
    )
    # Add the watch directory argument
    parser.add_argument(
        '-w',
        '--watch',
        type=str,
        help='Directory to watch for changes',
        metavar='DIR',
        default=None,
    )
    args = parser.parse_args()

    if args.version:
        print(f'OpenHands version: {__version__}')
        return

    logger.setLevel(logging.WARNING)
    config = load_app_config(config_file=args.config_file)
    sid = 'cli'

    # Set up file watcher if --watch is specified
    if args.watch:
        from openhands.intent.watch import FileWatcher
        watch_dir = os.path.abspath(args.watch)
        if not os.path.isdir(watch_dir):
            print(f"Error: Watch directory '{args.watch}' does not exist or is not a directory")
            return
        print(f"Starting file watcher for directory: {watch_dir}")
        file_watcher = FileWatcher(directory=watch_dir, event_stream=event_stream)
        file_watcher.start()

    agent_cls: Type[Agent] = Agent.get_cls(config.default_agent)
    agent_config = config.get_agent_config(config.default_agent)
    llm_config = config.get_llm_config_from_agent(config.default_agent)
    agent = agent_cls(
        llm=LLM(config=llm_config),
        config=agent_config,
    )

    file_store = get_file_store(config.file_store, config.file_store_path)
    event_stream = EventStream(sid, file_store)

    runtime_cls = get_runtime_cls(config.runtime)
    runtime: Runtime = runtime_cls(  # noqa: F841
        config=config,
        event_stream=event_stream,
        sid=sid,
        plugins=agent_cls.sandbox_plugins,
    )
    await runtime.connect()

    controller = AgentController(
        agent=agent,
        max_iterations=config.max_iterations,
        max_budget_per_task=config.max_budget_per_task,
        agent_to_llm_config=config.get_agent_to_llm_config_map(),
        event_stream=event_stream,
    )

    if controller is not None:
        controller.agent_task = asyncio.create_task(controller.start_step_loop())

    async def prompt_for_next_task():
        next_message = input('How can I help? >> ')
        if next_message == 'exit':
            event_stream.add_event(
                ChangeAgentStateAction(AgentState.STOPPED), EventSource.ENVIRONMENT
            )
            return
        action = MessageAction(content=next_message)
        event_stream.add_event(action, EventSource.USER)

    async def on_event(event: Event):
        display_event(event)
        if isinstance(event, AgentStateChangedObservation):
            if event.agent_state == AgentState.ERROR:
                print('An error occurred. Please try again.')
            if event.agent_state in [
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.ERROR,
            ]:
                await prompt_for_next_task()

    event_stream.subscribe(EventStreamSubscriber.MAIN, on_event)

    await prompt_for_next_task()

    while controller.state.agent_state not in [
        AgentState.STOPPED,
    ]:
        await asyncio.sleep(1)  # Give back control for a tick, so the agent can run

    print('Exiting...')
    await controller.close()
    
    # Stop file watcher if it was started
    if args.watch and 'file_watcher' in locals():
        print('Stopping file watcher...')
        file_watcher.stop()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        pass
