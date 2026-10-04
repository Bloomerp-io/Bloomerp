# Agent runtime

`definition.py` contains the persisted JSON payload schemas used by Django models.
`runtime.py` contains both the public `AgentRuntime` protocol and the abstract
`BaseAgentRuntime` implementation, along with execution requests, events, and
adapter hooks. `PydanticAIRuntime` inherits that implementation in `pydantic_ai.py`.
The runtime imports the payload definitions; the definitions never import the
runtime. Execution requires no Django, Channels, Redis, or workers.
The same async iterator can run inside an async request or a configured worker.
A synchronous caller can use its existing async bridge; the adapter itself does
not choose an execution backend.

## Runtime layers

- `AgentRuntime`: public interface consumed by the runner.
- `BaseAgentRuntime[StateT]`: execution lifecycle, event backpressure, cancellation,
  duration and tool budgets, checkpoint envelopes, and tool/approval coordination.
  It imports no model SDK. `AgentRuntimeAttempt` tracks portable usage and live tasks;
  `AgentRuntimeState` holds pending proposals, the transcript cursor, and completion.
- `PydanticAIRuntime`: provider registration, SDK message/history conversion,
  streaming model turns, token accounting/limits, and SDK error classification.

A new runtime inherits `BaseAgentRuntime` and supplies its identity/version plus
`_validate_request`, `_initial_state`, `_restore_state`, `_add_messages`,
`_apply_tool_results`, and `_run`. Its state extends `AgentRuntimeState` with typed
framework-specific fields. `_serialize_state` already serializes that Pydantic
state; override it only when another representation is needed. `_classify_error`
can map SDK failures before delegating portable failures to the base.

The adapter loop calls `_save` before effects and `_dispatch` for pending calls.
`_dispatch` resolves approvals and then invokes `_apply_tool_results` to translate
the completed batch into framework history. `_run` must release owned resources
before returning its terminal event. The base publishes that event and manages
the producer's lifetime. The PydanticAI checkpoint format remains version one;
this extraction does not require checkpoint or database migration.

## Instance configuration

Resolve instance settings into `AgentRuntimeConfig`, and resolve its current API
key separately into `AgentRuntimeCredentials`. Keys never belong in `parameters`, a
configuration snapshot, or a checkpoint. The adapter does not fall back to global
API-key environment variables.

Built-in provider registrations (model names are unrestricted):

| Provider | API |
| --- | --- |
| `openai` | OpenAI Responses |
| `openai_chat` | OpenAI-compatible Chat Completions |
| `anthropic` | Anthropic Messages |
| `deepseek` | DeepSeek Chat Completions, including its reasoning history profile |

The instance selects `model`, optional `base_url`, and
`request_timeout_seconds`. `PydanticAISettings` documents and validates the
supported `parameters`; arbitrary request bodies, headers, and provider-hosted
tools are intentionally excluded because they could bypass the coordinator.
Provider availability and model-specific parameter support are still determined
by the selected endpoint. Clients and credentials are isolated per attempt.

## Adding providers

`AI_PROVIDER_REGISTRY` is the single Python registry. Register a stable identifier,
display name, runtime factory accepting `AgentRuntimeConfig`, credential schema
class, and configuration schema class. Factories return fresh runtime instances;
providers may share PydanticAI or supply a custom runtime implementing `AgentRuntime`.
The runtime receives the same pinned configuration used to construct it.

For a compatible gateway, register provider-owned model construction:

```python
from bloomerp.agents.providers.definition import AIProviderDefinition
from bloomerp.agents.providers.registry import AI_PROVIDER_REGISTRY, pydantic_runtime
from bloomerp.agents.providers.builtins.pydantic_open_ai import create_openai_chat_model
from bloomerp.agents.providers.builtins.pydantic_ai_common import PydanticAIProvider, PydanticAISettings

AI_PROVIDER_REGISTRY.register("private_gateway", AIProviderDefinition(
    id="private_gateway",
    name="Private gateway",
    runtime_factory=pydantic_runtime,
    config_schema=PydanticAISettings,
    integration=PydanticAIProvider(create_openai_chat_model),
))
```

Model identifiers remain extensible strings. Optional `model_identifier_factory`
accepts validated credentials and an optional endpoint and returns identifier/label
pairs. Discovery is advisory: outages must not invalidate saved model records.
Registration never performs discovery or other external calls.

Custom runtimes receive provider-specific validated credentials through
`AgentRuntimeCredentials.provider_credentials`. Credentials stay out of dumps,
logs, picker responses, and run configuration snapshots. The `model_factory`
runtime argument remains an offline testing override.

## Runner responsibilities

1. Construct `AgentRuntimeRunRequest` with authorized context, the current tool catalog,
   lifetime usage from **earlier** attempts, and lifetime budgets.
2. Supply an `AgentRuntimeToolCoordinator` bound to the run, attempt, and authenticated
   actor. It must enforce permissions, argument validation, approval decisions,
   leases, and effect idempotency using the existing MCP implementations.
3. Consume `execute(...)` or `resume(...)`. Persist each event before requesting
   the next one. The adapter applies backpressure, including before tool dispatch.
   Replace attempt usage totals; do not add repeated usage snapshots together.
4. On `run.paused`, persist its checkpoint and wait condition, then release the
   attempt. Resume with a fresh attempt, refreshed credentials/tool catalog, and
   only new transcript input. Never infer approval from a browser-submitted flag.
5. Close an iterator when abandoning consumption, and `aclose()` the runtime at
   service shutdown. Local cancellation targets an exact run/attempt pair; the
   runner still owns persistent cancellation and cross-process lease fencing.

External tool requests first enter the checkpoint with their original provider
call IDs. Resume re-proposes calls without a saved result using the same IDs,
resolves pending approvals through the coordinator, and skips completed calls.
The coordinator must reconcile interrupted effects, not blindly execute them
again. Saved tool errors and rejections are returned to the model as results.
New steering messages follow pending tool results in the provider transcript.

The adapter preserves SDK message history, including signed reasoning parts,
without publishing reasoning as text deltas. Streaming text remains provisional
until the model turn is checkpointed: a failed partial response may leave an
incomplete message associated with the failed attempt. Retrying that model turn
creates a new message; the runner/UI should retain or mark the old one interrupted.

## Persisted text execution

`AgentController` now authorizes private conversation ownership, persists user
messages, dispatches a leased `AIRunAttempt`, and consumes the configured runtime.
Model methods own transcript conversion, sequence allocation, checkpoints, usage,
and lifecycle transitions. Runtime text is committed before WebSocket publication.
`AIMessage.status` distinguishes streaming, completed, and interrupted output;
only completed messages enter subsequent model history.

The channel accepts `chat.message`, `chat.cancel`, `chat.resume`, `chat.approval`, and `chat.replay`.
Replay is bounded and sequence-based; it excludes private checkpoints. The frontend
replays missed events after reconnect and deduplicates live/replayed deltas. Socket
closure does not cancel durable work. Cancellation is persisted and observed by a
lease heartbeat, including while a model request is waiting for output.

One unfinished run occupies each conversation. Concurrent new messages are
explicitly rejected for now; `active_run_behavior` reserves queue/steer policies
for later implementation. Completed runs release the slot. Client message UUIDs
provide retry deduplication, including when creating a conversation.

Runtime types retain the `AgentRuntime` prefix and outgoing tool requests retain
`AgentRuntimeToolProposal`. Allowed internal tools in the live MCP `tools/list`
catalog retain their original names, descriptions and input/output schemas.
`LocalMcpClient` calls the real MCP endpoint in-process as the run's current active
user. The endpoint's permissions, validation and MCP result envelopes are unchanged.
No internal HTTP credentials or separate agent tool implementations are needed.
Built-in resources are exposed to tool-calling runtimes as read-only reader tools.
The public MCP endpoint still advertises them only through its resource catalogs.
Reader tools use stable `bloomerp_resource_` identifiers derived from resource URIs,
carry the resource metadata in their versioned contracts, and dispatch through
`resources/read` with the run actor. Template readers expose the declared string
parameter schema and safely expand the URI. Reader permissions still apply.

`internal_resource_mode="all"` includes newly registered resources and templates.
`"selected"` permits only URIs or URI templates in `internal_resources`; an empty
selection allows none. Resources have separate controls in the creation and
reconfiguration forms. Removed identities remain stored but unavailable. Both
resource selection and the resolved reader are rechecked before each read.

Configure an agent's **Tools** section on creation or its **Reconfigure** tab.
`internal_tool_mode="all"` preserves existing behavior and includes newly registered
extensions. `"selected"` permits only names in `internal_tools`; an empty list permits
none. Removed tool names remain stored but unavailable. The current configuration
is reloaded before dispatch and approval resume, independently of user permissions.

`mcp_integrations` selects external integration definitions, never credential records.
`AgentMcpClient` combines internal tools with live external catalogs. Remote names use
`external_<integration UUID hex>_<remote-name hash>` to prevent cross-server collisions
and remain within provider name limits. Every call goes through `McpToolCoordinator`.
Tool contract versions include integration configuration and encrypted connection
revision fingerprints; changing either invalidates old proposals. Approval cards use
the pinned human-readable title without issuing remote discovery requests.

Shared integrations resolve their single shared connection. Personal integrations
resolve only the acting user's existing connection, with no shared-account fallback.
No-auth integrations need no connection. Disabled integrations and missing, revoked,
expired or rejected accounts produce actionable run errors; discovery fails closed
instead of advertising unavailable tools. OAuth refresh and personal connect UI remain
separate work: expired accounts explicitly require reconnecting.

Outbound calls use public HTTPS with the OAuth service's DNS-pinned transport, no
redirects or environment proxies, MCP initialization and negotiated session/protocol
headers, paginated catalogs and JSON/SSE replies. Limits are 20 integrations, 500
combined tools, 1 MiB per request/response and combined catalog, 10 catalog pages,
and 30 seconds per discovery/session with bounded HTTP timeouts. Only local JSON Schema
references are supported. Credentials stay in transport memory and reflected stored
secrets are redacted before contracts/results enter the runtime or persistence.
Unknown annotations require approval under the default conversation policy. A lost
remote tool result becomes an unknown outcome and is never automatically replayed.

`McpToolCoordinator` persists proposals before execution. Read-only tools run
immediately by default; all other tools require approval. Configure
`AIConversation.approval_rules` as `{"default": "writes", "tools": {"navigate_user_mcp": "never"}}`
to adjust exact tool names. Defaults can be `writes`, `always`, or `never`; per-tool
overrides are `always` or `never`. Approval is independent of endpoint permissions:
a previously approved action can still be denied when it executes.

Approval cards show the exact tool arguments. Decisions are owner-authorized and
bound to an immutable proposal and contract hash. A changed tool contract stops
the old run rather than applying an old approval to a new definition. Runs pause
without holding a worker, then resume in a new attempt after all decisions are made.
Rejected actions return a refusal to the model. Duplicate decisions are harmless.

Completed results are reused. A call dispatched before a crash but lacking a durable
result is marked `unknown` and requires reconciliation; it is never automatically
repeated. This is not a claim of exactly-once external effects. Cancellation cannot
undo an action that has already started. Rich inputs/artifacts and resource ingestion
remain separate work. Current-page inspection and highlighting remain unfinished.

Browser runs bind their instance origin at the socket boundary. Set `mcp_origin`
in `BLOOMERP_CONFIG.bloomai_settings` for non-browser runs that need absolute instance URLs (default
`http://localhost`). No network request is sent to this origin by the local client.
The chat retains only account-scoped active-run IDs in session storage so navigation
can reattach through authorized replay without re-executing a message.

### Conversation history

The panel's history button opens an owner-scoped, paginated conversation list with
title search and an archived filter. Selecting a conversation restores its text
and approval cards. Older messages load in bounded pages. The existing Cotton
dropdown exposes rename, archive, and restore; archiving prevents new input but
does not cancel work already running.

`chat.history`, `chat.conversation`, and `chat.edit_conversation` use a client
`request_id` echoed in their responses so stale searches and selections can be
ignored. History remains available without a configured model provider. Reads
and edits authorize the authenticated owner independently of runtime setup.
Chat progress reuses `tool.outcome`, `run.paused`, `approval.decided`, and
`text.delta`. The shared MCP coordinator also commits `tool.started` immediately
before an authorized dispatch, after approval checks, with only the pinned tool
title. All runtimes using that coordinator receive the same tool-start behavior.
The dedicated live status line shows waiting, running tools, outcomes, approval
waits and visible response streaming; it clears on completion, failure or
cancellation. Model processing stays labelled "Waiting for a response" because
the provider does not expose finer operational stages. Private reasoning and
tool arguments are never used for progress text. Snapshots carry the latest
observable stage without results or checkpoint contents, so reconnects can
restore it without regressing when older events are replayed.

Conversation snapshots capture text and the latest run's event cursor under the
same conversation lock used by writers. Replaying after that cursor appends only
new output instead of duplicating already persisted text.

Switching chats only detaches the presentation; active runs continue. Activity
indicators are local to the connected panel, not durable cross-device read receipts.
Search currently matches titles, and rich artifact rendering remains separate work.

### Instance setup

Apply the AI agent and conversation-selection migrations. `BloomerpAgentSettings`
contains only instance operations (`mcp_origin`, `lease_seconds`, `history_limit`).
Provider credentials, model identifiers, instructions, provider parameters,
endpoints, and run budgets belong to shared `AIAgent` records.

```python
from bloomerp.models.agents import AIAgent

model = AIAgent(name="Workspace assistant", provider="openai",
    model_identifier="your-provider-model", default_instructions="Help the user.",
    max_tokens=20000, max_tool_calls=30, max_duration_seconds=300)
model.set_credentials({"api_key": "retrieve-from-your-secret-store"})
model.save()
```

Credentials use a JSON envelope with `version`, `algorithm`, and `ciphertext`.
The credential payload is encrypted with a purpose-specific key derived from the instance's
`SECRET_KEY`; preserve that key when moving the database. `SecretStr` masks values
but is not the encryption mechanism. Generic model APIs are disabled and plaintext
credentials stay out of activity logs. Use `set_credentials` to rotate keys.
The AI agent create view is a two-step provider wizard with structured settings and
encrypted credential inputs. Its Reconfigure detail tab reuses the wizard, loads
current settings, and updates the same agent. Blank credential fields retain the
stored values; switching providers requires credentials for the new provider.
Configuration changes still require administrative row and field change grants.

`AIAgentAccessManager` in `agents/access.py` grants use to active authenticated
creators (`created_by`), explicitly listed users, members of listed groups, and
superusers. `AIAgentAccess` records attach through the agent's `access` relation.
Each record also has `all_staff_users` and `all_authenticated_users`, both false
by default. These are additive grants alongside explicit users/groups. The staff
flag covers active staff accounts; the authenticated flag covers every active
signed-in account, including non-staff users. Neither grants anonymous access.
Account activity, staff status and grants are read live, including tool dispatch.
The chat picker and new-run acceptance use these grants, with disabled or
unconfigured agents excluded. Credential resolution rechecks use access on every
attempt, so revoked users cannot resume using provider secrets. Agent use grants
expose only safe picker metadata; they do not grant configuration, credential,
or access-management permissions. Set `created_by` when creating agents via ORM
to give their creator automatic use access.

### Private conversation APIs

`AIConversation` and `AIMessage` declare authenticated, owner-scoped `view` and
`add` rules using the existing `ApiAccessSettings` row/field contracts:

- `/api/ai_conversations/`: list owned conversations or create one with `title`
  and an optional `selected_agent`. The server selects a permitted enabled agent
  when omitted and assigns the owner/audit actor.
- `/api/ai_messages/`: list owned user/assistant entries or send `conversation`
  and plain-text `content_blocks`. An optional UUID `id` deduplicates retries.
  Creation uses `AgentController.accept_message`, which also creates the run,
  pins a permitted agent and derives the actor from the request.
- The generated detail endpoints and MCP object-retrieval/mutation adapters use
  the same owner boundary and fixed serializers. Even broad administrative API
  grants cannot read somebody else's transcript or forge roles, sequence,
  approval rules, agent/run state, or ownership. System entries are excluded.
- API updates/deletes are not exposed for these private records. Existing
  controller/socket commands handle conversation metadata and execution control.

Message runs dispatch only after commit. A configured external Celery broker
queues the durable IDs; the no-broker development fallback executes synchronously
within the HTTP/MCP request. Socket submissions retain their asynchronous path.
An agent-use grant enables that complete socket lifecycle for non-staff users;
it never grants SQL, configuration, project-tool or administrative permissions.
Revoking an agent grant blocks further sends/attempts/tool dispatch while owners
may still read their own existing transcript.

The chat picker saves a conversation's next-run choice. Users may switch models
within a conversation, including during an active run. Each new run snapshots
resolved non-secret settings and cumulative budgets. Resume/retry constructs the
provider runtime from that snapshot and resolves current credentials separately.
Disabling a record or changing its parameters does not alter existing runs.
Deleting its credential-bearing record prevents further credential resolution.

`max_tokens` on the model is the total input/output budget for an entire run,
including every attempt; `parameters.max_tokens` is the per-response output cap.
Version one has no monetary budget or currency configuration.

Agent runs use a Celery worker when Celery is available with an external broker;
a `memory://` development broker runs inline. Workers must run the
`bloomerp.agents.execute_run` task, and
cross-process delivery needs a shared Channels layer such as Redis. Inline work
runs on the application event loop; synchronous callers can bridge `run_attempt`
with `async_to_sync` and wait for completion. The asynchronous `execute` API requires a persistent application event loop;
a synchronous caller should use `accept_message` followed by `run_attempt` through
`async_to_sync`, or explicitly enqueue the worker task. Bridging only `execute`
would close its temporary event loop before background dispatch completes.

Attempts renew expiring leases; expired executors cannot publish new committed
output. `chat.resume` can redispatch queued runs or reclaim an expired running
attempt. Safe checkpoints restore provider history; interrupted partial messages
remain visible in storage but are excluded from fresh runtime history. Automatic
recovery sweeps, retry policy, durable queue/steering, and distributed scheduling
of waits are later orchestration work. Approval waits cannot be bypassed by resume.

Tests exercise the real PydanticAI loop with a local `FunctionModel`; no real
provider calls or API keys are required. The application database is not migrated
by those tests.

## Limits and compatibility

- Token, tool-dispatch, and elapsed-time budgets account for earlier attempts.
  Token totals depend on provider reporting and can exceed the limit during the
  final request; the adapter caps output and stops further work once exceeded.
  A recovered proposal without a saved outcome conservatively counts as another
  dispatch, even if the coordinator finds an existing result.
- There is also a 50-model-request safety limit per attempt.
- Monetary budgets and currency are outside version one.
- Artifacts currently need extracted content in user messages. A `file_uri` alone
  is not sufficient; native PDF/image transfer is not implemented here.
- Rich artifact presentation and input resolution remain separate integration work.
- The dependency uses `pydantic-ai-slim` with OpenAI/Anthropic extras and a
  compatible Anthropic SDK. Checkpoints record both adapter and SDK versions.
  An SDK upgrade requires draining existing runs or an explicit history migration;
  incompatible checkpoints fail before tool execution.

Offline tests use PydanticAI's `FunctionModel` through the real agent loop:

```sh
.venv/bin/python -m unittest bloomerp.tests.agents.test_pydantic_ai
```


## Artifact tool-result adapters

Artifact definitions may register `tool_result_adapters`. Each adapter declares a
stable `key`, exact MCP `tool_names`, and `adapt(result, request)`, returning zero
or more `AIArtifactCandidate` values. The context contains unchanged MCP output
and original arguments. Candidates carry type-local stable keys, validated payloads,
a display flag, and an optional File reference. They must not execute tools.

The registry dispatches only successful MCP results, using the newest registered
schema version for new artifacts. Existing artifacts resolve their exact stored
version. Adapters authorize source access before returning candidates; optional
`authorize` hooks recheck access when building context and rendering history.
The object adapter handles successful creates from `api_assistant_mutations`;
updates, deletes, errors, hidden objects, and results without a returned PK produce
no artifact. Its renderer intentionally uses model/ID labels rather than `__str__`,
which can reveal fields the actor cannot read.

After the original tool result is committed, the coordinator requests generic
artifact persistence. Stable IDs derived from the tool call, type/version, adapter,
and candidate key prevent duplicate attachment rows on retry. Once artifacts exist for a tool call,
replay reuses that batch even if newer adapter versions have been registered. Displayed artifacts
get an assistant message plus `AIMessageArtifact` link. Tool-outcome events and
history return references; the chat loads the generic authorized component endpoint.
An adapter error is logged and never retries or reverses the original mutation.

Apply migration `0078_bloomai_initial` before deployment. It replaces the obsolete
conversation table and creates the final agent, artifact, execution, and MCP schema.
It consolidates the unmerged `0078`–`0091` migrations; databases that applied all
14 originals are recognized through Django replacement metadata. Databases with
only part of that development chain applied must finish it using the previous
checkout before switching to this migration. The obsolete conversation records
are discarded, as in the original branch migrations. Artifact kinds and versions
remain extensible through the registry.
New payloads validate through the artifact registry on model saves. This increment
implements tool-created object cards and manually attached files/modules.
PDF processing and a visualization MCP route remain separate unfinished work.

### Attaching files and modules

The composer’s plus button and a slash at a word boundary open the same drop-up.
Use `/file` or `/module` to filter its categories, then select the category and
search its sources. Arrow keys, Enter and Escape work alongside pointer controls.
Selections appear as removable draft chips and persist as message artifacts on send;
attachment-only messages are supported.

`components/agents/search_artifacts.py` dispatches to registered `search` and `upload`
hooks. Only definitions with either hook appear in the composer. Adding a new
searchable source needs its artifact registration, not controller or frontend branches.
Search returns signed, user-bound tokens; sending revalidates their schema and current
source access. Tokens expire after 24 hours, requiring a fresh selection.

Files can be selected from the existing library or uploaded with its normal add/view
permissions. Uploads are saved immediately to that library; removing a draft chip
only detaches it, and does not delete the stored file. The default per-file limit is
20 MiB, configurable through `BLOOMERP_AGENT_UPLOAD_MAX_BYTES`. A message accepts up
to 20 attachments. Downloads recheck existing file permissions and use attachment
rather than inline disposition. Module search uses module-page visibility rules.

The runtime receives reference descriptions, including a file identifier or module
identifier. Attaching a file does not extract its contents; reading PDFs, images or
spreadsheets belongs in separately registered MCP capabilities.

Tool approval rules belong to `AIConversation`, not `AIAgent`. The chat composer can change the conversation policy during an active response. The coordinator reads current rules for each tool call; existing pending approvals still require an explicit decision. Run snapshots retain the initial rules for audit history.
