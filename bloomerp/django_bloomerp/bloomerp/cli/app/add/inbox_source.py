# Proposed scaffolding parameters for scheduled, event-driven, or signal inbox sources.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated symbol prefix.
# key: str - Globally unique source key used by InboxSourceRegistry.
# folder_type: str - Existing persisted InboxFolderTypeDefinition.key.
# source_type: Literal["job", "event", "signal"] - Source definition to generate.
# folder_qs_resolver: str | None = None - Folder resolver import path or typed stub.
# handler: str | None = None - Source handler import path or generated typed stub.
# origin: str | None = None - Registration owner; derive from the target app.
# schedule: str | None = None - Cron expression; required only for job sources.
# signal: str | None = None - Django signal import path; required for signal sources.
# dispatch_uid: str | None = None - Stable signal receiver ID; required for signals.
# sender: str | None = None - Optional Django model class import path for signals.
# predicate: str | None = None - Optional signal predicate callback import path.
# run_async: bool = True - Event/signal execution mode; not a job-source option.
# Registration: InboxSourceRegistry.register_source(source, folder_type=..., origin=...).
