export type QueryValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryValue | QueryValue[]>;

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export type ListResponse<T> = PaginatedResponse<T>;

export interface BloomerpSessionResponse {
  authenticated: boolean;
  user?: Record<string, unknown>;
}

export interface BloomerpCsrfResponse {
  csrfToken: string;
}

export interface BloomerpAuthLoginPayload {
  password: string;
  identifier?: string;
  username?: string;
  email?: string;
  [key: string]: unknown;
}

export interface BloomerpFieldChoiceMetadata {
  value: string | number | boolean | null;
  label: string;
}

export interface BloomerpFieldMetadata {
  name: string;
  title: string;
  fieldType: string;
  dbFieldType: string | null;
  nullable: boolean;
  many: boolean;
  relatedModel: string | null;
  editable: boolean;
  requiredOnCreate: boolean;
  tsType: string;
  choices: BloomerpFieldChoiceMetadata[] | null;
}

export interface BloomerpModelPublicAccessMetadata {
  listAllowed: boolean;
  readAllowed: boolean;
  listFields: string[] | null;
  readFields: string[] | null;
  nesting: BloomerpModelNestingMetadata[];
  authenticatedFallbackEnabled: boolean;
}

export interface BloomerpModelNestingMetadata {
  forField: string;
  fields: string[];
  onAction: Array<"list" | "read">;
  autoPk: boolean;
}

export interface BloomerpModelCapabilities {
  list: boolean;
  retrieve: boolean;
  create: boolean;
  createMany: boolean;
  update: boolean;
  partialUpdate: boolean;
  destroy: boolean;
}

export interface BloomerpRequestOptions extends Omit<RequestInit, "headers"> {
  headers?: HeadersInit;
  query?: QueryParams;
  fetchOptions?: Record<string, unknown>;
}

export interface BloomerpSessionCsrfConfig {
  enabled?: boolean;
  headerName?: string;
  token?: string | null | (() => string | null | Promise<string | null>);
}

export type BloomerpAuth =
  | { type: "none" }
  | { type: "session"; credentials?: RequestCredentials; csrf?: BloomerpSessionCsrfConfig }
  | { type: "basic"; username: string; password: string }
  | { type: "bearer"; token: string }
  | { type: "apiKey"; key: string; headerName?: string }
  | { type: "authorization"; value: string }
  | { type: "custom"; headers?: Record<string, string> };

export interface BloomerpSdkConfig {
  baseUrl: string;
  auth?: BloomerpAuth;
  headers?: Record<string, string>;
  fetch?: typeof fetch;
}

export class BloomerpHttpError<TBody = unknown> extends Error {
  public readonly status: number;
  public readonly statusText: string;
  public readonly body: TBody | undefined;
  public readonly headers: Headers;

  constructor(response: Response, body?: TBody) {
    super(BloomerpHttpError.buildMessage(response, body));
    this.name = "BloomerpHttpError";
    this.status = response.status;
    this.statusText = response.statusText;
    this.body = body;
    this.headers = response.headers;
  }

  private static buildMessage<TBody>(response: Response, body?: TBody) {
    if (typeof body === "string" && body.trim()) {
      return body;
    }

    if (body && typeof body === "object") {
      const payload = body as Record<string, unknown>;

      if (typeof payload.detail === "string" && payload.detail.trim()) {
        return payload.detail;
      }

      const firstEntry = Object.values(payload).find(
        (value) => value !== undefined && value !== null,
      );
      if (typeof firstEntry === "string" && firstEntry.trim()) {
        return firstEntry;
      }
      if (Array.isArray(firstEntry) && typeof firstEntry[0] === "string") {
        return firstEntry[0];
      }
    }

    return `Bloomerp request failed with status ${response.status}: ${response.statusText}`;
  }
}

export class BloomerpHttpClient {
  private readonly baseUrl: string;
  private readonly auth: BloomerpAuth;
  private readonly headers: Record<string, string>;
  private readonly fetchImpl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
  private csrfToken: string | null = null;

  constructor(config: BloomerpSdkConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    this.auth = config.auth ?? { type: "none" };
    this.headers = config.headers ?? {};
    this.fetchImpl = config.fetch ?? ((input, init) => globalThis.fetch(input, init));
  }

  async request<T>(path: string, options: BloomerpRequestOptions = {}): Promise<T> {
    const { query, fetchOptions, headers: requestHeaders, ...init } = options;
    const url = this.buildUrl(path, query);
    const headers = this.buildHeaders(requestHeaders);

    this.applyAuthHeaders(headers);

    if (this.shouldSetJsonContentType(init.body, headers)) {
      headers.set("Content-Type", "application/json");
    }

    const method = (init.method ?? "GET").toUpperCase();
    if (await this.shouldAttachCsrfHeader(method, headers)) {
      const csrfToken = await this.resolveCsrfToken();
      if (csrfToken) {
        headers.set(this.getCsrfHeaderName(), csrfToken);
      }
    }

    const response = await this.fetchImpl(url.toString(), {
      ...(fetchOptions ?? {}),
      ...init,
      credentials: this.resolveCredentials(init.credentials),
      headers,
    } as RequestInit);

    const body = await this.parseResponseBody(response);
    if (!response.ok) {
      throw new BloomerpHttpError(response, body);
    }

    return body as T;
  }

  async fetchCsrfToken(options: BloomerpRequestOptions = {}): Promise<BloomerpCsrfResponse> {
    const response = await this.request<BloomerpCsrfResponse>("/api/auth/csrf/", {
      ...options,
      method: options.method ?? "GET",
    });
    this.csrfToken = response.csrfToken ?? null;
    return response;
  }

  private buildUrl(path: string, query?: QueryParams): URL {
    const url = new URL(this.baseUrl + path);
    if (!query) {
      return url;
    }

    for (const [key, value] of Object.entries(query)) {
      if (value === undefined) {
        continue;
      }
      if (Array.isArray(value)) {
        for (const item of value) {
          if (item !== undefined && item !== null) {
            url.searchParams.append(key, String(item));
          }
        }
        continue;
      }
      if (value !== null) {
        url.searchParams.set(key, String(value));
      }
    }

    return url;
  }

  private buildHeaders(requestHeaders?: HeadersInit): Headers {
    const headers = new Headers(this.headers);
    if (requestHeaders) {
      new Headers(requestHeaders).forEach((value, key) => headers.set(key, value));
    }
    return headers;
  }

  private applyAuthHeaders(headers: Headers): void {
    const authHeader = this.getAuthorizationHeader();
    if (authHeader) {
      headers.set("Authorization", authHeader);
    }

    if (this.auth.type === "apiKey") {
      headers.set(this.auth.headerName ?? "X-API-Key", this.auth.key);
    }

    if (this.auth.type === "custom" && this.auth.headers) {
      for (const [key, value] of Object.entries(this.auth.headers)) {
        headers.set(key, value);
      }
    }
  }

  /** Set JSON headers for serialized payloads; let browsers encode multipart bodies. */
  private shouldSetJsonContentType(body: BodyInit | null | undefined, headers: Headers): boolean {
    return typeof body === "string" && !headers.has("Content-Type");
  }

  private getAuthorizationHeader(): string | null {
    switch (this.auth.type) {
      case "basic":
        return `Basic ${encodeBase64(`${this.auth.username}:${this.auth.password}`)}`;
      case "bearer":
        return `Bearer ${this.auth.token}`;
      case "authorization":
        return this.auth.value;
      default:
        return null;
    }
  }

  private resolveCredentials(requestCredentials?: RequestCredentials): RequestCredentials | undefined {
    if (requestCredentials) {
      return requestCredentials;
    }
    if (this.auth.type === "session") {
      return this.auth.credentials ?? "include";
    }
    return undefined;
  }

  private async shouldAttachCsrfHeader(method: string, headers: Headers): Promise<boolean> {
    if (this.auth.type !== "session") {
      return false;
    }
    if (["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
      return false;
    }
    if (headers.has(this.getCsrfHeaderName())) {
      return false;
    }
    return this.auth.csrf?.enabled !== false;
  }

  private getCsrfHeaderName(): string {
    if (this.auth.type === "session") {
      return this.auth.csrf?.headerName ?? "X-CSRFToken";
    }
    return "X-CSRFToken";
  }

  private async resolveCsrfToken(): Promise<string | null> {
    if (this.auth.type !== "session") {
      return null;
    }

    const configuredToken = this.auth.csrf?.token;
    if (typeof configuredToken === "function") {
      return (await configuredToken()) ?? null;
    }
    if (typeof configuredToken === "string") {
      return configuredToken;
    }
    if (this.csrfToken) {
      return this.csrfToken;
    }

    const response = await this.fetchCsrfToken();
    return response.csrfToken ?? null;
  }

  private async parseResponseBody(response: Response): Promise<unknown> {
    if (response.status === 204) {
      return undefined;
    }

    const contentType = response.headers.get("content-type") ?? "";
    const rawBody = await response.text();
    if (!rawBody) {
      return undefined;
    }

    if (contentType.includes("application/json")) {
      try {
        return JSON.parse(rawBody);
      } catch (_error) {
        return rawBody;
      }
    }

    return rawBody;
  }
}

function encodeBase64(value: string): string {
  if (typeof btoa === "function") {
    return btoa(value);
  }
  const globalBuffer = (globalThis as { Buffer?: { from(input: string, encoding: string): { toString(outputEncoding: string): string } } }).Buffer;
  if (globalBuffer) {
    return globalBuffer.from(value, "utf-8").toString("base64");
  }
  throw new Error("No base64 encoder available in this runtime.");
}

function isPaginatedResponse<T>(value: unknown): value is PaginatedResponse<T> {
  if (!value || typeof value !== "object") {
    return false;
  }
  const candidate = value as Partial<PaginatedResponse<T>>;
  return (
    typeof candidate.count === "number"
    && "results" in candidate
    && Array.isArray(candidate.results)
  );
}

function normalizeListResponse<T>(value: T[] | PaginatedResponse<T>): PaginatedResponse<T> {
  if (Array.isArray(value)) {
    return {
      count: value.length,
      next: null,
      previous: null,
      results: value,
    };
  }
  return value;
}

export class AuthApi {
  constructor(private readonly client: BloomerpHttpClient) {}

  session(options?: BloomerpRequestOptions): Promise<BloomerpSessionResponse> {
    return this.client.request<BloomerpSessionResponse>("/api/auth/session/", {
      ...options,
      method: "GET",
    });
  }

  csrf(options?: BloomerpRequestOptions): Promise<BloomerpCsrfResponse> {
    return this.client.fetchCsrfToken(options);
  }

  login(payload: BloomerpAuthLoginPayload, options?: BloomerpRequestOptions): Promise<BloomerpSessionResponse> {
    return this.client.request<BloomerpSessionResponse>("/api/auth/login/", {
      ...options,
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  logout(options?: BloomerpRequestOptions): Promise<BloomerpSessionResponse> {
    return this.client.request<BloomerpSessionResponse>("/api/auth/logout/", {
      ...options,
      method: "POST",
    });
  }
}

export class ModelApi<TModel, TId extends string | number, TCreate, TUpdate, TQuery, TFieldName extends string> {
  constructor(
    protected readonly client: BloomerpHttpClient,
    protected readonly endpoint: string,
  ) {}

  async list(query?: TQuery, options?: BloomerpRequestOptions): Promise<ListResponse<TModel>> {
    const response = await this.client.request<TModel[] | PaginatedResponse<TModel>>(this.endpoint, {
      ...options,
      method: "GET",
      query: query as QueryParams | undefined,
    });
    return normalizeListResponse(response);
  }

  async listResults(query?: TQuery, options?: BloomerpRequestOptions): Promise<TModel[]> {
    const response = await this.list(query, options);
    return response.results;
  }

  retrieve(id: TId, options?: BloomerpRequestOptions): Promise<TModel> {
    return this.client.request<TModel>(`${this.endpoint}${id}/`, {
      ...options,
      method: "GET",
    });
  }

  create(payload: TCreate, options?: BloomerpRequestOptions): Promise<TModel> {
    return this.client.request<TModel>(this.endpoint, {
      ...options,
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  createMany(payloads: TCreate[], options?: BloomerpRequestOptions): Promise<TModel[]> {
    return this.client.request<TModel[]>(this.endpoint, {
      ...options,
      method: "POST",
      body: JSON.stringify(payloads),
    });
  }

  update(id: TId, payload: TUpdate, options?: BloomerpRequestOptions): Promise<TModel> {
    return this.client.request<TModel>(`${this.endpoint}${id}/`, {
      ...options,
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  partialUpdate(id: TId, payload: Partial<TUpdate>, options?: BloomerpRequestOptions): Promise<TModel> {
    return this.client.request<TModel>(`${this.endpoint}${id}/`, {
      ...options,
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  destroy(id: TId, options?: BloomerpRequestOptions): Promise<void> {
    return this.client.request<void>(`${this.endpoint}${id}/`, {
      ...options,
      method: "DELETE",
    });
  }
}

export const bloomerpAuthStrategyTypes = ["session", "apiKey"] as const;

export interface AIConversation {
  approval_rules: unknown;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: string;
  object_labels: unknown;
  owner: number;
  selected_agent: string | null;
  status: string;
  title: string;
  updated_by: number | null;
}

export type AIConversationId = string;
export type AIConversationFieldName = "approval_rules" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "object_labels" | "owner" | "selected_agent" | "status" | "title" | "updated_by";

export interface AIConversationCreate {
  approval_rules?: unknown;
  created_by?: number | null;
  owner: number;
  selected_agent?: string | null;
  status?: string;
  title?: string;
  updated_by?: number | null;
}

export type AIConversationUpdate = Partial<AIConversationCreate>;
export type AIConversationQuery = Partial<Record<AIConversationFieldName | `${AIConversationFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const aiConversationsFields: Record<AIConversationFieldName, BloomerpFieldMetadata> = {
  "approval_rules": {"name": "approval_rules", "title": "Tool Approval Rules", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "owner": {"name": "owner", "title": "Owner", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "selected_agent": {"name": "selected_agent", "title": "Selected Agent", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "AIAgent", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "status": {"name": "status", "title": "Status", "fieldType": "CharField", "dbFieldType": "varchar(16)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "open", "label": "Open"}, {"value": "archived", "label": "Archived"}]},
  "title": {"name": "title", "title": "Title", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const aiConversationsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const aiConversationsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class AIConversationApi extends ModelApi<AIConversation, AIConversationId, AIConversationCreate, AIConversationUpdate, AIConversationQuery, AIConversationFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/ai_conversations/");
  }
}

export interface AIMessage {
  content_blocks: unknown;
  conversation: string;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: string;
  object_labels: unknown;
  role: string;
  run: string | null;
  schema_version: number;
  sequence: number;
  status: string;
  updated_by: number | null;
}

export type AIMessageId = string;
export type AIMessageFieldName = "content_blocks" | "conversation" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "object_labels" | "role" | "run" | "schema_version" | "sequence" | "status" | "updated_by";

export interface AIMessageCreate {
  content_blocks?: unknown;
  conversation: string;
  created_by?: number | null;
  role: string;
  run?: string | null;
  schema_version?: number;
  sequence: number;
  status?: string;
  updated_by?: number | null;
}

export type AIMessageUpdate = Partial<AIMessageCreate>;
export type AIMessageQuery = Partial<Record<AIMessageFieldName | `${AIMessageFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const aiMessagesFields: Record<AIMessageFieldName, BloomerpFieldMetadata> = {
  "content_blocks": {"name": "content_blocks", "title": "Content Blocks", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "conversation": {"name": "conversation", "title": "Conversation", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": "AIConversation", "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "role": {"name": "role", "title": "Role", "fieldType": "CharField", "dbFieldType": "varchar(16)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "user", "label": "User"}, {"value": "assistant", "label": "Assistant"}, {"value": "system", "label": "System"}]},
  "run": {"name": "run", "title": "Run", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "AIRun", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "schema_version": {"name": "schema_version", "title": "Schema Version", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": [{"value": 1, "label": "Version 1"}]},
  "sequence": {"name": "sequence", "title": "Sequence", "fieldType": "BigIntegerField", "dbFieldType": "bigint unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "status": {"name": "status", "title": "Status", "fieldType": "CharField", "dbFieldType": "varchar(16)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "streaming", "label": "Streaming"}, {"value": "completed", "label": "Completed"}, {"value": "interrupted", "label": "Interrupted"}]},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const aiMessagesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const aiMessagesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class AIMessageApi extends ModelApi<AIMessage, AIMessageId, AIMessageCreate, AIMessageUpdate, AIMessageQuery, AIMessageFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/ai_messages/");
  }
}

export interface ActivityLog {
  action: string;
  actor: number | null;
  content_type: number;
  id: number;
  is_create: boolean;
  object_id: string;
  payload: unknown;
  source: string;
  timestamp: string;
}

export type ActivityLogId = number;
export type ActivityLogFieldName = "action" | "actor" | "content_type" | "id" | "is_create" | "object_id" | "payload" | "source" | "timestamp";

export interface ActivityLogCreate {
  action?: string;
  actor?: number | null;
  content_type: number;
  is_create?: boolean;
  object_id: string;
  payload?: unknown;
  source?: string;
}

export type ActivityLogUpdate = Partial<ActivityLogCreate>;
export type ActivityLogQuery = Partial<Record<ActivityLogFieldName | `${ActivityLogFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const activityLogsFields: Record<ActivityLogFieldName, BloomerpFieldMetadata> = {
  "action": {"name": "action", "title": "Action", "fieldType": "CharField", "dbFieldType": "varchar(12)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "CHANGE", "label": "Change"}, {"value": "CREATE", "label": "Create"}, {"value": "DELETE", "label": "Delete"}]},
  "actor": {"name": "actor", "title": "Actor", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "is_create": {"name": "is_create", "title": "Is Create", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "object_id": {"name": "object_id", "title": "Object ID", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "payload": {"name": "payload", "title": "Payload", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "source": {"name": "source", "title": "Source", "fieldType": "CharField", "dbFieldType": "varchar(12)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "DETAIL", "label": "Detail"}, {"value": "API", "label": "API"}, {"value": "CREATE", "label": "Create"}, {"value": "BULK", "label": "Bulk"}]},
  "timestamp": {"name": "timestamp", "title": "Timestamp", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
} as const;

export const activityLogsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const activityLogsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class ActivityLogApi extends ModelApi<ActivityLog, ActivityLogId, ActivityLogCreate, ActivityLogUpdate, ActivityLogQuery, ActivityLogFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/activity_logs/");
  }
}

export interface ApplicationField {
  advanced_rendering: string | null;
  content_type: number;
  db_column: string | null;
  db_field_type: string | null;
  db_table: string | null;
  field: string;
  field_type: string;
  id: number;
  meta: unknown;
  related_model: number | null;
}

export type ApplicationFieldId = number;
export type ApplicationFieldFieldName = "advanced_rendering" | "content_type" | "db_column" | "db_field_type" | "db_table" | "field" | "field_type" | "id" | "meta" | "related_model";

export interface ApplicationFieldCreate {
  advanced_rendering?: string | null;
}

export type ApplicationFieldUpdate = Partial<ApplicationFieldCreate>;
export type ApplicationFieldQuery = Partial<Record<ApplicationFieldFieldName | `${ApplicationFieldFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const applicationFieldsFields: Record<ApplicationFieldFieldName, BloomerpFieldMetadata> = {
  "advanced_rendering": {"name": "advanced_rendering", "title": "Advanced rendering", "fieldType": "CodeField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": false, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "db_column": {"name": "db_column", "title": "DB Column", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "db_field_type": {"name": "db_field_type", "title": "DB Field Type", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "db_table": {"name": "db_table", "title": "DB Table", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "field": {"name": "field", "title": "Field", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "field_type": {"name": "field_type", "title": "Field Type", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "CharField", "label": "Char Field"}, {"value": "CodeField", "label": "Code Field"}, {"value": "ChoiceField", "label": "Choice Field"}, {"value": "TextField", "label": "Text Field"}, {"value": "EmailField", "label": "Email Field"}, {"value": "URLField", "label": "URL Field"}, {"value": "AddressField", "label": "Address Field"}, {"value": "PhoneNumberField", "label": "Phone Number Field"}, {"value": "SlugField", "label": "Slug Field"}, {"value": "IPAddressField", "label": "IP Address Field"}, {"value": "GenericIPAddressField", "label": "Generic IP Address Field"}, {"value": "IconField", "label": "Icon Field"}, {"value": "CountryField", "label": "Country Field"}, {"value": "AutoField", "label": "Auto Field"}, {"value": "BigAutoField", "label": "Big Auto Field"}, {"value": "SmallAutoField", "label": "Small Auto Field"}, {"value": "IntegerField", "label": "Integer Field"}, {"value": "FloatField", "label": "Float Field"}, {"value": "DecimalField", "label": "Decimal Field"}, {"value": "PositiveIntegerField", "label": "Positive Integer Field"}, {"value": "PositiveSmallIntegerField", "label": "Positive Small Integer Field"}, {"value": "BigIntegerField", "label": "Big Integer Field"}, {"value": "SmallIntegerField", "label": "Small Integer Field"}, {"value": "BooleanField", "label": "Boolean Field"}, {"value": "NullBooleanField", "label": "Null Boolean Field"}, {"value": "DateField", "label": "Date Field"}, {"value": "WeekField", "label": "Week Field"}, {"value": "DateTimeField", "label": "DateTime Field"}, {"value": "TimeField", "label": "Time Field"}, {"value": "DurationField", "label": "Duration Field"}, {"value": "ForeignKey", "label": "Foreign Key"}, {"value": "OneToOneField", "label": "One To One Field"}, {"value": "ManyToManyField", "label": "Many To Many Field"}, {"value": "OneToManyField", "label": "One To Many Field"}, {"value": "UserField", "label": "User Field"}, {"value": "OneToOneUserField", "label": "One To One User Field"}, {"value": "GenericRelation", "label": "Generic Relation"}, {"value": "GenericForeignKey", "label": "Generic Foreign Key"}, {"value": "FilesRelationField", "label": "Files"}, {"value": "Property", "label": "Property"}, {"value": "FileField", "label": "File Field"}, {"value": "ImageField", "label": "Image Field"}, {"value": "UUIDField", "label": "UUID Field"}, {"value": "BinaryField", "label": "Binary Field"}, {"value": "JSONField", "label": "JSON Field"}, {"value": "ArrayField", "label": "Array Field"}, {"value": "HStoreField", "label": "HStore Field"}, {"value": "StatusField", "label": "Status Field"}, {"value": "BloomerpFileField", "label": "Bloomerp File Field"}, {"value": "BloomerpLabelsField", "label": "Labels"}]},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "meta": {"name": "meta", "title": "Meta", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "related_model": {"name": "related_model", "title": "Related Model", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": "ContentType", "editable": false, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const applicationFieldsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const applicationFieldsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class ApplicationFieldApi extends ModelApi<ApplicationField, ApplicationFieldId, ApplicationFieldCreate, ApplicationFieldUpdate, ApplicationFieldQuery, ApplicationFieldFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/application_fields/");
  }
}

export interface Bookmark {
  content_type: number;
  datetime_created: string;
  id: number;
  object_id: string;
  user: number;
}

export type BookmarkId = number;
export type BookmarkFieldName = "content_type" | "datetime_created" | "id" | "object_id" | "user";

export interface BookmarkCreate {
  content_type: number;
  object_id: string;
  user: number;
}

export type BookmarkUpdate = Partial<BookmarkCreate>;
export type BookmarkQuery = Partial<Record<BookmarkFieldName | `${BookmarkFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const bookmarksFields: Record<BookmarkFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "object_id": {"name": "object_id", "title": "Object ID", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const bookmarksCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const bookmarksPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class BookmarkApi extends ModelApi<Bookmark, BookmarkId, BookmarkCreate, BookmarkUpdate, BookmarkQuery, BookmarkFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/bookmarks/");
  }
}

export interface CalendarBooking {
  active: boolean;
  availability_hours: unknown;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  description: string;
  id: string;
  meeting_duration_minutes: number;
  object_labels: unknown;
  organizing_inbox: number;
  public_token: string;
  target_inboxes: Array<number>;
  timezone: string;
  title: string;
  updated_by: number | null;
}

export type CalendarBookingId = string;
export type CalendarBookingFieldName = "active" | "availability_hours" | "created_by" | "datetime_created" | "datetime_updated" | "description" | "id" | "meeting_duration_minutes" | "object_labels" | "organizing_inbox" | "public_token" | "target_inboxes" | "timezone" | "title" | "updated_by";

export interface CalendarBookingCreate {
  active?: boolean;
  availability_hours?: unknown;
  created_by?: number | null;
  description?: string;
  meeting_duration_minutes: number;
  organizing_inbox: number;
  target_inboxes?: Array<number>;
  timezone: string;
  title: string;
  updated_by?: number | null;
}

export type CalendarBookingUpdate = Partial<CalendarBookingCreate>;
export type CalendarBookingQuery = Partial<Record<CalendarBookingFieldName | `${CalendarBookingFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const calendarBookingsFields: Record<CalendarBookingFieldName, BloomerpFieldMetadata> = {
  "active": {"name": "active", "title": "Active", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "availability_hours": {"name": "availability_hours", "title": "Availability hours", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "description": {"name": "description", "title": "Description", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "meeting_duration_minutes": {"name": "meeting_duration_minutes", "title": "Meeting duration in minutes", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "organizing_inbox": {"name": "organizing_inbox", "title": "Organizing inbox", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "Inbox", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "public_token": {"name": "public_token", "title": "Public Token", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "target_inboxes": {"name": "target_inboxes", "title": "Destination inboxes", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Inbox", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "timezone": {"name": "timezone", "title": "Availability timezone", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "title": {"name": "title", "title": "Title", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const calendarBookingsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const calendarBookingsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class CalendarBookingApi extends ModelApi<CalendarBooking, CalendarBookingId, CalendarBookingCreate, CalendarBookingUpdate, CalendarBookingQuery, CalendarBookingFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/calendar_bookings/");
  }
}

export interface CalendarBookingSubmission {
  calendar_booking: string;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  email: string;
  id: string;
  name: string;
  object_labels: unknown;
  submitted_at: string;
  updated_by: number | null;
}

export type CalendarBookingSubmissionId = string;
export type CalendarBookingSubmissionFieldName = "calendar_booking" | "created_by" | "datetime_created" | "datetime_updated" | "email" | "id" | "name" | "object_labels" | "submitted_at" | "updated_by";

export interface CalendarBookingSubmissionCreate {
  calendar_booking: string;
  created_by?: number | null;
  email: string;
  name: string;
  submitted_at?: string;
  updated_by?: number | null;
}

export type CalendarBookingSubmissionUpdate = Partial<CalendarBookingSubmissionCreate>;
export type CalendarBookingSubmissionQuery = Partial<Record<CalendarBookingSubmissionFieldName | `${CalendarBookingSubmissionFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const calendarBookingSubmissionsFields: Record<CalendarBookingSubmissionFieldName, BloomerpFieldMetadata> = {
  "calendar_booking": {"name": "calendar_booking", "title": "Calendar booking", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": "CalendarBooking", "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "email": {"name": "email", "title": "Email", "fieldType": "EmailField", "dbFieldType": "varchar(254)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "submitted_at": {"name": "submitted_at", "title": "Submitted at", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const calendarBookingSubmissionsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const calendarBookingSubmissionsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class CalendarBookingSubmissionApi extends ModelApi<CalendarBookingSubmission, CalendarBookingSubmissionId, CalendarBookingSubmissionCreate, CalendarBookingSubmissionUpdate, CalendarBookingSubmissionQuery, CalendarBookingSubmissionFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/calendar_booking_submissions/");
  }
}

export interface CalendarEvent {
  all_day: boolean;
  calendar_booking_submission: string | null;
  calendar_uid: string;
  cancelled: boolean;
  conference_session: string | null;
  content: string;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  end: string;
  end_date: string;
  event_timezone: string | null;
  id: string;
  inboxes: Array<number>;
  invitation_sent_at: string;
  location: string;
  object_labels: unknown;
  organizer_email: string;
  organizing_inbox: number | null;
  scheduling_dtstamp: string;
  sequence: number;
  source_calendar: string;
  start: string;
  start_date: string;
  title: string;
  updated_by: number | null;
}

export type CalendarEventId = string;
export type CalendarEventFieldName = "all_day" | "calendar_booking_submission" | "calendar_uid" | "cancelled" | "conference_session" | "content" | "created_by" | "datetime_created" | "datetime_updated" | "end" | "end_date" | "event_timezone" | "id" | "inboxes" | "invitation_sent_at" | "location" | "object_labels" | "organizer_email" | "organizing_inbox" | "scheduling_dtstamp" | "sequence" | "source_calendar" | "start" | "start_date" | "title" | "updated_by";

export interface CalendarEventCreate {
  all_day?: boolean;
  calendar_booking_submission?: string | null;
  content?: string;
  created_by?: number | null;
  end?: string;
  end_date?: string;
  event_timezone?: string | null;
  inboxes?: Array<number>;
  location?: string;
  organizer_email: string;
  organizing_inbox?: number | null;
  start?: string;
  start_date?: string;
  title: string;
  updated_by?: number | null;
}

export type CalendarEventUpdate = Partial<CalendarEventCreate>;
export type CalendarEventQuery = Partial<Record<CalendarEventFieldName | `${CalendarEventFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const calendarEventsFields: Record<CalendarEventFieldName, BloomerpFieldMetadata> = {
  "all_day": {"name": "all_day", "title": "All day", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "calendar_booking_submission": {"name": "calendar_booking_submission", "title": "Booking submission", "fieldType": "OneToOneField", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "CalendarBookingSubmission", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "calendar_uid": {"name": "calendar_uid", "title": "Calendar Uid", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "cancelled": {"name": "cancelled", "title": "Cancelled", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "conference_session": {"name": "conference_session", "title": "Conference session", "fieldType": "OneToOneField", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "ConferenceSession", "editable": false, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "content": {"name": "content", "title": "Content", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "end": {"name": "end", "title": "End", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "end_date": {"name": "end_date", "title": "Exclusive end date", "fieldType": "DateField", "dbFieldType": "date", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "event_timezone": {"name": "event_timezone", "title": "Event timezone", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "inboxes": {"name": "inboxes", "title": "Calendar inboxes", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Inbox", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "invitation_sent_at": {"name": "invitation_sent_at", "title": "Invitation Sent At", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "location": {"name": "location", "title": "Location", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "organizer_email": {"name": "organizer_email", "title": "Organizer email", "fieldType": "EmailField", "dbFieldType": "varchar(254)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "organizing_inbox": {"name": "organizing_inbox", "title": "Organizing inbox", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "Inbox", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "scheduling_dtstamp": {"name": "scheduling_dtstamp", "title": "Scheduling Dtstamp", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "sequence": {"name": "sequence", "title": "Sequence", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "source_calendar": {"name": "source_calendar", "title": "Source Calendar", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "start": {"name": "start", "title": "Start", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "start_date": {"name": "start_date", "title": "Start date", "fieldType": "DateField", "dbFieldType": "date", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "title": {"name": "title", "title": "Title", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const calendarEventsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const calendarEventsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class CalendarEventApi extends ModelApi<CalendarEvent, CalendarEventId, CalendarEventCreate, CalendarEventUpdate, CalendarEventQuery, CalendarEventFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/calendar_events/");
  }
}

export interface CalendarEventParticipant {
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  display_name: string;
  email: string;
  event: string;
  id: string;
  invitation_cancelled: boolean;
  last_sent_reply_sequence: number;
  last_sent_reply_status: string;
  object_labels: unknown;
  reply_dtstamp: string;
  reply_sequence: number;
  responded_at: string;
  response_status: string;
  updated_by: number | null;
  user: number | null;
}

export type CalendarEventParticipantId = string;
export type CalendarEventParticipantFieldName = "created_by" | "datetime_created" | "datetime_updated" | "display_name" | "email" | "event" | "id" | "invitation_cancelled" | "last_sent_reply_sequence" | "last_sent_reply_status" | "object_labels" | "reply_dtstamp" | "reply_sequence" | "responded_at" | "response_status" | "updated_by" | "user";

export interface CalendarEventParticipantCreate {
  created_by?: number | null;
  display_name?: string;
  email?: string;
  event: string;
  responded_at?: string;
  response_status?: string;
  updated_by?: number | null;
  user?: number | null;
}

export type CalendarEventParticipantUpdate = Partial<CalendarEventParticipantCreate>;
export type CalendarEventParticipantQuery = Partial<Record<CalendarEventParticipantFieldName | `${CalendarEventParticipantFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const calendarEventParticipantsFields: Record<CalendarEventParticipantFieldName, BloomerpFieldMetadata> = {
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "display_name": {"name": "display_name", "title": "Display name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "email": {"name": "email", "title": "Invited email", "fieldType": "EmailField", "dbFieldType": "varchar(254)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "event": {"name": "event", "title": "Event", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": "CalendarEvent", "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "invitation_cancelled": {"name": "invitation_cancelled", "title": "Invitation Cancelled", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "last_sent_reply_sequence": {"name": "last_sent_reply_sequence", "title": "Last Sent Reply Sequence", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "last_sent_reply_status": {"name": "last_sent_reply_status", "title": "Last Sent Reply Status", "fieldType": "CharField", "dbFieldType": "varchar(24)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "reply_dtstamp": {"name": "reply_dtstamp", "title": "Reply Dtstamp", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "reply_sequence": {"name": "reply_sequence", "title": "Reply Sequence", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "responded_at": {"name": "responded_at", "title": "Responded at", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "response_status": {"name": "response_status", "title": "Response status", "fieldType": "CharField", "dbFieldType": "varchar(24)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "awaiting_response", "label": "Awaiting response"}, {"value": "accepted", "label": "Accepted"}, {"value": "tentative", "label": "Tentative"}, {"value": "declined", "label": "Declined"}]},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const calendarEventParticipantsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const calendarEventParticipantsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class CalendarEventParticipantApi extends ModelApi<CalendarEventParticipant, CalendarEventParticipantId, CalendarEventParticipantCreate, CalendarEventParticipantUpdate, CalendarEventParticipantQuery, CalendarEventParticipantFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/calendar_event_participants/");
  }
}

export interface Comment {
  content: string;
  content_type: number;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: number;
  object_id: string;
  updated_by: number | null;
}

export type CommentId = number;
export type CommentFieldName = "content" | "content_type" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "object_id" | "updated_by";

export interface CommentCreate {
  content: string;
  content_type: number;
  created_by?: number | null;
  object_id: string;
  updated_by?: number | null;
}

export type CommentUpdate = Partial<CommentCreate>;
export type CommentQuery = Partial<Record<CommentFieldName | `${CommentFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const commentsFields: Record<CommentFieldName, BloomerpFieldMetadata> = {
  "content": {"name": "content", "title": "Content", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "object_id": {"name": "object_id", "title": "Object ID", "fieldType": "CharField", "dbFieldType": "varchar(36)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const commentsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const commentsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class CommentApi extends ModelApi<Comment, CommentId, CommentCreate, CommentUpdate, CommentQuery, CommentFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/comments/");
  }
}

export interface DocumentTemplate {
  content_types: Array<number>;
  created_by: number | null;
  custom_styling: string;
  datetime_created: string;
  datetime_updated: string;
  default_signature_layout: string | null;
  footer: string | null;
  free_variables: unknown;
  id: string;
  include_page_numbers: boolean;
  name: string;
  object_labels: unknown;
  page_margin: number;
  page_orientation: string;
  page_size: string;
  style_sets: Array<string>;
  template: string;
  template_header: string | null;
  updated_by: number | null;
}

export type DocumentTemplateId = string;
export type DocumentTemplateFieldName = "content_types" | "created_by" | "custom_styling" | "datetime_created" | "datetime_updated" | "default_signature_layout" | "footer" | "free_variables" | "id" | "include_page_numbers" | "name" | "object_labels" | "page_margin" | "page_orientation" | "page_size" | "style_sets" | "template" | "template_header" | "updated_by";

export interface DocumentTemplateCreate {
  content_types?: Array<number>;
  created_by?: number | null;
  custom_styling?: string;
  default_signature_layout?: string | null;
  footer?: string | null;
  free_variables?: unknown;
  include_page_numbers?: boolean;
  name: string;
  page_margin?: number;
  page_orientation?: string;
  page_size?: string;
  style_sets?: Array<string>;
  template?: string;
  template_header?: string | null;
  updated_by?: number | null;
}

export type DocumentTemplateUpdate = Partial<DocumentTemplateCreate>;
export type DocumentTemplateQuery = Partial<Record<DocumentTemplateFieldName | `${DocumentTemplateFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const documentTemplatesFields: Record<DocumentTemplateFieldName, BloomerpFieldMetadata> = {
  "content_types": {"name": "content_types", "title": "Content Types", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "custom_styling": {"name": "custom_styling", "title": "Custom Styling", "fieldType": "CodeField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "default_signature_layout": {"name": "default_signature_layout", "title": "Default signature layout", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "SignatureLayout", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "footer": {"name": "footer", "title": "Footer", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "free_variables": {"name": "free_variables", "title": "Free Variables", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "include_page_numbers": {"name": "include_page_numbers", "title": "Include Page Numbers", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "page_margin": {"name": "page_margin", "title": "Page Margin", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "page_orientation": {"name": "page_orientation", "title": "Page Orientation", "fieldType": "CharField", "dbFieldType": "varchar(10)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "portrait", "label": "Portrait"}, {"value": "landscape", "label": "Landscape"}]},
  "page_size": {"name": "page_size", "title": "Page Size", "fieldType": "CharField", "dbFieldType": "varchar(10)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "A4", "label": "A4"}, {"value": "Letter", "label": "Letter"}, {"value": "A3", "label": "A3"}]},
  "style_sets": {"name": "style_sets", "title": "Style Sets", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "DocumentTemplateStyling", "editable": true, "requiredOnCreate": false, "tsType": "Array<string>", "choices": null},
  "template": {"name": "template", "title": "Template", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "template_header": {"name": "template_header", "title": "Template Header", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "DocumentTemplateHeader", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const documentTemplatesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const documentTemplatesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class DocumentTemplateApi extends ModelApi<DocumentTemplate, DocumentTemplateId, DocumentTemplateCreate, DocumentTemplateUpdate, DocumentTemplateQuery, DocumentTemplateFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/document_templates/");
  }
}

export interface DocumentTemplateHeader {
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  header: string;
  height: number;
  id: string;
  margin_bottom: number;
  margin_left: number;
  margin_right: number;
  margin_top: number;
  name: string;
  object_labels: unknown;
  updated_by: number | null;
}

export type DocumentTemplateHeaderId = string;
export type DocumentTemplateHeaderFieldName = "created_by" | "datetime_created" | "datetime_updated" | "header" | "height" | "id" | "margin_bottom" | "margin_left" | "margin_right" | "margin_top" | "name" | "object_labels" | "updated_by";

export interface DocumentTemplateHeaderCreate {
  created_by?: number | null;
  header: string;
  height?: number;
  margin_bottom?: number;
  margin_left?: number;
  margin_right?: number;
  margin_top?: number;
  name: string;
  updated_by?: number | null;
}

export type DocumentTemplateHeaderUpdate = Partial<DocumentTemplateHeaderCreate>;
export type DocumentTemplateHeaderQuery = Partial<Record<DocumentTemplateHeaderFieldName | `${DocumentTemplateHeaderFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const documentTemplateHeadersFields: Record<DocumentTemplateHeaderFieldName, BloomerpFieldMetadata> = {
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "header": {"name": "header", "title": "Header", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "height": {"name": "height", "title": "Height", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "margin_bottom": {"name": "margin_bottom", "title": "Margin Bottom", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "margin_left": {"name": "margin_left", "title": "Margin Left", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "margin_right": {"name": "margin_right", "title": "Margin Right", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "margin_top": {"name": "margin_top", "title": "Margin Top", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const documentTemplateHeadersCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const documentTemplateHeadersPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class DocumentTemplateHeaderApi extends ModelApi<DocumentTemplateHeader, DocumentTemplateHeaderId, DocumentTemplateHeaderCreate, DocumentTemplateHeaderUpdate, DocumentTemplateHeaderQuery, DocumentTemplateHeaderFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/document_template_headers/");
  }
}

export interface DocumentTemplateStyling {
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: string;
  name: string;
  object_labels: unknown;
  styling: string;
  updated_by: number | null;
}

export type DocumentTemplateStylingId = string;
export type DocumentTemplateStylingFieldName = "created_by" | "datetime_created" | "datetime_updated" | "id" | "name" | "object_labels" | "styling" | "updated_by";

export interface DocumentTemplateStylingCreate {
  created_by?: number | null;
  name: string;
  styling?: string;
  updated_by?: number | null;
}

export type DocumentTemplateStylingUpdate = Partial<DocumentTemplateStylingCreate>;
export type DocumentTemplateStylingQuery = Partial<Record<DocumentTemplateStylingFieldName | `${DocumentTemplateStylingFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const documentTemplateStylingsFields: Record<DocumentTemplateStylingFieldName, BloomerpFieldMetadata> = {
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "styling": {"name": "styling", "title": "Styling", "fieldType": "CodeField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const documentTemplateStylingsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const documentTemplateStylingsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class DocumentTemplateStylingApi extends ModelApi<DocumentTemplateStyling, DocumentTemplateStylingId, DocumentTemplateStylingCreate, DocumentTemplateStylingUpdate, DocumentTemplateStylingQuery, DocumentTemplateStylingFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/document_template_stylings/");
  }
}

export interface EmailDraft {
  avatar: string | null;
  content_type: number | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  email_account: string | null;
  id: string;
  object_id: string;
  object_labels: unknown;
  payload: unknown;
  pending_send: unknown;
  updated_by: number | null;
  user: number;
}

export type EmailDraftId = string;
export type EmailDraftFieldName = "avatar" | "content_type" | "created_by" | "datetime_created" | "datetime_updated" | "email_account" | "id" | "object_id" | "object_labels" | "payload" | "pending_send" | "updated_by" | "user";

export interface EmailDraftCreate {
  avatar?: string | null;
  content_type?: number | null;
  created_by?: number | null;
  email_account?: string | null;
  object_id?: string;
  payload?: unknown;
  updated_by?: number | null;
  user: number;
}

export type EmailDraftUpdate = Partial<EmailDraftCreate>;
export type EmailDraftQuery = Partial<Record<EmailDraftFieldName | `${EmailDraftFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const emailDraftsFields: Record<EmailDraftFieldName, BloomerpFieldMetadata> = {
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "email_account": {"name": "email_account", "title": "Email Account", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "EmailAccount", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_id": {"name": "object_id", "title": "Object Id", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "payload": {"name": "payload", "title": "Payload", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "pending_send": {"name": "pending_send", "title": "Pending Send", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const emailDraftsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const emailDraftsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class EmailDraftApi extends ModelApi<EmailDraft, EmailDraftId, EmailDraftCreate, EmailDraftUpdate, EmailDraftQuery, EmailDraftFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/email_drafts/");
  }
}

export interface FieldPolicy {
  content_type: number;
  id: number;
  name: string;
  rule: unknown;
}

export type FieldPolicyId = number;
export type FieldPolicyFieldName = "content_type" | "id" | "name" | "rule";

export interface FieldPolicyCreate {
  content_type: number;
  name: string;
  rule: unknown;
}

export type FieldPolicyUpdate = Partial<FieldPolicyCreate>;
export type FieldPolicyQuery = Partial<Record<FieldPolicyFieldName | `${FieldPolicyFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const accessControlFieldPoliciesFields: Record<FieldPolicyFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "rule": {"name": "rule", "title": "Rule", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "unknown", "choices": null},
} as const;

export const accessControlFieldPoliciesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const accessControlFieldPoliciesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class FieldPolicyApi extends ModelApi<FieldPolicy, FieldPolicyId, FieldPolicyCreate, FieldPolicyUpdate, FieldPolicyQuery, FieldPolicyFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/access_control_field_policies/");
  }
}

export interface FileNode {
  content: string | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: string;
  kind: string;
  meta: unknown;
  name: string;
  object_labels: unknown;
  parent: string | null;
  updated_by: number | null;
}

export type FileNodeId = string;
export type FileNodeFieldName = "content" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "kind" | "meta" | "name" | "object_labels" | "parent" | "updated_by";

export interface FileNodeCreate {
  content?: string | null;
  created_by?: number | null;
  kind: string;
  meta?: unknown;
  name: string;
  parent?: string | null;
  updated_by?: number | null;
}

export type FileNodeUpdate = Partial<FileNodeCreate>;
export type FileNodeQuery = Partial<Record<FileNodeFieldName | `${FileNodeFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const fileNodesFields: Record<FileNodeFieldName, BloomerpFieldMetadata> = {
  "content": {"name": "content", "title": "Content", "fieldType": "FileField", "dbFieldType": "varchar(255)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "kind": {"name": "kind", "title": "Kind", "fieldType": "CharField", "dbFieldType": "varchar(9)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "FILE", "label": "File"}, {"value": "FOLDER", "label": "Folder"}]},
  "meta": {"name": "meta", "title": "Meta", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "parent": {"name": "parent", "title": "Parent", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "FileNode", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const fileNodesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const fileNodesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class FileNodeApi extends ModelApi<FileNode, FileNodeId, FileNodeCreate, FileNodeUpdate, FileNodeQuery, FileNodeFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/file_nodes/");
  }
}

export interface FileReference {
  application_field: number | null;
  content_type: number;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  file: string;
  id: string;
  object_id: string;
  object_labels: unknown;
  occurrence_id: string;
  updated_by: number | null;
}

export type FileReferenceId = string;
export type FileReferenceFieldName = "application_field" | "content_type" | "created_by" | "datetime_created" | "datetime_updated" | "file" | "id" | "object_id" | "object_labels" | "occurrence_id" | "updated_by";

export interface FileReferenceCreate {
  application_field?: number | null;
  content_type: number;
  created_by?: number | null;
  file: string;
  object_id: string;
  occurrence_id?: string;
  updated_by?: number | null;
}

export type FileReferenceUpdate = Partial<FileReferenceCreate>;
export type FileReferenceQuery = Partial<Record<FileReferenceFieldName | `${FileReferenceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const fileReferencesFields: Record<FileReferenceFieldName, BloomerpFieldMetadata> = {
  "application_field": {"name": "application_field", "title": "Application Field", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "ApplicationField", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "file": {"name": "file", "title": "File", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": "FileNode", "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_id": {"name": "object_id", "title": "Object Id", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "occurrence_id": {"name": "occurrence_id", "title": "Occurrence Id", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const fileReferencesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const fileReferencesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class FileReferenceApi extends ModelApi<FileReference, FileReferenceId, FileReferenceCreate, FileReferenceUpdate, FileReferenceQuery, FileReferenceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/file_references/");
  }
}

export interface Form {
  avatar: string | null;
  closes_at: string;
  content_type: number;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  description: string | null;
  id: string;
  initial_payload: unknown;
  layout: unknown;
  max_submissions: number;
  max_submissions_per_ip: number;
  name: string;
  object_labels: unknown;
  opens_at: string;
  public_embed_enabled: boolean;
  requires_authentication: boolean;
  requires_review: boolean;
  success_text: string | null;
  updated_by: number | null;
}

export type FormId = string;
export type FormFieldName = "avatar" | "closes_at" | "content_type" | "created_by" | "datetime_created" | "datetime_updated" | "description" | "id" | "initial_payload" | "layout" | "max_submissions" | "max_submissions_per_ip" | "name" | "object_labels" | "opens_at" | "public_embed_enabled" | "requires_authentication" | "requires_review" | "success_text" | "updated_by";

export interface FormCreate {
  avatar?: string | null;
  closes_at?: string;
  content_type: number;
  created_by?: number | null;
  description?: string | null;
  initial_payload?: unknown;
  layout?: unknown;
  max_submissions?: number;
  max_submissions_per_ip?: number;
  name?: string;
  opens_at?: string;
  public_embed_enabled?: boolean;
  requires_authentication?: boolean;
  requires_review?: boolean;
  success_text?: string | null;
  updated_by?: number | null;
}

export type FormUpdate = Partial<FormCreate>;
export type FormQuery = Partial<Record<FormFieldName | `${FormFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const formsFields: Record<FormFieldName, BloomerpFieldMetadata> = {
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "closes_at": {"name": "closes_at", "title": "Closes At", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "description": {"name": "description", "title": "Description", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "initial_payload": {"name": "initial_payload", "title": "Initial Payload", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "layout": {"name": "layout", "title": "Layout", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "max_submissions": {"name": "max_submissions", "title": "Max Submissions", "fieldType": "IntegerField", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "max_submissions_per_ip": {"name": "max_submissions_per_ip", "title": "Max Submissions Per IP", "fieldType": "IntegerField", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "opens_at": {"name": "opens_at", "title": "Opens At", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "public_embed_enabled": {"name": "public_embed_enabled", "title": "Public Embed Enabled", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "requires_authentication": {"name": "requires_authentication", "title": "Requires Authentication", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "requires_review": {"name": "requires_review", "title": "Requires Review", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "success_text": {"name": "success_text", "title": "Success Text", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const formsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const formsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class FormApi extends ModelApi<Form, FormId, FormCreate, FormUpdate, FormQuery, FormFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/forms/");
  }
}

export interface FormSubmission {
  created_by: number | null;
  data: unknown;
  datetime_created: string;
  datetime_updated: string;
  form: string | null;
  id: string;
  ip_address: unknown;
  object_labels: unknown;
  persisted: boolean;
  updated_by: number | null;
}

export type FormSubmissionId = string;
export type FormSubmissionFieldName = "created_by" | "data" | "datetime_created" | "datetime_updated" | "form" | "id" | "ip_address" | "object_labels" | "persisted" | "updated_by";

export interface FormSubmissionCreate {
  created_by?: number | null;
  data: unknown;
  form?: string | null;
  ip_address?: unknown;
  updated_by?: number | null;
}

export type FormSubmissionUpdate = Partial<FormSubmissionCreate>;
export type FormSubmissionQuery = Partial<Record<FormSubmissionFieldName | `${FormSubmissionFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const formSubmissionsFields: Record<FormSubmissionFieldName, BloomerpFieldMetadata> = {
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "data": {"name": "data", "title": "Data", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "unknown", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "form": {"name": "form", "title": "Form", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "Form", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "ip_address": {"name": "ip_address", "title": "IP Address", "fieldType": "IPAddressField", "dbFieldType": "char(39)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "persisted": {"name": "persisted", "title": "Persisted", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const formSubmissionsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const formSubmissionsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class FormSubmissionApi extends ModelApi<FormSubmission, FormSubmissionId, FormSubmissionCreate, FormSubmissionUpdate, FormSubmissionQuery, FormSubmissionFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/form_submissions/");
  }
}

export interface Inbox {
  id: number;
  initial_default: boolean;
  name: string;
  selected: boolean;
  shared_with_groups: Array<number>;
  shared_with_users: Array<number>;
  source_object: number | null;
  user: number;
}

export type InboxId = number;
export type InboxFieldName = "id" | "initial_default" | "name" | "selected" | "shared_with_groups" | "shared_with_users" | "source_object" | "user";

export interface InboxCreate {
  initial_default?: boolean;
  name?: string;
  selected?: boolean;
  shared_with_groups?: Array<number>;
  shared_with_users?: Array<number>;
  source_object?: number | null;
  user: number;
}

export type InboxUpdate = Partial<InboxCreate>;
export type InboxQuery = Partial<Record<InboxFieldName | `${InboxFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const inboxesFields: Record<InboxFieldName, BloomerpFieldMetadata> = {
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "initial_default": {"name": "initial_default", "title": "Initial Default", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "shared_with_groups": {"name": "shared_with_groups", "title": "Shared With Groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "shared_with_users": {"name": "shared_with_users", "title": "Shared With Users", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "source_object": {"name": "source_object", "title": "Source Object", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "Inbox", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const inboxesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const inboxesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class InboxApi extends ModelApi<Inbox, InboxId, InboxCreate, InboxUpdate, InboxQuery, InboxFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/inboxes/");
  }
}

export interface InboxFolder {
  avatar: string | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: string;
  inbox: number;
  object_labels: unknown;
  related_object_id: string | null;
  type: string;
  updated_by: number | null;
}

export type InboxFolderId = string;
export type InboxFolderFieldName = "avatar" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "inbox" | "object_labels" | "related_object_id" | "type" | "updated_by";

export interface InboxFolderCreate {
  avatar?: string | null;
  created_by?: number | null;
  inbox: number;
  related_object_id?: string | null;
  type: string;
  updated_by?: number | null;
}

export type InboxFolderUpdate = Partial<InboxFolderCreate>;
export type InboxFolderQuery = Partial<Record<InboxFolderFieldName | `${InboxFolderFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const inboxFoldersFields: Record<InboxFolderFieldName, BloomerpFieldMetadata> = {
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "inbox": {"name": "inbox", "title": "Inbox", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "Inbox", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "related_object_id": {"name": "related_object_id", "title": "Related Object ID", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "type": {"name": "type", "title": "Type", "fieldType": "CharField", "dbFieldType": "varchar(50)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "all", "label": "All"}, {"value": "in_app_notifications", "label": "Notifications"}, {"value": "email", "label": "Emails"}, {"value": "instant_messaging", "label": "Messages"}]},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const inboxFoldersCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const inboxFoldersPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class InboxFolderApi extends ModelApi<InboxFolder, InboxFolderId, InboxFolderCreate, InboxFolderUpdate, InboxFolderQuery, InboxFolderFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/inbox_folders/");
  }
}

export interface InboxItem {
  actor: string | null;
  avatar: string | null;
  created_by: number | null;
  datetime_created: string;
  datetime_received: string;
  datetime_updated: string;
  folder: string;
  id: string;
  is_read: boolean;
  item_type: string;
  object_labels: unknown;
  raw_meta_data: unknown;
  related_item_id: string | null;
  snippet: string | null;
  title: string;
  updated_by: number | null;
}

export type InboxItemId = string;
export type InboxItemFieldName = "actor" | "avatar" | "created_by" | "datetime_created" | "datetime_received" | "datetime_updated" | "folder" | "id" | "is_read" | "item_type" | "object_labels" | "raw_meta_data" | "related_item_id" | "snippet" | "title" | "updated_by";

export interface InboxItemCreate {
  actor?: string | null;
  avatar?: string | null;
  created_by?: number | null;
  folder: string;
  is_read?: boolean;
  item_type: string;
  raw_meta_data?: unknown;
  related_item_id?: string | null;
  snippet?: string | null;
  title: string;
  updated_by?: number | null;
}

export type InboxItemUpdate = Partial<InboxItemCreate>;
export type InboxItemQuery = Partial<Record<InboxItemFieldName | `${InboxItemFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const inboxItemsFields: Record<InboxItemFieldName, BloomerpFieldMetadata> = {
  "actor": {"name": "actor", "title": "Actor", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_received": {"name": "datetime_received", "title": "Datetime Received", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "folder": {"name": "folder", "title": "Folder", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": "InboxFolder", "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "is_read": {"name": "is_read", "title": "Is Read", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "item_type": {"name": "item_type", "title": "Item Type", "fieldType": "CharField", "dbFieldType": "varchar(50)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "notification", "label": "Notification"}, {"value": "email", "label": "Email"}, {"value": "instant_messaging_item", "label": "Conversation"}]},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "raw_meta_data": {"name": "raw_meta_data", "title": "Raw Meta Data", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "related_item_id": {"name": "related_item_id", "title": "Related Item ID", "fieldType": "CharField", "dbFieldType": "varchar(1000)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "snippet": {"name": "snippet", "title": "Snippet", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "title": {"name": "title", "title": "Title", "fieldType": "CharField", "dbFieldType": "varchar(1000)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const inboxItemsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const inboxItemsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class InboxItemApi extends ModelApi<InboxItem, InboxItemId, InboxItemCreate, InboxItemUpdate, InboxItemQuery, InboxItemFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/inbox_items/");
  }
}

export interface Initiative {
  completed_at: string;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  description: string | null;
  id: string;
  name: string;
  object_labels: unknown;
  owner: number | null;
  parent: string | null;
  start_date: string;
  status: string;
  target_date: string;
  updated_by: number | null;
}

export type InitiativeId = string;
export type InitiativeFieldName = "completed_at" | "created_by" | "datetime_created" | "datetime_updated" | "description" | "id" | "name" | "object_labels" | "owner" | "parent" | "start_date" | "status" | "target_date" | "updated_by";

export interface InitiativeCreate {
  created_by?: number | null;
  description?: string | null;
  name: string;
  owner?: number | null;
  parent?: string | null;
  start_date?: string;
  status?: string;
  target_date?: string;
  updated_by?: number | null;
}

export type InitiativeUpdate = Partial<InitiativeCreate>;
export type InitiativeQuery = Partial<Record<InitiativeFieldName | `${InitiativeFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const initiativesFields: Record<InitiativeFieldName, BloomerpFieldMetadata> = {
  "completed_at": {"name": "completed_at", "title": "Completed At", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "description": {"name": "description", "title": "Description", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "owner": {"name": "owner", "title": "Owner", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "parent": {"name": "parent", "title": "Parent Initiative", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "Initiative", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "start_date": {"name": "start_date", "title": "Start Date", "fieldType": "DateField", "dbFieldType": "date", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "status": {"name": "status", "title": "Status", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "backlog", "label": "Backlog"}, {"value": "scoped", "label": "Scoped"}, {"value": "in_progress", "label": "In Progress"}, {"value": "on_hold", "label": "On Hold"}, {"value": "completed", "label": "Completed"}, {"value": "canceled", "label": "Canceled"}]},
  "target_date": {"name": "target_date", "title": "Target Date", "fieldType": "DateField", "dbFieldType": "date", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const initiativesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const initiativesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class InitiativeApi extends ModelApi<Initiative, InitiativeId, InitiativeCreate, InitiativeUpdate, InitiativeQuery, InitiativeFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/initiatives/");
  }
}

export interface OAuthAccessToken {
  client_id: string;
  expires_at: string;
  id: number;
  resource: string;
  revoked_at: string;
  scope: string;
  token_hash: string;
  user: number;
}

export type OAuthAccessTokenId = number;
export type OAuthAccessTokenFieldName = "client_id" | "expires_at" | "id" | "resource" | "revoked_at" | "scope" | "token_hash" | "user";

export interface OAuthAccessTokenCreate {
  client_id: string;
  expires_at: string;
  resource: string;
  revoked_at?: string;
  scope: string;
  token_hash: string;
  user: number;
}

export type OAuthAccessTokenUpdate = Partial<OAuthAccessTokenCreate>;
export type OAuthAccessTokenQuery = Partial<Record<OAuthAccessTokenFieldName | `${OAuthAccessTokenFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const oAuthAccessTokensFields: Record<OAuthAccessTokenFieldName, BloomerpFieldMetadata> = {
  "client_id": {"name": "client_id", "title": "Client Id", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "expires_at": {"name": "expires_at", "title": "Expires At", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "resource": {"name": "resource", "title": "Resource", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "revoked_at": {"name": "revoked_at", "title": "Revoked At", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "scope": {"name": "scope", "title": "Scope", "fieldType": "CharField", "dbFieldType": "varchar(200)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "token_hash": {"name": "token_hash", "title": "Token Hash", "fieldType": "CharField", "dbFieldType": "varchar(64)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const oAuthAccessTokensCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const oAuthAccessTokensPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class OAuthAccessTokenApi extends ModelApi<OAuthAccessToken, OAuthAccessTokenId, OAuthAccessTokenCreate, OAuthAccessTokenUpdate, OAuthAccessTokenQuery, OAuthAccessTokenFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/o_auth_access_tokens/");
  }
}

export interface OAuthAuthorizationCode {
  client_id: string;
  code_challenge: string;
  code_hash: string;
  expires_at: string;
  id: number;
  redirect_uri: string;
  resource: string;
  scope: string;
  user: number;
}

export type OAuthAuthorizationCodeId = number;
export type OAuthAuthorizationCodeFieldName = "client_id" | "code_challenge" | "code_hash" | "expires_at" | "id" | "redirect_uri" | "resource" | "scope" | "user";

export interface OAuthAuthorizationCodeCreate {
  client_id: string;
  code_challenge: string;
  code_hash: string;
  expires_at: string;
  redirect_uri: string;
  resource: string;
  scope: string;
  user: number;
}

export type OAuthAuthorizationCodeUpdate = Partial<OAuthAuthorizationCodeCreate>;
export type OAuthAuthorizationCodeQuery = Partial<Record<OAuthAuthorizationCodeFieldName | `${OAuthAuthorizationCodeFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const oAuthAuthorizationCodesFields: Record<OAuthAuthorizationCodeFieldName, BloomerpFieldMetadata> = {
  "client_id": {"name": "client_id", "title": "Client Id", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "code_challenge": {"name": "code_challenge", "title": "Code Challenge", "fieldType": "CharField", "dbFieldType": "varchar(128)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "code_hash": {"name": "code_hash", "title": "Code Hash", "fieldType": "CharField", "dbFieldType": "varchar(64)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "expires_at": {"name": "expires_at", "title": "Expires At", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "redirect_uri": {"name": "redirect_uri", "title": "Redirect Uri", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "resource": {"name": "resource", "title": "Resource", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "scope": {"name": "scope", "title": "Scope", "fieldType": "CharField", "dbFieldType": "varchar(200)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const oAuthAuthorizationCodesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const oAuthAuthorizationCodesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class OAuthAuthorizationCodeApi extends ModelApi<OAuthAuthorizationCode, OAuthAuthorizationCodeId, OAuthAuthorizationCodeCreate, OAuthAuthorizationCodeUpdate, OAuthAuthorizationCodeQuery, OAuthAuthorizationCodeFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/o_auth_authorization_codes/");
  }
}

export interface Policy {
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  default_policy_hash: string;
  default_policy_key: string | null;
  description: string;
  field_policy: number;
  global_permissions: Array<number>;
  groups: Array<number>;
  id: number;
  name: string;
  row_policy: number;
  system_created: boolean;
  updated_by: number | null;
  users: Array<number>;
}

export type PolicyId = number;
export type PolicyFieldName = "created_by" | "datetime_created" | "datetime_updated" | "default_policy_hash" | "default_policy_key" | "description" | "field_policy" | "global_permissions" | "groups" | "id" | "name" | "row_policy" | "system_created" | "updated_by" | "users";

export interface PolicyCreate {
  created_by?: number | null;
  description?: string;
  field_policy: number;
  global_permissions?: Array<number>;
  groups?: Array<number>;
  name: string;
  row_policy: number;
  updated_by?: number | null;
  users?: Array<number>;
}

export type PolicyUpdate = Partial<PolicyCreate>;
export type PolicyQuery = Partial<Record<PolicyFieldName | `${PolicyFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const accessControlPoliciesFields: Record<PolicyFieldName, BloomerpFieldMetadata> = {
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "default_policy_hash": {"name": "default_policy_hash", "title": "Default Policy Hash", "fieldType": "CharField", "dbFieldType": "varchar(64)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "default_policy_key": {"name": "default_policy_key", "title": "Default Policy Key", "fieldType": "CharField", "dbFieldType": "varchar(512)", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "description": {"name": "description", "title": "Description", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "field_policy": {"name": "field_policy", "title": "Field Policy", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "FieldPolicy", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "global_permissions": {"name": "global_permissions", "title": "Global Permissions", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Permission", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "groups": {"name": "groups", "title": "Groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "row_policy": {"name": "row_policy", "title": "Row Policy", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "RowPolicy", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "system_created": {"name": "system_created", "title": "System Created", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "users": {"name": "users", "title": "Users", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
} as const;

export const accessControlPoliciesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const accessControlPoliciesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class PolicyApi extends ModelApi<Policy, PolicyId, PolicyCreate, PolicyUpdate, PolicyQuery, PolicyFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/access_control_policies/");
  }
}

export interface RowPolicy {
  content_type: number;
  id: number;
  name: string;
}

export type RowPolicyId = number;
export type RowPolicyFieldName = "content_type" | "id" | "name";

export interface RowPolicyCreate {
  content_type: number;
  name?: string;
}

export type RowPolicyUpdate = Partial<RowPolicyCreate>;
export type RowPolicyQuery = Partial<Record<RowPolicyFieldName | `${RowPolicyFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const accessControlRowPoliciesFields: Record<RowPolicyFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
} as const;

export const accessControlRowPoliciesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const accessControlRowPoliciesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class RowPolicyApi extends ModelApi<RowPolicy, RowPolicyId, RowPolicyCreate, RowPolicyUpdate, RowPolicyQuery, RowPolicyFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/access_control_row_policies/");
  }
}

export interface RowPolicyRule {
  id: number;
  permissions: Array<number>;
  row_policy: number;
  rule: unknown;
}

export type RowPolicyRuleId = number;
export type RowPolicyRuleFieldName = "id" | "permissions" | "row_policy" | "rule";

export interface RowPolicyRuleCreate {
  permissions: Array<number>;
  row_policy: number;
  rule: unknown;
}

export type RowPolicyRuleUpdate = Partial<RowPolicyRuleCreate>;
export type RowPolicyRuleQuery = Partial<Record<RowPolicyRuleFieldName | `${RowPolicyRuleFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const accessControlRowPolicyRulesFields: Record<RowPolicyRuleFieldName, BloomerpFieldMetadata> = {
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "permissions": {"name": "permissions", "title": "Permissions", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Permission", "editable": true, "requiredOnCreate": true, "tsType": "Array<number>", "choices": null},
  "row_policy": {"name": "row_policy", "title": "Row Policy", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "RowPolicy", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "rule": {"name": "rule", "title": "Rule", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "unknown", "choices": null},
} as const;

export const accessControlRowPolicyRulesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const accessControlRowPolicyRulesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class RowPolicyRuleApi extends ModelApi<RowPolicyRule, RowPolicyRuleId, RowPolicyRuleCreate, RowPolicyRuleUpdate, RowPolicyRuleQuery, RowPolicyRuleFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/access_control_row_policy_rules/");
  }
}

export interface RowPolicyRulePermission {
  id: number;
  permission: number;
  row_policy_rule: number;
}

export type RowPolicyRulePermissionId = number;
export type RowPolicyRulePermissionFieldName = "id" | "permission" | "row_policy_rule";

export interface RowPolicyRulePermissionCreate {
  permission: number;
  row_policy_rule: number;
}

export type RowPolicyRulePermissionUpdate = Partial<RowPolicyRulePermissionCreate>;
export type RowPolicyRulePermissionQuery = Partial<Record<RowPolicyRulePermissionFieldName | `${RowPolicyRulePermissionFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const rowPolicyRulePermissionsFields: Record<RowPolicyRulePermissionFieldName, BloomerpFieldMetadata> = {
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "permission": {"name": "permission", "title": "Permission", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "Permission", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "row_policy_rule": {"name": "row_policy_rule", "title": "Row Policy Rule", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "RowPolicyRule", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const rowPolicyRulePermissionsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const rowPolicyRulePermissionsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class RowPolicyRulePermissionApi extends ModelApi<RowPolicyRulePermission, RowPolicyRulePermissionId, RowPolicyRulePermissionCreate, RowPolicyRulePermissionUpdate, RowPolicyRulePermissionQuery, RowPolicyRulePermissionFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/row_policy_rule_permissions/");
  }
}

export interface SavedFilter {
  avatar: string | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  filters: unknown;
  id: string;
  identifier: string;
  name: string;
  object_labels: unknown;
  scope: string;
  updated_by: number | null;
}

export type SavedFilterId = string;
export type SavedFilterFieldName = "avatar" | "created_by" | "datetime_created" | "datetime_updated" | "filters" | "id" | "identifier" | "name" | "object_labels" | "scope" | "updated_by";

export interface SavedFilterCreate {
  avatar?: string | null;
  created_by?: number | null;
  filters?: unknown;
  identifier: string;
  name: string;
  scope: string;
  updated_by?: number | null;
}

export type SavedFilterUpdate = Partial<SavedFilterCreate>;
export type SavedFilterQuery = Partial<Record<SavedFilterFieldName | `${SavedFilterFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const savedFiltersFields: Record<SavedFilterFieldName, BloomerpFieldMetadata> = {
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "filters": {"name": "filters", "title": "Filters", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "identifier": {"name": "identifier", "title": "Identifier", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "scope": {"name": "scope", "title": "Scope", "fieldType": "CharField", "dbFieldType": "varchar(16)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "model", "label": "Model"}, {"value": "workspace", "label": "Workspace"}]},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const savedFiltersCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const savedFiltersPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class SavedFilterApi extends ModelApi<SavedFilter, SavedFilterId, SavedFilterCreate, SavedFilterUpdate, SavedFilterQuery, SavedFilterFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/saved_filters/");
  }
}

export interface Sidebar {
  id: number;
  initial_default: boolean;
  name: string;
  selected: boolean;
  shared_with_groups: Array<number>;
  shared_with_users: Array<number>;
  source_object: number | null;
  user: number;
}

export type SidebarId = number;
export type SidebarFieldName = "id" | "initial_default" | "name" | "selected" | "shared_with_groups" | "shared_with_users" | "source_object" | "user";

export interface SidebarCreate {
  initial_default?: boolean;
  name?: string;
  selected?: boolean;
  shared_with_groups?: Array<number>;
  shared_with_users?: Array<number>;
  source_object?: number | null;
  user: number;
}

export type SidebarUpdate = Partial<SidebarCreate>;
export type SidebarQuery = Partial<Record<SidebarFieldName | `${SidebarFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const sidebarsFields: Record<SidebarFieldName, BloomerpFieldMetadata> = {
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "initial_default": {"name": "initial_default", "title": "Initial Default", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "shared_with_groups": {"name": "shared_with_groups", "title": "Shared With Groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "shared_with_users": {"name": "shared_with_users", "title": "Shared With Users", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "source_object": {"name": "source_object", "title": "Source Object", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "Sidebar", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const sidebarsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const sidebarsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class SidebarApi extends ModelApi<Sidebar, SidebarId, SidebarCreate, SidebarUpdate, SidebarQuery, SidebarFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/sidebars/");
  }
}

export interface SidebarItem {
  color: string;
  icon: string;
  id: number;
  is_folder: boolean;
  name: string;
  parent: number | null;
  position: number;
  sidebar: number;
  url: string | null;
}

export type SidebarItemId = number;
export type SidebarItemFieldName = "color" | "icon" | "id" | "is_folder" | "name" | "parent" | "position" | "sidebar" | "url";

export interface SidebarItemCreate {
  color?: string;
  icon: string;
  is_folder?: boolean;
  name: string;
  parent?: number | null;
  position?: number;
  sidebar: number;
  url?: string | null;
}

export type SidebarItemUpdate = Partial<SidebarItemCreate>;
export type SidebarItemQuery = Partial<Record<SidebarItemFieldName | `${SidebarItemFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const sidebarItemsFields: Record<SidebarItemFieldName, BloomerpFieldMetadata> = {
  "color": {"name": "color", "title": "Color", "fieldType": "CharField", "dbFieldType": "varchar(7)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "icon": {"name": "icon", "title": "Icon", "fieldType": "IconField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "is_folder": {"name": "is_folder", "title": "Is Folder", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "parent": {"name": "parent", "title": "Parent", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "SidebarItem", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "position": {"name": "position", "title": "Position", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "sidebar": {"name": "sidebar", "title": "Sidebar", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "Sidebar", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "url": {"name": "url", "title": "URL", "fieldType": "CharField", "dbFieldType": "varchar(2048)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
} as const;

export const sidebarItemsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const sidebarItemsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class SidebarItemApi extends ModelApi<SidebarItem, SidebarItemId, SidebarItemCreate, SidebarItemUpdate, SidebarItemQuery, SidebarItemFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/sidebar_items/");
  }
}

export interface SignatureRecipient {
  consent_text: string;
  consented_at: string;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  decline_reason: string;
  declined_at: string;
  email: string;
  email_delivery: unknown;
  id: string;
  name: string;
  object_labels: unknown;
  request: string;
  role_key: string;
  role_label: string;
  signed_at: string;
  signing_order: number;
  status: string;
  updated_by: number | null;
  user: number | null;
}

export type SignatureRecipientId = string;
export type SignatureRecipientFieldName = "consent_text" | "consented_at" | "created_by" | "datetime_created" | "datetime_updated" | "decline_reason" | "declined_at" | "email" | "email_delivery" | "id" | "name" | "object_labels" | "request" | "role_key" | "role_label" | "signed_at" | "signing_order" | "status" | "updated_by" | "user";

export interface SignatureRecipientCreate {
  consent_text?: string;
  consented_at?: string;
  created_by?: number | null;
  decline_reason?: string;
  declined_at?: string;
  email?: string;
  name: string;
  request: string;
  role_key: string;
  role_label: string;
  signed_at?: string;
  signing_order?: number;
  status?: string;
  updated_by?: number | null;
  user?: number | null;
}

export type SignatureRecipientUpdate = Partial<SignatureRecipientCreate>;
export type SignatureRecipientQuery = Partial<Record<SignatureRecipientFieldName | `${SignatureRecipientFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const signatureRecipientsFields: Record<SignatureRecipientFieldName, BloomerpFieldMetadata> = {
  "consent_text": {"name": "consent_text", "title": "Accepted consent text", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "consented_at": {"name": "consented_at", "title": "Consented at", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "decline_reason": {"name": "decline_reason", "title": "Decline reason", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "declined_at": {"name": "declined_at", "title": "Declined at", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "email": {"name": "email", "title": "Email", "fieldType": "EmailField", "dbFieldType": "varchar(254)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "email_delivery": {"name": "email_delivery", "title": "Email delivery", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "request": {"name": "request", "title": "Request", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": "SignatureRequest", "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "role_key": {"name": "role_key", "title": "Role key", "fieldType": "SlugField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "role_label": {"name": "role_label", "title": "Role label", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "signed_at": {"name": "signed_at", "title": "Signed at", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "signing_order": {"name": "signing_order", "title": "Signing order", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "status": {"name": "status", "title": "Status", "fieldType": "CharField", "dbFieldType": "varchar(16)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "pending", "label": "Pending"}, {"value": "viewed", "label": "Viewed"}, {"value": "signed", "label": "Signed"}, {"value": "declined", "label": "Declined"}]},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const signatureRecipientsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const signatureRecipientsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class SignatureRecipientApi extends ModelApi<SignatureRecipient, SignatureRecipientId, SignatureRecipientCreate, SignatureRecipientUpdate, SignatureRecipientQuery, SignatureRecipientFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/signature_recipients/");
  }
}

export interface SignatureRequest {
  completed_at: string;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  email_account: string | null;
  email_content: string;
  expires_at: string;
  id: string;
  object_labels: unknown;
  original_file: string;
  original_sha256: string;
  sent_at: string;
  signature_level: string;
  signed_file: string | null;
  signed_sha256: string;
  source_layout: string | null;
  source_layout_name: string;
  source_layout_revision: number;
  source_preparation: string | null;
  source_preparation_revision: number;
  status: string;
  title: string;
  updated_by: number | null;
}

export type SignatureRequestId = string;
export type SignatureRequestFieldName = "completed_at" | "created_by" | "datetime_created" | "datetime_updated" | "email_account" | "email_content" | "expires_at" | "id" | "object_labels" | "original_file" | "original_sha256" | "sent_at" | "signature_level" | "signed_file" | "signed_sha256" | "source_layout" | "source_layout_name" | "source_layout_revision" | "source_preparation" | "source_preparation_revision" | "status" | "title" | "updated_by";

export interface SignatureRequestCreate {
  completed_at?: string;
  created_by?: number | null;
  email_account?: string | null;
  email_content?: string;
  expires_at?: string;
  original_file: string;
  original_sha256?: string;
  sent_at?: string;
  signed_file?: string | null;
  signed_sha256?: string;
  source_layout?: string | null;
  source_layout_name?: string;
  source_layout_revision?: number;
  source_preparation?: string | null;
  source_preparation_revision?: number;
  status?: string;
  title: string;
  updated_by?: number | null;
}

export type SignatureRequestUpdate = Partial<SignatureRequestCreate>;
export type SignatureRequestQuery = Partial<Record<SignatureRequestFieldName | `${SignatureRequestFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const signatureRequestsFields: Record<SignatureRequestFieldName, BloomerpFieldMetadata> = {
  "completed_at": {"name": "completed_at", "title": "Completed at", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "email_account": {"name": "email_account", "title": "Sending email account", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "EmailAccount", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "email_content": {"name": "email_content", "title": "Invitation message", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "expires_at": {"name": "expires_at", "title": "Expires at", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "original_file": {"name": "original_file", "title": "Original PDF", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": "FileNode", "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "original_sha256": {"name": "original_sha256", "title": "Original SHA-256", "fieldType": "CharField", "dbFieldType": "varchar(64)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "sent_at": {"name": "sent_at", "title": "Sent at", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "signature_level": {"name": "signature_level", "title": "Signature level", "fieldType": "CharField", "dbFieldType": "varchar(16)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "simple", "label": "Simple electronic signature"}]},
  "signed_file": {"name": "signed_file", "title": "Signed PDF", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "FileNode", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "signed_sha256": {"name": "signed_sha256", "title": "Signed SHA-256", "fieldType": "CharField", "dbFieldType": "varchar(64)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "source_layout": {"name": "source_layout", "title": "Source layout", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "SignatureLayout", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "source_layout_name": {"name": "source_layout_name", "title": "Source layout name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "source_layout_revision": {"name": "source_layout_revision", "title": "Source layout revision", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "source_preparation": {"name": "source_preparation", "title": "Source preparation", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "SignaturePreparation", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "source_preparation_revision": {"name": "source_preparation_revision", "title": "Source preparation revision", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "status": {"name": "status", "title": "Status", "fieldType": "CharField", "dbFieldType": "varchar(16)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "draft", "label": "Draft"}, {"value": "sent", "label": "Sent"}, {"value": "completed", "label": "Completed"}, {"value": "declined", "label": "Declined"}, {"value": "cancelled", "label": "Cancelled"}, {"value": "expired", "label": "Expired"}]},
  "title": {"name": "title", "title": "Title", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const signatureRequestsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const signatureRequestsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class SignatureRequestApi extends ModelApi<SignatureRequest, SignatureRequestId, SignatureRequestCreate, SignatureRequestUpdate, SignatureRequestQuery, SignatureRequestFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/signature_requests/");
  }
}

export interface SignatureRequestField {
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  field_type: string;
  filled_at: string;
  height: number;
  id: string;
  key: string;
  object_labels: unknown;
  page_number: number;
  recipient: string;
  request: string;
  required: boolean;
  settings: unknown;
  updated_by: number | null;
  value: unknown;
  width: number;
  x: number;
  y: number;
}

export type SignatureRequestFieldId = string;
export type SignatureRequestFieldFieldName = "created_by" | "datetime_created" | "datetime_updated" | "field_type" | "filled_at" | "height" | "id" | "key" | "object_labels" | "page_number" | "recipient" | "request" | "required" | "settings" | "updated_by" | "value" | "width" | "x" | "y";

export interface SignatureRequestFieldCreate {
  created_by?: number | null;
  field_type: string;
  filled_at?: string;
  height?: number;
  key: string;
  page_number?: number;
  recipient: string;
  request: string;
  required?: boolean;
  settings?: unknown;
  updated_by?: number | null;
  value?: unknown;
  width?: number;
  x?: number;
  y?: number;
}

export type SignatureRequestFieldUpdate = Partial<SignatureRequestFieldCreate>;
export type SignatureRequestFieldQuery = Partial<Record<SignatureRequestFieldFieldName | `${SignatureRequestFieldFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const signatureRequestFieldsFields: Record<SignatureRequestFieldFieldName, BloomerpFieldMetadata> = {
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "field_type": {"name": "field_type", "title": "Field type", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "signature", "label": "Signature"}, {"value": "initials", "label": "Initials"}, {"value": "name", "label": "Name"}, {"value": "email", "label": "Email"}, {"value": "phone", "label": "Phone"}, {"value": "company", "label": "Company"}, {"value": "text", "label": "Text"}, {"value": "multiline_text", "label": "Multiline text"}, {"value": "checkbox", "label": "Checkbox"}, {"value": "radio", "label": "Radio buttons"}, {"value": "selection", "label": "Selection"}, {"value": "date", "label": "Date"}]},
  "filled_at": {"name": "filled_at", "title": "Filled at", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "height": {"name": "height", "title": "Height", "fieldType": "DecimalField", "dbFieldType": "decimal", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "key": {"name": "key", "title": "Key", "fieldType": "SlugField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "page_number": {"name": "page_number", "title": "Page number", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "recipient": {"name": "recipient", "title": "Recipient", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": "SignatureRecipient", "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "request": {"name": "request", "title": "Request", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": "SignatureRequest", "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "required": {"name": "required", "title": "Required", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "settings": {"name": "settings", "title": "Settings", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "value": {"name": "value", "title": "Value", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "width": {"name": "width", "title": "Width", "fieldType": "DecimalField", "dbFieldType": "decimal", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "x": {"name": "x", "title": "Left", "fieldType": "DecimalField", "dbFieldType": "decimal", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "y": {"name": "y", "title": "Top", "fieldType": "DecimalField", "dbFieldType": "decimal", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
} as const;

export const signatureRequestFieldsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const signatureRequestFieldsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class SignatureRequestFieldApi extends ModelApi<SignatureRequestField, SignatureRequestFieldId, SignatureRequestFieldCreate, SignatureRequestFieldUpdate, SignatureRequestFieldQuery, SignatureRequestFieldFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/signature_request_fields/");
  }
}

export interface SqlQuery {
  avatar: string | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: string;
  name: string;
  object_labels: unknown;
  query: string;
  updated_by: number | null;
}

export type SqlQueryId = string;
export type SqlQueryFieldName = "avatar" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "name" | "object_labels" | "query" | "updated_by";

export interface SqlQueryCreate {
  avatar?: string | null;
  created_by?: number | null;
  name: string;
  query: string;
  updated_by?: number | null;
}

export type SqlQueryUpdate = Partial<SqlQueryCreate>;
export type SqlQueryQuery = Partial<Record<SqlQueryFieldName | `${SqlQueryFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const sqlQueriesFields: Record<SqlQueryFieldName, BloomerpFieldMetadata> = {
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "query": {"name": "query", "title": "Query", "fieldType": "CodeField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const sqlQueriesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const sqlQueriesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class SqlQueryApi extends ModelApi<SqlQuery, SqlQueryId, SqlQueryCreate, SqlQueryUpdate, SqlQueryQuery, SqlQueryFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/sql_queries/");
  }
}

export interface Tile {
  auto_generated: boolean;
  avatar: string | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  description: string | null;
  icon: string;
  id: string;
  name: string;
  object_labels: unknown;
  schema: unknown;
  type: string;
  updated_by: number | null;
}

export type TileId = string;
export type TileFieldName = "auto_generated" | "avatar" | "created_by" | "datetime_created" | "datetime_updated" | "description" | "icon" | "id" | "name" | "object_labels" | "schema" | "type" | "updated_by";

export interface TileCreate {
  avatar?: string | null;
  created_by?: number | null;
  description?: string | null;
  icon?: string;
  name: string;
  schema: unknown;
  type: string;
  updated_by?: number | null;
}

export type TileUpdate = Partial<TileCreate>;
export type TileQuery = Partial<Record<TileFieldName | `${TileFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const tilesFields: Record<TileFieldName, BloomerpFieldMetadata> = {
  "auto_generated": {"name": "auto_generated", "title": "Auto Generated", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "description": {"name": "description", "title": "Description", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "icon": {"name": "icon", "title": "Icon", "fieldType": "IconField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "schema": {"name": "schema", "title": "Schema", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "unknown", "choices": null},
  "type": {"name": "type", "title": "Type", "fieldType": "CharField", "dbFieldType": "varchar(32)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "ANALYTICS_TILE", "label": "Analytics Tile"}, {"value": "CANVAS_TILE", "label": "Canvas"}, {"value": "LINKS_TILE", "label": "Links"}, {"value": "TEXT_TILE", "label": "Text"}, {"value": "DATAVIEW_TILE", "label": "Data View"}, {"value": "FORM_TILE", "label": "Form"}]},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const tilesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const tilesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class TileApi extends ModelApi<Tile, TileId, TileCreate, TileUpdate, TileQuery, TileFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/tiles/");
  }
}

export interface Todo {
  assigned_to: number | null;
  content: string | null;
  content_type: number | null;
  created_by: number | null;
  datetime_completed: string;
  datetime_created: string;
  datetime_updated: string;
  effort: number;
  id: string;
  initiative: string | null;
  object_id: string | null;
  object_labels: unknown;
  priority: string;
  requested_by: number | null;
  required_by: string;
  status: string;
  title: string;
  updated_by: number | null;
}

export type TodoId = string;
export type TodoFieldName = "assigned_to" | "content" | "content_type" | "created_by" | "datetime_completed" | "datetime_created" | "datetime_updated" | "effort" | "id" | "initiative" | "object_id" | "object_labels" | "priority" | "requested_by" | "required_by" | "status" | "title" | "updated_by";

export interface TodoCreate {
  assigned_to?: number | null;
  content?: string | null;
  content_type?: number | null;
  created_by?: number | null;
  effort?: number;
  initiative?: string | null;
  object_id?: string | null;
  priority?: string;
  requested_by?: number | null;
  required_by?: string;
  status?: string;
  title: string;
  updated_by?: number | null;
}

export type TodoUpdate = Partial<TodoCreate>;
export type TodoQuery = Partial<Record<TodoFieldName | `${TodoFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const todosFields: Record<TodoFieldName, BloomerpFieldMetadata> = {
  "assigned_to": {"name": "assigned_to", "title": "Assigned To", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "content": {"name": "content", "title": "Content", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_completed": {"name": "datetime_completed", "title": "Date Completed", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "effort": {"name": "effort", "title": "Effort", "fieldType": "IntegerField", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": [{"value": 1, "label": "XS"}, {"value": 2, "label": "S"}, {"value": 4, "label": "M"}, {"value": 8, "label": "L"}, {"value": 16, "label": "XL"}]},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "initiative": {"name": "initiative", "title": "Initiative", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "Initiative", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "object_id": {"name": "object_id", "title": "Object ID", "fieldType": "CharField", "dbFieldType": "varchar(36)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "priority": {"name": "priority", "title": "Priority", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "urgent", "label": "Urgent"}, {"value": "high", "label": "High"}, {"value": "medium", "label": "Medium"}, {"value": "low", "label": "Low"}]},
  "requested_by": {"name": "requested_by", "title": "Requested By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "required_by": {"name": "required_by", "title": "Required By", "fieldType": "DateField", "dbFieldType": "date", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "status": {"name": "status", "title": "Status", "fieldType": "CharField", "dbFieldType": "varchar(50)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "backlog", "label": "Backlog"}, {"value": "scoped", "label": "Scoped"}, {"value": "in_progress", "label": "In Progress"}, {"value": "in_review", "label": "In Review"}, {"value": "completed", "label": "Completed"}, {"value": "cancelled", "label": "Cancelled"}, {"value": "duplicate", "label": "Duplicate"}]},
  "title": {"name": "title", "title": "Title", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const todosCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const todosPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class TodoApi extends ModelApi<Todo, TodoId, TodoCreate, TodoUpdate, TodoQuery, TodoFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/todos/");
  }
}

export interface User {
  avatar: string | null;
  date_joined: string;
  date_view_preference: string;
  datetime_view_preference: string;
  default_email_account: string | null;
  detail_sidebar_view_preference: string;
  email: string;
  first_name: string;
  groups: Array<number>;
  id: number;
  is_active: boolean;
  is_staff: boolean;
  is_superuser: boolean;
  last_login: string;
  last_name: string;
  password: string;
  user_permissions: Array<number>;
  username: string;
}

export type UserId = number;
export type UserFieldName = "avatar" | "date_joined" | "date_view_preference" | "datetime_view_preference" | "default_email_account" | "detail_sidebar_view_preference" | "email" | "first_name" | "groups" | "id" | "is_active" | "is_staff" | "is_superuser" | "last_login" | "last_name" | "password" | "user_permissions" | "username";

export interface UserCreate {
  avatar?: string | null;
  date_joined?: string;
  date_view_preference?: string;
  datetime_view_preference?: string;
  default_email_account?: string | null;
  detail_sidebar_view_preference?: string;
  email?: string;
  first_name?: string;
  groups?: Array<number>;
  is_active?: boolean;
  is_staff?: boolean;
  is_superuser?: boolean;
  last_login?: string;
  last_name?: string;
  password: string;
  user_permissions?: Array<number>;
  username: string;
}

export type UserUpdate = Partial<UserCreate>;
export type UserQuery = Partial<Record<UserFieldName | `${UserFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const usersFields: Record<UserFieldName, BloomerpFieldMetadata> = {
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "date_joined": {"name": "date_joined", "title": "date joined", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "date_view_preference": {"name": "date_view_preference", "title": "Date View Preference", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "d-m-Y", "label": "Day-Month-Year (15-08-2000)"}, {"value": "m-d-Y", "label": "Month-Day-Year (08-15-2000)"}, {"value": "Y-m-d", "label": "Year-Month-Day (2000-08-15)"}]},
  "datetime_view_preference": {"name": "datetime_view_preference", "title": "Datetime View Preference", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "d-m-Y H:i", "label": "Day-Month-Year Hour:Minute (15-08-2000 12:30)"}, {"value": "m-d-Y H:i", "label": "Month-Day-Year Hour:Minute (08-15-2000 12:30)"}, {"value": "Y-m-d H:i", "label": "Year-Month-Day Hour:Minute (2000-08-15 12:30)"}]},
  "default_email_account": {"name": "default_email_account", "title": "Default Email Account", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "EmailAccount", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "detail_sidebar_view_preference": {"name": "detail_sidebar_view_preference", "title": "Detail Sidebar View Preference", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "activity", "label": "Activity"}, {"value": "comments", "label": "Comments"}]},
  "email": {"name": "email", "title": "email address", "fieldType": "EmailField", "dbFieldType": "varchar(254)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "first_name": {"name": "first_name", "title": "first name", "fieldType": "CharField", "dbFieldType": "varchar(150)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "groups": {"name": "groups", "title": "groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "is_active": {"name": "is_active", "title": "active", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "is_staff": {"name": "is_staff", "title": "staff status", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "is_superuser": {"name": "is_superuser", "title": "superuser status", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "last_login": {"name": "last_login", "title": "last login", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "last_name": {"name": "last_name", "title": "last name", "fieldType": "CharField", "dbFieldType": "varchar(150)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "password": {"name": "password", "title": "password", "fieldType": "CharField", "dbFieldType": "varchar(128)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "user_permissions": {"name": "user_permissions", "title": "user permissions", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Permission", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "username": {"name": "username", "title": "username", "fieldType": "CharField", "dbFieldType": "varchar(150)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
} as const;

export const usersCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const usersPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class UserApi extends ModelApi<User, UserId, UserCreate, UserUpdate, UserQuery, UserFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/users/");
  }
}

export interface UserDetailViewTabsPreference {
  content_type: number;
  id: number;
  initial_default: boolean;
  name: string;
  selected: boolean;
  shared_with_groups: Array<number>;
  shared_with_users: Array<number>;
  source_object: number | null;
  user: number;
}

export type UserDetailViewTabsPreferenceId = number;
export type UserDetailViewTabsPreferenceFieldName = "content_type" | "id" | "initial_default" | "name" | "selected" | "shared_with_groups" | "shared_with_users" | "source_object" | "user";

export interface UserDetailViewTabsPreferenceCreate {
  content_type: number;
  initial_default?: boolean;
  name?: string;
  selected?: boolean;
  shared_with_groups?: Array<number>;
  shared_with_users?: Array<number>;
  source_object?: number | null;
  user: number;
}

export type UserDetailViewTabsPreferenceUpdate = Partial<UserDetailViewTabsPreferenceCreate>;
export type UserDetailViewTabsPreferenceQuery = Partial<Record<UserDetailViewTabsPreferenceFieldName | `${UserDetailViewTabsPreferenceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const userDetailViewTabsPreferencesFields: Record<UserDetailViewTabsPreferenceFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "initial_default": {"name": "initial_default", "title": "Initial Default", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "shared_with_groups": {"name": "shared_with_groups", "title": "Shared With Groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "shared_with_users": {"name": "shared_with_users", "title": "Shared With Users", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "source_object": {"name": "source_object", "title": "Source Object", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "UserDetailViewTabsPreference", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const userDetailViewTabsPreferencesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const userDetailViewTabsPreferencesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class UserDetailViewTabsPreferenceApi extends ModelApi<UserDetailViewTabsPreference, UserDetailViewTabsPreferenceId, UserDetailViewTabsPreferenceCreate, UserDetailViewTabsPreferenceUpdate, UserDetailViewTabsPreferenceQuery, UserDetailViewTabsPreferenceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/user_detail_view_tabs_preferences/");
  }
}

export interface UserInboxPreference {
  avatar: string | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: string;
  object_labels: unknown;
  selected_inbox_folder: string | null;
  updated_by: number | null;
  user: number;
}

export type UserInboxPreferenceId = string;
export type UserInboxPreferenceFieldName = "avatar" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "object_labels" | "selected_inbox_folder" | "updated_by" | "user";

export interface UserInboxPreferenceCreate {
  avatar?: string | null;
  created_by?: number | null;
  selected_inbox_folder?: string | null;
  updated_by?: number | null;
  user: number;
}

export type UserInboxPreferenceUpdate = Partial<UserInboxPreferenceCreate>;
export type UserInboxPreferenceQuery = Partial<Record<UserInboxPreferenceFieldName | `${UserInboxPreferenceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const userInboxPreferencesFields: Record<UserInboxPreferenceFieldName, BloomerpFieldMetadata> = {
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "ImageField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "UUIDField", "dbFieldType": "char(32)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "object_labels": {"name": "object_labels", "title": "Object labels", "fieldType": "BloomerpLabelsField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "selected_inbox_folder": {"name": "selected_inbox_folder", "title": "Selected Inbox Folder", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "InboxFolder", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "OneToOneField", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const userInboxPreferencesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const userInboxPreferencesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class UserInboxPreferenceApi extends ModelApi<UserInboxPreference, UserInboxPreferenceId, UserInboxPreferenceCreate, UserInboxPreferenceUpdate, UserInboxPreferenceQuery, UserInboxPreferenceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/user_inbox_preferences/");
  }
}

export interface UserListViewPreference {
  content_type: number;
  default_filters: Array<string>;
  display_fields: unknown;
  id: number;
  initial_default: boolean;
  name: string;
  options: unknown;
  selected: boolean;
  shared_with_groups: Array<number>;
  shared_with_users: Array<number>;
  source_object: number | null;
  user: number;
  view_mode: string;
  view_type: string;
}

export type UserListViewPreferenceId = number;
export type UserListViewPreferenceFieldName = "content_type" | "default_filters" | "display_fields" | "id" | "initial_default" | "name" | "options" | "selected" | "shared_with_groups" | "shared_with_users" | "source_object" | "user" | "view_mode" | "view_type";

export interface UserListViewPreferenceCreate {
  content_type: number;
  default_filters?: Array<string>;
  display_fields?: unknown;
  initial_default?: boolean;
  name?: string;
  options?: unknown;
  selected?: boolean;
  shared_with_groups?: Array<number>;
  shared_with_users?: Array<number>;
  source_object?: number | null;
  user: number;
  view_mode?: string;
  view_type?: string;
}

export type UserListViewPreferenceUpdate = Partial<UserListViewPreferenceCreate>;
export type UserListViewPreferenceQuery = Partial<Record<UserListViewPreferenceFieldName | `${UserListViewPreferenceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const userListViewPreferencesFields: Record<UserListViewPreferenceFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "default_filters": {"name": "default_filters", "title": "Default Filters", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "SavedFilter", "editable": true, "requiredOnCreate": false, "tsType": "Array<string>", "choices": null},
  "display_fields": {"name": "display_fields", "title": "Display Fields", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "initial_default": {"name": "initial_default", "title": "Initial Default", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "options": {"name": "options", "title": "Options", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "shared_with_groups": {"name": "shared_with_groups", "title": "Shared With Groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "shared_with_users": {"name": "shared_with_users", "title": "Shared With Users", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "source_object": {"name": "source_object", "title": "Source Object", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "UserListViewPreference", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "view_mode": {"name": "view_mode", "title": "View mode", "fieldType": "CharField", "dbFieldType": "varchar(10)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "normal", "label": "Normal"}, {"value": "split", "label": "Split view"}, {"value": "drawer", "label": "Drawer"}]},
  "view_type": {"name": "view_type", "title": "View Type", "fieldType": "CharField", "dbFieldType": "varchar(50)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "table", "label": "Table"}, {"value": "kanban", "label": "Kanban"}, {"value": "card", "label": "Card"}, {"value": "calendar", "label": "Calendar"}, {"value": "gantt", "label": "Gantt"}, {"value": "pivot_table", "label": "Pivot"}, {"value": "file_browser", "label": "File Browser"}]},
} as const;

export const userListViewPreferencesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const userListViewPreferencesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class UserListViewPreferenceApi extends ModelApi<UserListViewPreference, UserListViewPreferenceId, UserListViewPreferenceCreate, UserListViewPreferenceUpdate, UserListViewPreferenceQuery, UserListViewPreferenceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/user_list_view_preferences/");
  }
}

export interface UserObjectLayoutPreference {
  content_type: number;
  id: number;
  initial_default: boolean;
  layout: unknown;
  name: string;
  selected: boolean;
  shared_with_groups: Array<number>;
  shared_with_users: Array<number>;
  source_object: number | null;
  user: number;
}

export type UserObjectLayoutPreferenceId = number;
export type UserObjectLayoutPreferenceFieldName = "content_type" | "id" | "initial_default" | "layout" | "name" | "selected" | "shared_with_groups" | "shared_with_users" | "source_object" | "user";

export interface UserObjectLayoutPreferenceCreate {
  content_type: number;
  initial_default?: boolean;
  layout?: unknown;
  name?: string;
  selected?: boolean;
  shared_with_groups?: Array<number>;
  shared_with_users?: Array<number>;
  source_object?: number | null;
  user: number;
}

export type UserObjectLayoutPreferenceUpdate = Partial<UserObjectLayoutPreferenceCreate>;
export type UserObjectLayoutPreferenceQuery = Partial<Record<UserObjectLayoutPreferenceFieldName | `${UserObjectLayoutPreferenceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const userObjectLayoutPreferencesFields: Record<UserObjectLayoutPreferenceFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "initial_default": {"name": "initial_default", "title": "Initial Default", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "layout": {"name": "layout", "title": "Layout", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "shared_with_groups": {"name": "shared_with_groups", "title": "Shared With Groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "shared_with_users": {"name": "shared_with_users", "title": "Shared With Users", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "source_object": {"name": "source_object", "title": "Source Object", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "UserObjectLayoutPreference", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const userObjectLayoutPreferencesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const userObjectLayoutPreferencesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class UserObjectLayoutPreferenceApi extends ModelApi<UserObjectLayoutPreference, UserObjectLayoutPreferenceId, UserObjectLayoutPreferenceCreate, UserObjectLayoutPreferenceUpdate, UserObjectLayoutPreferenceQuery, UserObjectLayoutPreferenceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/user_object_layout_preferences/");
  }
}

export interface Workflow {
  active: boolean;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  enable_logging: boolean;
  id: number;
  name: string;
  run_asynchronously: boolean;
  updated_by: number | null;
}

export type WorkflowId = number;
export type WorkflowFieldName = "active" | "created_by" | "datetime_created" | "datetime_updated" | "enable_logging" | "id" | "name" | "run_asynchronously" | "updated_by";

export interface WorkflowCreate {
  active?: boolean;
  created_by?: number | null;
  enable_logging?: boolean;
  name: string;
  run_asynchronously?: boolean;
  updated_by?: number | null;
}

export type WorkflowUpdate = Partial<WorkflowCreate>;
export type WorkflowQuery = Partial<Record<WorkflowFieldName | `${WorkflowFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workflowsFields: Record<WorkflowFieldName, BloomerpFieldMetadata> = {
  "active": {"name": "active", "title": "Active", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "enable_logging": {"name": "enable_logging", "title": "Enable Logging", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "run_asynchronously": {"name": "run_asynchronously", "title": "Run Asynchronously", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const workflowsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workflowsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkflowApi extends ModelApi<Workflow, WorkflowId, WorkflowCreate, WorkflowUpdate, WorkflowQuery, WorkflowFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workflows/");
  }
}

export interface WorkflowEdge {
  from_node: number;
  id: number;
  name: string | null;
  output_port: string;
  to_node: number;
}

export type WorkflowEdgeId = number;
export type WorkflowEdgeFieldName = "from_node" | "id" | "name" | "output_port" | "to_node";

export interface WorkflowEdgeCreate {
  from_node: number;
  name?: string | null;
  output_port?: string;
  to_node: number;
}

export type WorkflowEdgeUpdate = Partial<WorkflowEdgeCreate>;
export type WorkflowEdgeQuery = Partial<Record<WorkflowEdgeFieldName | `${WorkflowEdgeFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workflowEdgesFields: Record<WorkflowEdgeFieldName, BloomerpFieldMetadata> = {
  "from_node": {"name": "from_node", "title": "From Node", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "WorkflowNode", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(1000)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "output_port": {"name": "output_port", "title": "Output Port", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "to_node": {"name": "to_node", "title": "To Node", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "WorkflowNode", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const workflowEdgesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workflowEdgesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkflowEdgeApi extends ModelApi<WorkflowEdge, WorkflowEdgeId, WorkflowEdgeCreate, WorkflowEdgeUpdate, WorkflowEdgeQuery, WorkflowEdgeFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workflow_edges/");
  }
}

export interface WorkflowNode {
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: number;
  name: string | null;
  parameters: unknown;
  pos_x: number;
  pos_y: number;
  sub_type: string;
  type: string;
  updated_by: number | null;
  workflow: number;
}

export type WorkflowNodeId = number;
export type WorkflowNodeFieldName = "created_by" | "datetime_created" | "datetime_updated" | "id" | "name" | "parameters" | "pos_x" | "pos_y" | "sub_type" | "type" | "updated_by" | "workflow";

export interface WorkflowNodeCreate {
  created_by?: number | null;
  name?: string | null;
  parameters?: unknown;
  pos_x?: number;
  pos_y?: number;
  sub_type: string;
  type: string;
  updated_by?: number | null;
  workflow: number;
}

export type WorkflowNodeUpdate = Partial<WorkflowNodeCreate>;
export type WorkflowNodeQuery = Partial<Record<WorkflowNodeFieldName | `${WorkflowNodeFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workflowNodesFields: Record<WorkflowNodeFieldName, BloomerpFieldMetadata> = {
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "parameters": {"name": "parameters", "title": "Parameters", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "pos_x": {"name": "pos_x", "title": "Pos X", "fieldType": "IntegerField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "pos_y": {"name": "pos_y", "title": "Pos Y", "fieldType": "IntegerField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "sub_type": {"name": "sub_type", "title": "Sub Type", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "ON_OBJECT_CREATE", "label": "On Object Create"}, {"value": "ON_OBJECT_UPDATE", "label": "On Object Update"}, {"value": "ON_OBJECT_CREATE_OR_UPDATE", "label": "On Object Create or Update"}, {"value": "ON_OBJECT_DELETE", "label": "On Object Deletion"}, {"value": "SCHEDULE", "label": "On Schedule"}, {"value": "HUMAN_TRIGGER", "label": "Human Trigger"}, {"value": "SEND_EMAIL", "label": "Send Email"}, {"value": "GET_OBJECT", "label": "Get Object"}, {"value": "CREATE_OBJECT", "label": "Create Object"}, {"value": "UPDATE_OBJECT", "label": "Update Object"}, {"value": "DELETE_OBJECT", "label": "Delete Object"}, {"value": "ENRICH_DATA", "label": "Enrich Data"}, {"value": "EXTRACT_FIELD", "label": "Extract Field"}, {"value": "CALL_API", "label": "Call API"}, {"value": "LIST_OBJECTS", "label": "List Objects"}, {"value": "SEND_USER_MESSAGE", "label": "Send User Message"}, {"value": "GENERATE_PDF", "label": "Generate PDF"}, {"value": "SQL_QUERY", "label": "SQL Query"}, {"value": "COMPUTE", "label": "Compute"}, {"value": "HUMAN_IN_THE_LOOP", "label": "Human in the Loop"}, {"value": "WAIT", "label": "Wait"}, {"value": "IF_CONDITION", "label": "If Condition"}, {"value": "FILTER_OBJECTS", "label": "Filter Objects"}, {"value": "FOR_EACH", "label": "For Each"}, {"value": "COLLECT", "label": "Collect"}, {"value": "MERGE_BRANCHES", "label": "Merge Branches"}, {"value": "OBJECT_IF_CONDITION", "label": "Object If Condition"}, {"value": "RUN_WORKFLOW", "label": "Run workflow"}, {"value": "LIST_COUNT_CONDITION", "label": "List count condition"}]},
  "type": {"name": "type", "title": "Type", "fieldType": "CharField", "dbFieldType": "varchar(32)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "TRIGGER", "label": "Trigger"}, {"value": "ACTION", "label": "Action"}, {"value": "FLOW", "label": "Flow"}]},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "workflow": {"name": "workflow", "title": "Workflow", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "Workflow", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const workflowNodesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workflowNodesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkflowNodeApi extends ModelApi<WorkflowNode, WorkflowNodeId, WorkflowNodeCreate, WorkflowNodeUpdate, WorkflowNodeQuery, WorkflowNodeFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workflow_nodes/");
  }
}

export interface WorkflowRun {
  datetime_created: string;
  datetime_updated: string;
  finished_at: string;
  id: number;
  start_node: number | null;
  started_at: string;
  status: string;
  workflow: number;
}

export type WorkflowRunId = number;
export type WorkflowRunFieldName = "datetime_created" | "datetime_updated" | "finished_at" | "id" | "start_node" | "started_at" | "status" | "workflow";

export interface WorkflowRunCreate {
}

export type WorkflowRunUpdate = Partial<WorkflowRunCreate>;
export type WorkflowRunQuery = Partial<Record<WorkflowRunFieldName | `${WorkflowRunFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workflowRunsFields: Record<WorkflowRunFieldName, BloomerpFieldMetadata> = {
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "finished_at": {"name": "finished_at", "title": "Finished At", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "start_node": {"name": "start_node", "title": "Start Node", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "WorkflowNode", "editable": false, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "started_at": {"name": "started_at", "title": "Started At", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "status": {"name": "status", "title": "Status", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "QUEUED", "label": "Queued"}, {"value": "RUNNING", "label": "Running"}, {"value": "PAUSED", "label": "Paused"}, {"value": "SUCCEEDED", "label": "Succeeded"}, {"value": "FAILED", "label": "Failed"}, {"value": "CANCELLED", "label": "Cancelled"}]},
  "workflow": {"name": "workflow", "title": "Workflow", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "Workflow", "editable": false, "requiredOnCreate": false, "tsType": "number", "choices": null},
} as const;

export const workflowRunsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workflowRunsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkflowRunApi extends ModelApi<WorkflowRun, WorkflowRunId, WorkflowRunCreate, WorkflowRunUpdate, WorkflowRunQuery, WorkflowRunFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workflow_runs/");
  }
}

export interface WorkflowRunStep {
  action_id: string;
  datetime_created: string;
  datetime_updated: string;
  id: number;
  node: number | null;
  output_file: string | null;
  sequence: number;
  state: unknown;
  status: string;
  workflow_run: number;
}

export type WorkflowRunStepId = number;
export type WorkflowRunStepFieldName = "action_id" | "datetime_created" | "datetime_updated" | "id" | "node" | "output_file" | "sequence" | "state" | "status" | "workflow_run";

export interface WorkflowRunStepCreate {
  action_id: string;
  node?: number | null;
  output_file?: string | null;
  sequence: number;
  state?: unknown;
  status?: string;
  workflow_run: number;
}

export type WorkflowRunStepUpdate = Partial<WorkflowRunStepCreate>;
export type WorkflowRunStepQuery = Partial<Record<WorkflowRunStepFieldName | `${WorkflowRunStepFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workflowRunStepsFields: Record<WorkflowRunStepFieldName, BloomerpFieldMetadata> = {
  "action_id": {"name": "action_id", "title": "Action ID", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "node": {"name": "node", "title": "Node", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "WorkflowNode", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "output_file": {"name": "output_file", "title": "Output File", "fieldType": "FileField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "sequence": {"name": "sequence", "title": "Sequence", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "state": {"name": "state", "title": "State", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "status": {"name": "status", "title": "Status", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "PAUSED", "label": "Paused"}, {"value": "COMPLETED", "label": "Completed"}, {"value": "FAILED", "label": "Failed"}, {"value": "CANCELLED", "label": "Cancelled"}]},
  "workflow_run": {"name": "workflow_run", "title": "Workflow Run", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "WorkflowRun", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const workflowRunStepsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workflowRunStepsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkflowRunStepApi extends ModelApi<WorkflowRunStep, WorkflowRunStepId, WorkflowRunStepCreate, WorkflowRunStepUpdate, WorkflowRunStepQuery, WorkflowRunStepFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workflow_run_steps/");
  }
}

export interface Workspace {
  default_filters: Array<string>;
  id: number;
  initial_default: boolean;
  layout: unknown;
  module_id: string | null;
  name: string;
  selected: boolean;
  shared_with_groups: Array<number>;
  shared_with_users: Array<number>;
  source_object: number | null;
  user: number;
}

export type WorkspaceId = number;
export type WorkspaceFieldName = "default_filters" | "id" | "initial_default" | "layout" | "module_id" | "name" | "selected" | "shared_with_groups" | "shared_with_users" | "source_object" | "user";

export interface WorkspaceCreate {
  default_filters?: Array<string>;
  initial_default?: boolean;
  layout?: unknown;
  module_id?: string | null;
  name?: string;
  selected?: boolean;
  shared_with_groups?: Array<number>;
  shared_with_users?: Array<number>;
  source_object?: number | null;
  user: number;
}

export type WorkspaceUpdate = Partial<WorkspaceCreate>;
export type WorkspaceQuery = Partial<Record<WorkspaceFieldName | `${WorkspaceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workspacesFields: Record<WorkspaceFieldName, BloomerpFieldMetadata> = {
  "default_filters": {"name": "default_filters", "title": "Default Filters", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "SavedFilter", "editable": true, "requiredOnCreate": false, "tsType": "Array<string>", "choices": null},
  "id": {"name": "id", "title": "ID", "fieldType": "BigAutoField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "initial_default": {"name": "initial_default", "title": "Initial Default", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "layout": {"name": "layout", "title": "Layout", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "module_id": {"name": "module_id", "title": "Module ID", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "shared_with_groups": {"name": "shared_with_groups", "title": "Shared With Groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "shared_with_users": {"name": "shared_with_users", "title": "Shared With Users", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "source_object": {"name": "source_object", "title": "Source Object", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "Workspace", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const workspacesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "createMany": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workspacesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkspaceApi extends ModelApi<Workspace, WorkspaceId, WorkspaceCreate, WorkspaceUpdate, WorkspaceQuery, WorkspaceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workspaces/");
  }
}

export interface CustomWorkflowsSaveInputNodesItem {
  "id"?: number;
  "client_id": string;
  "type": "TRIGGER" | "ACTION" | "FLOW";
  "name"?: string | null;
  "sub_type": string;
  "parameters": unknown;
  "pos_x"?: number | null;
  "pos_y"?: number | null;
}

export interface CustomWorkflowsSaveInputEdgesItem {
  "id"?: number;
  "from_node": string;
  "to_node": string;
  "output_port"?: string;
  "name"?: string | null;
}

export interface CustomWorkflowsSaveInput {
  "workflow_id"?: number;
  "name": string;
  "nodes": Array<CustomWorkflowsSaveInputNodesItem>;
  "edges": Array<CustomWorkflowsSaveInputEdgesItem>;
}

export interface CustomWorkflowsSaveOutputNodesItemOutputPortsItem {
  "id": string;
  "label": string;
  "max_connections": number | null;
}

export interface CustomWorkflowsSaveOutputNodesItem {
  "id": number;
  "client_id": string;
  "type": "TRIGGER" | "ACTION" | "FLOW";
  "name"?: string | null;
  "sub_type": string;
  "parameters": Record<string, unknown | null>;
  "pos_x": number;
  "pos_y": number;
  "output_ports": Array<CustomWorkflowsSaveOutputNodesItemOutputPortsItem>;
}

export interface CustomWorkflowsSaveOutputEdgesItem {
  "id"?: number;
  "from_node": string;
  "to_node": string;
  "output_port"?: string;
  "name"?: string | null;
}

export interface CustomWorkflowsSaveOutput {
  "workflow_id": number;
  "name": string;
  "nodes": Array<CustomWorkflowsSaveOutputNodesItem>;
  "edges": Array<CustomWorkflowsSaveOutputEdgesItem>;
}

export class CustomApi {
  /** Reuse the SDK authentication and request transport. */
  constructor(private readonly client: BloomerpHttpClient) {}

  /** Call POST /api/workflows/save/. */
  workflowsSave(payload: CustomWorkflowsSaveInput, options?: BloomerpRequestOptions): Promise<CustomWorkflowsSaveOutput> {
    return this.client.request<CustomWorkflowsSaveOutput>("/api/workflows/save/", { ...options, method: "POST", body: JSON.stringify(payload) });
  }
}

export class BloomerpSdk {
  public readonly client: BloomerpHttpClient;
  public readonly auth: AuthApi;
  public readonly custom: CustomApi;
  public readonly metadata = {
    authStrategies: bloomerpAuthStrategyTypes,
    models: {
      aiConversations: {
        endpoint: "/api/ai_conversations/",
        capabilities: aiConversationsCapabilities,
        publicAccess: aiConversationsPublicAccess,
        fields: aiConversationsFields,
      },
      aiMessages: {
        endpoint: "/api/ai_messages/",
        capabilities: aiMessagesCapabilities,
        publicAccess: aiMessagesPublicAccess,
        fields: aiMessagesFields,
      },
      activityLogs: {
        endpoint: "/api/activity_logs/",
        capabilities: activityLogsCapabilities,
        publicAccess: activityLogsPublicAccess,
        fields: activityLogsFields,
      },
      applicationFields: {
        endpoint: "/api/application_fields/",
        capabilities: applicationFieldsCapabilities,
        publicAccess: applicationFieldsPublicAccess,
        fields: applicationFieldsFields,
      },
      bookmarks: {
        endpoint: "/api/bookmarks/",
        capabilities: bookmarksCapabilities,
        publicAccess: bookmarksPublicAccess,
        fields: bookmarksFields,
      },
      calendarBookings: {
        endpoint: "/api/calendar_bookings/",
        capabilities: calendarBookingsCapabilities,
        publicAccess: calendarBookingsPublicAccess,
        fields: calendarBookingsFields,
      },
      calendarBookingSubmissions: {
        endpoint: "/api/calendar_booking_submissions/",
        capabilities: calendarBookingSubmissionsCapabilities,
        publicAccess: calendarBookingSubmissionsPublicAccess,
        fields: calendarBookingSubmissionsFields,
      },
      calendarEvents: {
        endpoint: "/api/calendar_events/",
        capabilities: calendarEventsCapabilities,
        publicAccess: calendarEventsPublicAccess,
        fields: calendarEventsFields,
      },
      calendarEventParticipants: {
        endpoint: "/api/calendar_event_participants/",
        capabilities: calendarEventParticipantsCapabilities,
        publicAccess: calendarEventParticipantsPublicAccess,
        fields: calendarEventParticipantsFields,
      },
      comments: {
        endpoint: "/api/comments/",
        capabilities: commentsCapabilities,
        publicAccess: commentsPublicAccess,
        fields: commentsFields,
      },
      documentTemplates: {
        endpoint: "/api/document_templates/",
        capabilities: documentTemplatesCapabilities,
        publicAccess: documentTemplatesPublicAccess,
        fields: documentTemplatesFields,
      },
      documentTemplateHeaders: {
        endpoint: "/api/document_template_headers/",
        capabilities: documentTemplateHeadersCapabilities,
        publicAccess: documentTemplateHeadersPublicAccess,
        fields: documentTemplateHeadersFields,
      },
      documentTemplateStylings: {
        endpoint: "/api/document_template_stylings/",
        capabilities: documentTemplateStylingsCapabilities,
        publicAccess: documentTemplateStylingsPublicAccess,
        fields: documentTemplateStylingsFields,
      },
      emailDrafts: {
        endpoint: "/api/email_drafts/",
        capabilities: emailDraftsCapabilities,
        publicAccess: emailDraftsPublicAccess,
        fields: emailDraftsFields,
      },
      accessControlFieldPolicies: {
        endpoint: "/api/access_control_field_policies/",
        capabilities: accessControlFieldPoliciesCapabilities,
        publicAccess: accessControlFieldPoliciesPublicAccess,
        fields: accessControlFieldPoliciesFields,
      },
      fileNodes: {
        endpoint: "/api/file_nodes/",
        capabilities: fileNodesCapabilities,
        publicAccess: fileNodesPublicAccess,
        fields: fileNodesFields,
      },
      fileReferences: {
        endpoint: "/api/file_references/",
        capabilities: fileReferencesCapabilities,
        publicAccess: fileReferencesPublicAccess,
        fields: fileReferencesFields,
      },
      forms: {
        endpoint: "/api/forms/",
        capabilities: formsCapabilities,
        publicAccess: formsPublicAccess,
        fields: formsFields,
      },
      formSubmissions: {
        endpoint: "/api/form_submissions/",
        capabilities: formSubmissionsCapabilities,
        publicAccess: formSubmissionsPublicAccess,
        fields: formSubmissionsFields,
      },
      inboxes: {
        endpoint: "/api/inboxes/",
        capabilities: inboxesCapabilities,
        publicAccess: inboxesPublicAccess,
        fields: inboxesFields,
      },
      inboxFolders: {
        endpoint: "/api/inbox_folders/",
        capabilities: inboxFoldersCapabilities,
        publicAccess: inboxFoldersPublicAccess,
        fields: inboxFoldersFields,
      },
      inboxItems: {
        endpoint: "/api/inbox_items/",
        capabilities: inboxItemsCapabilities,
        publicAccess: inboxItemsPublicAccess,
        fields: inboxItemsFields,
      },
      initiatives: {
        endpoint: "/api/initiatives/",
        capabilities: initiativesCapabilities,
        publicAccess: initiativesPublicAccess,
        fields: initiativesFields,
      },
      oAuthAccessTokens: {
        endpoint: "/api/o_auth_access_tokens/",
        capabilities: oAuthAccessTokensCapabilities,
        publicAccess: oAuthAccessTokensPublicAccess,
        fields: oAuthAccessTokensFields,
      },
      oAuthAuthorizationCodes: {
        endpoint: "/api/o_auth_authorization_codes/",
        capabilities: oAuthAuthorizationCodesCapabilities,
        publicAccess: oAuthAuthorizationCodesPublicAccess,
        fields: oAuthAuthorizationCodesFields,
      },
      accessControlPolicies: {
        endpoint: "/api/access_control_policies/",
        capabilities: accessControlPoliciesCapabilities,
        publicAccess: accessControlPoliciesPublicAccess,
        fields: accessControlPoliciesFields,
      },
      accessControlRowPolicies: {
        endpoint: "/api/access_control_row_policies/",
        capabilities: accessControlRowPoliciesCapabilities,
        publicAccess: accessControlRowPoliciesPublicAccess,
        fields: accessControlRowPoliciesFields,
      },
      accessControlRowPolicyRules: {
        endpoint: "/api/access_control_row_policy_rules/",
        capabilities: accessControlRowPolicyRulesCapabilities,
        publicAccess: accessControlRowPolicyRulesPublicAccess,
        fields: accessControlRowPolicyRulesFields,
      },
      rowPolicyRulePermissions: {
        endpoint: "/api/row_policy_rule_permissions/",
        capabilities: rowPolicyRulePermissionsCapabilities,
        publicAccess: rowPolicyRulePermissionsPublicAccess,
        fields: rowPolicyRulePermissionsFields,
      },
      savedFilters: {
        endpoint: "/api/saved_filters/",
        capabilities: savedFiltersCapabilities,
        publicAccess: savedFiltersPublicAccess,
        fields: savedFiltersFields,
      },
      sidebars: {
        endpoint: "/api/sidebars/",
        capabilities: sidebarsCapabilities,
        publicAccess: sidebarsPublicAccess,
        fields: sidebarsFields,
      },
      sidebarItems: {
        endpoint: "/api/sidebar_items/",
        capabilities: sidebarItemsCapabilities,
        publicAccess: sidebarItemsPublicAccess,
        fields: sidebarItemsFields,
      },
      signatureRecipients: {
        endpoint: "/api/signature_recipients/",
        capabilities: signatureRecipientsCapabilities,
        publicAccess: signatureRecipientsPublicAccess,
        fields: signatureRecipientsFields,
      },
      signatureRequests: {
        endpoint: "/api/signature_requests/",
        capabilities: signatureRequestsCapabilities,
        publicAccess: signatureRequestsPublicAccess,
        fields: signatureRequestsFields,
      },
      signatureRequestFields: {
        endpoint: "/api/signature_request_fields/",
        capabilities: signatureRequestFieldsCapabilities,
        publicAccess: signatureRequestFieldsPublicAccess,
        fields: signatureRequestFieldsFields,
      },
      sqlQueries: {
        endpoint: "/api/sql_queries/",
        capabilities: sqlQueriesCapabilities,
        publicAccess: sqlQueriesPublicAccess,
        fields: sqlQueriesFields,
      },
      tiles: {
        endpoint: "/api/tiles/",
        capabilities: tilesCapabilities,
        publicAccess: tilesPublicAccess,
        fields: tilesFields,
      },
      todos: {
        endpoint: "/api/todos/",
        capabilities: todosCapabilities,
        publicAccess: todosPublicAccess,
        fields: todosFields,
      },
      users: {
        endpoint: "/api/users/",
        capabilities: usersCapabilities,
        publicAccess: usersPublicAccess,
        fields: usersFields,
      },
      userDetailViewTabsPreferences: {
        endpoint: "/api/user_detail_view_tabs_preferences/",
        capabilities: userDetailViewTabsPreferencesCapabilities,
        publicAccess: userDetailViewTabsPreferencesPublicAccess,
        fields: userDetailViewTabsPreferencesFields,
      },
      userInboxPreferences: {
        endpoint: "/api/user_inbox_preferences/",
        capabilities: userInboxPreferencesCapabilities,
        publicAccess: userInboxPreferencesPublicAccess,
        fields: userInboxPreferencesFields,
      },
      userListViewPreferences: {
        endpoint: "/api/user_list_view_preferences/",
        capabilities: userListViewPreferencesCapabilities,
        publicAccess: userListViewPreferencesPublicAccess,
        fields: userListViewPreferencesFields,
      },
      userObjectLayoutPreferences: {
        endpoint: "/api/user_object_layout_preferences/",
        capabilities: userObjectLayoutPreferencesCapabilities,
        publicAccess: userObjectLayoutPreferencesPublicAccess,
        fields: userObjectLayoutPreferencesFields,
      },
      workflows: {
        endpoint: "/api/workflows/",
        capabilities: workflowsCapabilities,
        publicAccess: workflowsPublicAccess,
        fields: workflowsFields,
      },
      workflowEdges: {
        endpoint: "/api/workflow_edges/",
        capabilities: workflowEdgesCapabilities,
        publicAccess: workflowEdgesPublicAccess,
        fields: workflowEdgesFields,
      },
      workflowNodes: {
        endpoint: "/api/workflow_nodes/",
        capabilities: workflowNodesCapabilities,
        publicAccess: workflowNodesPublicAccess,
        fields: workflowNodesFields,
      },
      workflowRuns: {
        endpoint: "/api/workflow_runs/",
        capabilities: workflowRunsCapabilities,
        publicAccess: workflowRunsPublicAccess,
        fields: workflowRunsFields,
      },
      workflowRunSteps: {
        endpoint: "/api/workflow_run_steps/",
        capabilities: workflowRunStepsCapabilities,
        publicAccess: workflowRunStepsPublicAccess,
        fields: workflowRunStepsFields,
      },
      workspaces: {
        endpoint: "/api/workspaces/",
        capabilities: workspacesCapabilities,
        publicAccess: workspacesPublicAccess,
        fields: workspacesFields,
      },
    },
  } as const;
  public readonly aiConversations: AIConversationApi;
  public readonly aiMessages: AIMessageApi;
  public readonly activityLogs: ActivityLogApi;
  public readonly applicationFields: ApplicationFieldApi;
  public readonly bookmarks: BookmarkApi;
  public readonly calendarBookings: CalendarBookingApi;
  public readonly calendarBookingSubmissions: CalendarBookingSubmissionApi;
  public readonly calendarEvents: CalendarEventApi;
  public readonly calendarEventParticipants: CalendarEventParticipantApi;
  public readonly comments: CommentApi;
  public readonly documentTemplates: DocumentTemplateApi;
  public readonly documentTemplateHeaders: DocumentTemplateHeaderApi;
  public readonly documentTemplateStylings: DocumentTemplateStylingApi;
  public readonly emailDrafts: EmailDraftApi;
  public readonly accessControlFieldPolicies: FieldPolicyApi;
  public readonly fileNodes: FileNodeApi;
  public readonly fileReferences: FileReferenceApi;
  public readonly forms: FormApi;
  public readonly formSubmissions: FormSubmissionApi;
  public readonly inboxes: InboxApi;
  public readonly inboxFolders: InboxFolderApi;
  public readonly inboxItems: InboxItemApi;
  public readonly initiatives: InitiativeApi;
  public readonly oAuthAccessTokens: OAuthAccessTokenApi;
  public readonly oAuthAuthorizationCodes: OAuthAuthorizationCodeApi;
  public readonly accessControlPolicies: PolicyApi;
  public readonly accessControlRowPolicies: RowPolicyApi;
  public readonly accessControlRowPolicyRules: RowPolicyRuleApi;
  public readonly rowPolicyRulePermissions: RowPolicyRulePermissionApi;
  public readonly savedFilters: SavedFilterApi;
  public readonly sidebars: SidebarApi;
  public readonly sidebarItems: SidebarItemApi;
  public readonly signatureRecipients: SignatureRecipientApi;
  public readonly signatureRequests: SignatureRequestApi;
  public readonly signatureRequestFields: SignatureRequestFieldApi;
  public readonly sqlQueries: SqlQueryApi;
  public readonly tiles: TileApi;
  public readonly todos: TodoApi;
  public readonly users: UserApi;
  public readonly userDetailViewTabsPreferences: UserDetailViewTabsPreferenceApi;
  public readonly userInboxPreferences: UserInboxPreferenceApi;
  public readonly userListViewPreferences: UserListViewPreferenceApi;
  public readonly userObjectLayoutPreferences: UserObjectLayoutPreferenceApi;
  public readonly workflows: WorkflowApi;
  public readonly workflowEdges: WorkflowEdgeApi;
  public readonly workflowNodes: WorkflowNodeApi;
  public readonly workflowRuns: WorkflowRunApi;
  public readonly workflowRunSteps: WorkflowRunStepApi;
  public readonly workspaces: WorkspaceApi;

  /** Configure shared transport and generated endpoint clients. */
  constructor(config: BloomerpSdkConfig) {
    this.client = new BloomerpHttpClient(config);
    this.auth = new AuthApi(this.client);
    this.custom = new CustomApi(this.client);
    this.aiConversations = new AIConversationApi(this.client);
    this.aiMessages = new AIMessageApi(this.client);
    this.activityLogs = new ActivityLogApi(this.client);
    this.applicationFields = new ApplicationFieldApi(this.client);
    this.bookmarks = new BookmarkApi(this.client);
    this.calendarBookings = new CalendarBookingApi(this.client);
    this.calendarBookingSubmissions = new CalendarBookingSubmissionApi(this.client);
    this.calendarEvents = new CalendarEventApi(this.client);
    this.calendarEventParticipants = new CalendarEventParticipantApi(this.client);
    this.comments = new CommentApi(this.client);
    this.documentTemplates = new DocumentTemplateApi(this.client);
    this.documentTemplateHeaders = new DocumentTemplateHeaderApi(this.client);
    this.documentTemplateStylings = new DocumentTemplateStylingApi(this.client);
    this.emailDrafts = new EmailDraftApi(this.client);
    this.accessControlFieldPolicies = new FieldPolicyApi(this.client);
    this.fileNodes = new FileNodeApi(this.client);
    this.fileReferences = new FileReferenceApi(this.client);
    this.forms = new FormApi(this.client);
    this.formSubmissions = new FormSubmissionApi(this.client);
    this.inboxes = new InboxApi(this.client);
    this.inboxFolders = new InboxFolderApi(this.client);
    this.inboxItems = new InboxItemApi(this.client);
    this.initiatives = new InitiativeApi(this.client);
    this.oAuthAccessTokens = new OAuthAccessTokenApi(this.client);
    this.oAuthAuthorizationCodes = new OAuthAuthorizationCodeApi(this.client);
    this.accessControlPolicies = new PolicyApi(this.client);
    this.accessControlRowPolicies = new RowPolicyApi(this.client);
    this.accessControlRowPolicyRules = new RowPolicyRuleApi(this.client);
    this.rowPolicyRulePermissions = new RowPolicyRulePermissionApi(this.client);
    this.savedFilters = new SavedFilterApi(this.client);
    this.sidebars = new SidebarApi(this.client);
    this.sidebarItems = new SidebarItemApi(this.client);
    this.signatureRecipients = new SignatureRecipientApi(this.client);
    this.signatureRequests = new SignatureRequestApi(this.client);
    this.signatureRequestFields = new SignatureRequestFieldApi(this.client);
    this.sqlQueries = new SqlQueryApi(this.client);
    this.tiles = new TileApi(this.client);
    this.todos = new TodoApi(this.client);
    this.users = new UserApi(this.client);
    this.userDetailViewTabsPreferences = new UserDetailViewTabsPreferenceApi(this.client);
    this.userInboxPreferences = new UserInboxPreferenceApi(this.client);
    this.userListViewPreferences = new UserListViewPreferenceApi(this.client);
    this.userObjectLayoutPreferences = new UserObjectLayoutPreferenceApi(this.client);
    this.workflows = new WorkflowApi(this.client);
    this.workflowEdges = new WorkflowEdgeApi(this.client);
    this.workflowNodes = new WorkflowNodeApi(this.client);
    this.workflowRuns = new WorkflowRunApi(this.client);
    this.workflowRunSteps = new WorkflowRunStepApi(this.client);
    this.workspaces = new WorkspaceApi(this.client);
  }
}

export default BloomerpSdk;
