import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InternalError,
    InvalidParamsError,
    Part,
    Task,
    TaskState,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import (
    new_agent_text_message,
    new_task,
)
from a2a.utils.errors import ServerError

from app.agent import process_math_request


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MathAgentExecutor(AgentExecutor):
    """Math Agent Executor for A2A SDK integration"""

    def __init__(self):
        pass  # No need to initialize agent since we use the global function

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        error = self._validate_request(context)
        if error:
            raise ServerError(error=InvalidParamsError())

        query = context.get_user_input()
        task = context.current_task
        if not task:
            if context.message:
                task = new_task(context.message)
                await event_queue.enqueue_event(task)
            else:
                raise ServerError(error=InvalidParamsError())
        updater = TaskUpdater(event_queue, task.id, task.contextId)
        
        try:
            # Process the mathematical request
            result = await process_math_request(query)
            
            # Add the result as an artifact and complete the task
            await updater.add_artifact(
                [Part(root=TextPart(text=result))],
                name='math_result',
            )
            await updater.complete()

        except Exception as e:
            logger.error(f'An error occurred while processing math request: {e}')
            raise ServerError(error=InternalError()) from e

    def _validate_request(self, context: RequestContext) -> bool:
        return False

    async def cancel(
        self, request: RequestContext, event_queue: EventQueue
    ) -> Task | None:
        raise ServerError(error=UnsupportedOperationError()) 