import logging
from typing import Any, Optional

from backend.data.block import (
    Block,
    BlockCategory,
    BlockInput,
    BlockOutput,
    BlockSchema,
    BlockType,
    get_block,
)
from backend.data.execution import ExecutionStatus
from backend.data.model import CredentialsMetaInput, SchemaField
from backend.util import json

logger = logging.getLogger(__name__)


class AgentExecutorBlock(Block):
    class Input(BlockSchema):
        user_id: str = SchemaField(description="User ID")
        graph_id: str = SchemaField(description="Graph ID")
        graph_version: int = SchemaField(description="Graph Version")

        inputs: BlockInput = SchemaField(description="Input data for the graph")
        input_schema: dict = SchemaField(description="Input schema for the graph")
        output_schema: dict = SchemaField(description="Output schema for the graph")

        node_credentials_input_map: Optional[
            dict[str, dict[str, CredentialsMetaInput]]
        ] = SchemaField(default=None, hidden=True)

        @classmethod
        def get_input_schema(cls, data: BlockInput) -> dict[str, Any]:
            return data.get("input_schema", {})

        @classmethod
        def get_input_defaults(cls, data: BlockInput) -> BlockInput:
            return data.get("inputs", {})

        @classmethod
        def get_missing_input(cls, data: BlockInput) -> set[str]:
            required_fields = cls.get_input_schema(data).get("required", [])
            return set(required_fields) - set(data)

        @classmethod
        def get_mismatch_error(cls, data: BlockInput) -> str | None:
            return json.validate_with_jsonschema(cls.get_input_schema(data), data)

    class Output(BlockSchema):
        pass

    def __init__(self):
        super().__init__(
            id="e189baac-8c20-45a1-94a7-55177ea42565",
            description="Executes an existing agent inside your agent",
            input_schema=AgentExecutorBlock.Input,
            output_schema=AgentExecutorBlock.Output,
            block_type=BlockType.AGENT,
            categories={BlockCategory.AGENT},
        )

    def run(self, input_data: Input, **kwargs) -> BlockOutput:
        from backend.data.execution import ExecutionEventType
        from backend.executor import utils as execution_utils

        event_bus = execution_utils.get_execution_event_bus()

        graph_exec = execution_utils.add_graph_execution(
            graph_id=input_data.graph_id,
            graph_version=input_data.graph_version,
            user_id=input_data.user_id,
            inputs=input_data.inputs,
            node_credentials_input_map=input_data.node_credentials_input_map,
        )
        log_id = f"Graph #{input_data.graph_id}-V{input_data.graph_version}, exec-id: {graph_exec.id}"
        logger.info(f"Starting execution of {log_id}")

        for event in event_bus.listen(
            user_id=graph_exec.user_id,
            graph_id=graph_exec.graph_id,
            graph_exec_id=graph_exec.id,
        ):
            if event.event_type == ExecutionEventType.GRAPH_EXEC_UPDATE:
                if event.status in [
                    ExecutionStatus.COMPLETED,
                    ExecutionStatus.TERMINATED,
                    ExecutionStatus.FAILED,
                ]:
                    logger.info(f"Execution {log_id} ended with status {event.status}")
                    break
                else:
                    continue

            logger.debug(
                f"Execution {log_id} produced input {event.input_data} output {event.output_data}"
            )

            if not event.block_id:
                logger.warning(f"{log_id} received event without block_id {event}")
                continue

            block = get_block(event.block_id)
            if not block or block.block_type != BlockType.OUTPUT:
                continue

            output_name = event.input_data.get("name")
            if not output_name:
                logger.warning(f"{log_id} produced an output with no name {event}")
                continue

            for output_data in event.output_data.get("output", []):
                logger.debug(
                    f"Execution {log_id} produced {output_name}: {output_data}"
                )
                yield output_name, output_data
