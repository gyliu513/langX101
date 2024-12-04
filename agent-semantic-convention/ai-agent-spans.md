<!--- Hugo front matter used to generate the website version of this page:
linkTitle: Generative AI traces
--->

# Semantic Conventions for AI Agent Spans

**Status**: [Experimental][DocumentStatus]

<!-- Re-generate TOC with `markdown-toc --no-first-h1 -i` -->

<!-- toc -->

- [Name](#name)
- [AI Agent attributes](#ai-agent-attributes)
- [Capturing inputs and outputs](#capturing-inputs-and-outputs)

<!-- tocstop -->

## SPAN KIND

Each step in an AI Agent workflow is treated as a span.

**Span kind:** SHOULD be `CLIENT`. It MAY be set to `INTERNAL` on spans representing call in an AI Agent workflow.

## Name

AI Agent spans MUST follow the overall [guidelines for span names](https://github.com/open-telemetry/opentelemetry-specification/tree/v1.39.0/specification/trace/api.md#span). The **span name** SHOULD be `{ai_agent.operation.name} {ai_agent.agent.type}`.
Semantic conventions for individual AI Agent systems and frameworks MAY specify different span name format.

- ai_agent.operation.name: The operation being performed (e.g., `workflow.kickoff`,`agent.execution`, `task.execution`, `agent.interaction`).
- ai_agent.agent.type: The type of agent performing the operation (e.g., `CrewAI`, `LangGraph`, `AutoGen`).

## AI Agent attributes

### Common Attributes

The following attributes apply to all spans related to agent operations:

| Attribute                     | Type   | Description                                                      | Example                          |
|-------------------------------|--------|------------------------------------------------------------------|----------------------------------|
| `agentops.agent.id`           | string | Unique identifier for the agent.                                 | `agent-12345`                    |
| `agentops.agent.name`         | string | Human-readable name of the agent.                                | `Data Processor`                 |
| `agentops.agent.type`         | string | Type of the agent (e.g., `CrewAI`, `LangGraph`, `AutoGen`).      | `CrewAI`                         |
| `agentops.session.id`         | string | Unique identifier for the session.                               | `session-67890`                  |
| `agentops.session.project_id` | string | Identifier for the project associated with the session.          | `project-abcde`                  |
| `agentops.session.start_time` | string | Timestamp marking the beginning of the session.                  | `2024-12-04T14:53:01Z`           |
| `agentops.session.end_time`   | string | Timestamp indicating when the session concluded.                 | `2024-12-04T15:53:01Z`           |
| `agentops.session.end_state`  | string | End state of the session (e.g., `success`, `failure`).           | `success`                        |
| `agentops.session.end_reason` | string | Reason for the session's end (e.g., `error`, `user_interrupt`).  | `user_interrupt`                 |
| `agentops.session.tags`       | array  | List of tags categorizing the session.                           | `["tag1", "tag2"]`               |
| `agentops.session.host_env`   | string | Information about the system where the session ran.              | `Ubuntu 20.04`                   |
| `agentops.session.video`      | string | URL to the video recording of the session, if applicable.        | `http://example.com/session.mp4` |
| `agentops.environment`        | string | Environment in which the agent operates (e.g., `production`).    | `production`                     |
| `agentops.lifecycle.state`    | string | Current lifecycle state of the agent (e.g., `initializing`).     | `running`                        |
| `agentops.execution.mode`     | string | Execution mode of the agent (e.g., `autonomous`, `interactive`). | `autonomous`                     |

### Task Execution Attributes
For spans that represent the execution of a task by an agent:
| Attribute                | Type    | Description                                                             | Example          |
|--------------------------|---------|-------------------------------------------------------------------------|------------------|
| `agentops.task.id`       | string  | Unique identifier for the task.                                         | `task-abcde`     |
| `agentops.task.name`     | string  | Human-readable name of the task.                                        | `Data Ingestion` |
| `agentops.task.priority` | string  | Priority level of the task (e.g., `low`, `medium`, `high`).             | `high`           |
| `agentops.task.state`    | string  | Current state of the task (e.g., `queued`, `in_progress`, `completed`). | `in_progress`    |
| `agentops.task.duration` | integer | Duration of the task execution in milliseconds.                         | `1500`           |

### Interaction Attributes
For spans capturing interactions between agents:

| Attribute                     | Type   | Description                                                         | Example            |
|-------------------------------|--------|---------------------------------------------------------------------|--------------------|
| `agentops.interaction.type`   | string | Type of interaction (e.g., `message_exchange`, `resource_request`). | `message_exchange` |
| `agentops.interaction.source` | string | Identifier of the source agent.                                     | `agent-01`         |
| `agentops.interaction.target` | string | Identifier of the target agent.                                     | `agent-02`         |
| `agentops.interaction.status` | string | Outcome of the interaction (e.g., `success`, `error`, `timeout`).   | `success`          |

## Examples

### Example 1: Task Execution by a CrewAI Agent

- **Span Name**: `task.execution CrewAI`
- **Attributes**:
  - `agentops.agent.id`: `agent-12345`
  - `agentops.agent.name`: `Data Aggregator`
  - `agentops.agent.type`: `CrewAI`
  - `agentops.session.id`: `session-67890`
  - `agentops.task.id`: `task-abcde`
  - `agentops.task.name`: `Data Ingestion`
  - `agentops.task.state`: `in_progress`
  - `agentops.task.duration`: `1500`

### Example 2: Interaction Between LangGraph Agents

- **Span Name**: `interaction LangGraph`
- **Attributes**:
  - `agentops.agent.id`: `agent-01`
  - `agentops.agent.name`: `Research Assistant`
  - `agentops.agent.type`: `LangGraph`
  - `agentops.session.id`: `session-12345`
  - `agentops.interaction.type`: `message_exchange`
  - `agentops.interaction.source`: `agent-01`
  - `agentops.interaction.target`: `agent-02`
  - `agentops.interaction.status`: `success`

In this example, a `Research Assistant` agent (`agent-01`) of type `LangGraph` engages in a `message_exchange` interaction with another agent (`agent-02`). The interaction is part of `session-12345` and completes successfully.

For a practical implementation of multi-agent collaboration using LangGraph, you can refer to the [Multi-Agent Collaboration Example](https://github.com/langchain-ai/langgraph/blob/main/examples/multi_agent/multi-agent-collaboration.ipynb) provided by LangGraph.

## Others

### Workflow
- ai_agent.workflow.name
- ai_agent.workflow.start_time
- ai_agent.workflow.end_time
- ai_agent.workflow.end_state
- ai_agent.workflow.end_reason
- ai_agent.workflow.tags
- ai_agent.workflow.host_env
- ai_agent.workflow.system

### Event

### Tools

### Agent

- ai_agent.agent.name
- ai_agent.agent.workflow_name
- ai_agent.agent.name
- ai_agent.agent.llm_id

### Task

- ai_agent.task.name
- ai_agent.task.agent_name
- ai_agent.task.description
- ai_agent.task.name
- ai_agent.task.priority
- ai_agent.task.state
- ai_agent.task.duration

### Interaction

- ai_agent.interaction.type
- ai_agent.interaction.source
- ai_agent.interaction.target
- ai_agent.interaction.status