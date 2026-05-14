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

  private shouldSetJsonContentType(body: BodyInit | null | undefined, headers: Headers): boolean {
    return body !== undefined && body !== null && !headers.has("Content-Type");
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

export const bloomerpAuthStrategyTypes = ["session"] as const;

export interface AIConversation {
  args: unknown;
  auto_named: boolean;
  conversation_history: unknown;
  conversation_type: string;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: string;
  title: string;
  updated_by: number | null;
  user: number;
}

export type AIConversationId = string;
export type AIConversationFieldName = "args" | "auto_named" | "conversation_history" | "conversation_type" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "title" | "updated_by" | "user";

export interface AIConversationCreate {
  args?: unknown;
  auto_named?: boolean;
  conversation_history?: unknown;
  conversation_type?: string;
  created_by?: number | null;
  title?: string;
  updated_by?: number | null;
  user: number;
}

export type AIConversationUpdate = Partial<AIConversationCreate>;
export type AIConversationQuery = Partial<Record<AIConversationFieldName | `${AIConversationFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const aiConversationsFields: Record<AIConversationFieldName, BloomerpFieldMetadata> = {
  "args": {"name": "args", "title": "Args", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "auto_named": {"name": "auto_named", "title": "Auto Named", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "conversation_history": {"name": "conversation_history", "title": "Conversation History", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "conversation_type": {"name": "conversation_type", "title": "Conversation Type", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "sql", "label": "SQL"}, {"value": "document_template", "label": "Document Template Generator"}, {"value": "tiny_mce_content", "label": "TinyMCE Content Generator"}, {"value": "bloom_ai", "label": "Bloom AI"}, {"value": "code", "label": "Code Generator"}, {"value": "object_bloom_ai", "label": "Object Bloom AI"}]},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "UUIDField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "title": {"name": "title", "title": "Title", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const aiConversationsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const aiConversationsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class AIConversationApi extends ModelApi<AIConversation, AIConversationId, AIConversationCreate, AIConversationUpdate, AIConversationQuery, AIConversationFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/ai_conversations/");
  }
}

export interface ActivityLog {
  content_type: number;
  id: number;
  object_id: string;
  payload: unknown;
  timestamp: string;
  user: number | null;
}

export type ActivityLogId = number;
export type ActivityLogFieldName = "content_type" | "id" | "object_id" | "payload" | "timestamp" | "user";

export interface ActivityLogCreate {
  content_type: number;
  object_id: string;
  payload?: unknown;
  user?: number | null;
}

export type ActivityLogUpdate = Partial<ActivityLogCreate>;
export type ActivityLogQuery = Partial<Record<ActivityLogFieldName | `${ActivityLogFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const activityLogsFields: Record<ActivityLogFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "object_id": {"name": "object_id", "title": "Object Id", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "payload": {"name": "payload", "title": "Payload", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "timestamp": {"name": "timestamp", "title": "Timestamp", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const activityLogsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const activityLogsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class ActivityLogApi extends ModelApi<ActivityLog, ActivityLogId, ActivityLogCreate, ActivityLogUpdate, ActivityLogQuery, ActivityLogFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/activity_logs/");
  }
}

export interface ApplicationField {
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
export type ApplicationFieldFieldName = "content_type" | "db_column" | "db_field_type" | "db_table" | "field" | "field_type" | "id" | "meta" | "related_model";

export interface ApplicationFieldCreate {
  content_type: number;
  db_column?: string | null;
  db_field_type?: string | null;
  db_table?: string | null;
  field: string;
  field_type: string;
  meta?: unknown;
  related_model?: number | null;
}

export type ApplicationFieldUpdate = Partial<ApplicationFieldCreate>;
export type ApplicationFieldQuery = Partial<Record<ApplicationFieldFieldName | `${ApplicationFieldFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const applicationFieldsFields: Record<ApplicationFieldFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "db_column": {"name": "db_column", "title": "Db Column", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "db_field_type": {"name": "db_field_type", "title": "Db Field Type", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "db_table": {"name": "db_table", "title": "Db Table", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "field": {"name": "field", "title": "Field", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "field_type": {"name": "field_type", "title": "Field Type", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "Property", "label": "Property"}, {"value": "AutoField", "label": "Auto Field"}, {"value": "BigAutoField", "label": "Big Auto Field"}, {"value": "SmallAutoField", "label": "Small Auto Field"}, {"value": "CharField", "label": "Char Field"}, {"value": "ChoiceField", "label": "Choice Field"}, {"value": "TextField", "label": "Text Field"}, {"value": "EmailField", "label": "Email Field"}, {"value": "URLField", "label": "URL Field"}, {"value": "PhoneNumberField", "label": "Phone Number Field"}, {"value": "SlugField", "label": "Slug Field"}, {"value": "IntegerField", "label": "Integer Field"}, {"value": "FloatField", "label": "Float Field"}, {"value": "DecimalField", "label": "Decimal Field"}, {"value": "PositiveIntegerField", "label": "Positive Integer Field"}, {"value": "PositiveSmallIntegerField", "label": "Positive Small Integer Field"}, {"value": "BigIntegerField", "label": "Big Integer Field"}, {"value": "SmallIntegerField", "label": "Small Integer Field"}, {"value": "BooleanField", "label": "Boolean Field"}, {"value": "NullBooleanField", "label": "Null Boolean Field"}, {"value": "DateField", "label": "Date Field"}, {"value": "DateTimeField", "label": "DateTime Field"}, {"value": "TimeField", "label": "Time Field"}, {"value": "DurationField", "label": "Duration Field"}, {"value": "FileField", "label": "File Field"}, {"value": "ImageField", "label": "Image Field"}, {"value": "ForeignKey", "label": "Foreign Key"}, {"value": "OneToOneField", "label": "One To One Field"}, {"value": "ManyToManyField", "label": "Many To Many Field"}, {"value": "OneToManyField", "label": "One To Many Field"}, {"value": "UserField", "label": "User Field"}, {"value": "UUIDField", "label": "UUID Field"}, {"value": "BinaryField", "label": "Binary Field"}, {"value": "IPAddressField", "label": "IP Address Field"}, {"value": "GenericIPAddressField", "label": "Generic IP Address Field"}, {"value": "JSONField", "label": "JSON Field"}, {"value": "ArrayField", "label": "Array Field"}, {"value": "HStoreField", "label": "HStore Field"}, {"value": "GenericRelation", "label": "Generic Relation"}, {"value": "GenericForeignKey", "label": "Generic Foreign Key"}, {"value": "StatusField", "label": "Status Field"}, {"value": "IconField", "label": "Icon Field"}, {"value": "BloomerpFileField", "label": "Bloomerp File Field"}]},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "meta": {"name": "meta", "title": "Meta", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "related_model": {"name": "related_model", "title": "Related Model", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const applicationFieldsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
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
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "object_id": {"name": "object_id", "title": "Object Id", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const bookmarksCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const bookmarksPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class BookmarkApi extends ModelApi<Bookmark, BookmarkId, BookmarkCreate, BookmarkUpdate, BookmarkQuery, BookmarkFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/bookmarks/");
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
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "object_id": {"name": "object_id", "title": "Object Id", "fieldType": "CharField", "dbFieldType": "varchar(36)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const commentsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const commentsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class CommentApi extends ModelApi<Comment, CommentId, CommentCreate, CommentUpdate, CommentQuery, CommentFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/comments/");
  }
}

export interface DocumentTemplate {
  content_types: Array<number>;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  footer: string | null;
  free_variables: unknown;
  id: string;
  include_page_numbers: boolean;
  name: string;
  page_margin: number;
  page_orientation: string;
  page_size: string;
  save_to_folder: number | null;
  styling: string | null;
  template: string;
  template_header: string | null;
  updated_by: number | null;
}

export type DocumentTemplateId = string;
export type DocumentTemplateFieldName = "content_types" | "created_by" | "datetime_created" | "datetime_updated" | "footer" | "free_variables" | "id" | "include_page_numbers" | "name" | "page_margin" | "page_orientation" | "page_size" | "save_to_folder" | "styling" | "template" | "template_header" | "updated_by";

export interface DocumentTemplateCreate {
  content_types?: Array<number>;
  created_by?: number | null;
  footer?: string | null;
  free_variables?: unknown;
  include_page_numbers?: boolean;
  name: string;
  page_margin?: number;
  page_orientation?: string;
  page_size?: string;
  save_to_folder?: number | null;
  styling?: string | null;
  template?: string;
  template_header?: string | null;
  updated_by?: number | null;
}

export type DocumentTemplateUpdate = Partial<DocumentTemplateCreate>;
export type DocumentTemplateQuery = Partial<Record<DocumentTemplateFieldName | `${DocumentTemplateFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const documentTemplatesFields: Record<DocumentTemplateFieldName, BloomerpFieldMetadata> = {
  "content_types": {"name": "content_types", "title": "Content Types", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "footer": {"name": "footer", "title": "Footer", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "free_variables": {"name": "free_variables", "title": "Free Variables", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "UUIDField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "include_page_numbers": {"name": "include_page_numbers", "title": "Include Page Numbers", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "page_margin": {"name": "page_margin", "title": "Page Margin", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "page_orientation": {"name": "page_orientation", "title": "Page Orientation", "fieldType": "CharField", "dbFieldType": "varchar(10)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "portrait", "label": "Portrait"}, {"value": "landscape", "label": "Landscape"}]},
  "page_size": {"name": "page_size", "title": "Page Size", "fieldType": "CharField", "dbFieldType": "varchar(10)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "A4", "label": "A4"}, {"value": "Letter", "label": "Letter"}, {"value": "A3", "label": "A3"}]},
  "save_to_folder": {"name": "save_to_folder", "title": "Save To Folder", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "FileFolder", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "styling": {"name": "styling", "title": "Styling", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "DocumentTemplateStyling", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "template": {"name": "template", "title": "Template", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "template_header": {"name": "template_header", "title": "Template Header", "fieldType": "ForeignKey", "dbFieldType": "char(32)", "nullable": true, "many": false, "relatedModel": "DocumentTemplateHeader", "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const documentTemplatesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
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
  updated_by: number | null;
}

export type DocumentTemplateHeaderId = string;
export type DocumentTemplateHeaderFieldName = "created_by" | "datetime_created" | "datetime_updated" | "header" | "height" | "id" | "margin_bottom" | "margin_left" | "margin_right" | "margin_top" | "name" | "updated_by";

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
  "header": {"name": "header", "title": "Header", "fieldType": "FileField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "height": {"name": "height", "title": "Height", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "UUIDField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "margin_bottom": {"name": "margin_bottom", "title": "Margin Bottom", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "margin_left": {"name": "margin_left", "title": "Margin Left", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "margin_right": {"name": "margin_right", "title": "Margin Right", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "margin_top": {"name": "margin_top", "title": "Margin Top", "fieldType": "FloatField", "dbFieldType": "real", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const documentTemplateHeadersCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
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
  styling: string;
  updated_by: number | null;
}

export type DocumentTemplateStylingId = string;
export type DocumentTemplateStylingFieldName = "created_by" | "datetime_created" | "datetime_updated" | "id" | "name" | "styling" | "updated_by";

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
  "id": {"name": "id", "title": "Id", "fieldType": "UUIDField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "styling": {"name": "styling", "title": "Styling", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const documentTemplateStylingsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const documentTemplateStylingsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class DocumentTemplateStylingApi extends ModelApi<DocumentTemplateStyling, DocumentTemplateStylingId, DocumentTemplateStylingCreate, DocumentTemplateStylingUpdate, DocumentTemplateStylingQuery, DocumentTemplateStylingFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/document_template_stylings/");
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
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "rule": {"name": "rule", "title": "Rule", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "unknown", "choices": null},
} as const;

export const accessControlFieldPoliciesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const accessControlFieldPoliciesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class FieldPolicyApi extends ModelApi<FieldPolicy, FieldPolicyId, FieldPolicyCreate, FieldPolicyUpdate, FieldPolicyQuery, FieldPolicyFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/access_control_field_policies/");
  }
}

export interface File {
  content_type: number | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  file: string;
  folder: number | null;
  id: string;
  meta: unknown;
  name: string | null;
  object_id: string | null;
  persisted: boolean;
  updated_by: number | null;
}

export type FileId = string;
export type FileFieldName = "content_type" | "created_by" | "datetime_created" | "datetime_updated" | "file" | "folder" | "id" | "meta" | "name" | "object_id" | "persisted" | "updated_by";

export interface FileCreate {
  content_type?: number | null;
  created_by?: number | null;
  file: string;
  folder?: number | null;
  meta?: unknown;
  name?: string | null;
  object_id?: string | null;
  persisted?: boolean;
  updated_by?: number | null;
}

export type FileUpdate = Partial<FileCreate>;
export type FileQuery = Partial<Record<FileFieldName | `${FileFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const filesFields: Record<FileFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "file": {"name": "file", "title": "File", "fieldType": "FileField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "folder": {"name": "folder", "title": "Folder", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "FileFolder", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "UUIDField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "meta": {"name": "meta", "title": "Meta", "fieldType": "JSONField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "object_id": {"name": "object_id", "title": "Object Id", "fieldType": "CharField", "dbFieldType": "varchar(36)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "persisted": {"name": "persisted", "title": "Persisted", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const filesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const filesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class FileApi extends ModelApi<File, FileId, FileCreate, FileUpdate, FileQuery, FileFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/files/");
  }
}

export interface FileFolder {
  content_type: number | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: number;
  name: string;
  object_id: string | null;
  parent: number | null;
  protected: boolean;
  updated_by: number | null;
}

export type FileFolderId = number;
export type FileFolderFieldName = "content_type" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "name" | "object_id" | "parent" | "protected" | "updated_by";

export interface FileFolderCreate {
  content_type?: number | null;
  created_by?: number | null;
  name: string;
  object_id?: string | null;
  parent?: number | null;
  protected?: boolean;
  updated_by?: number | null;
}

export type FileFolderUpdate = Partial<FileFolderCreate>;
export type FileFolderQuery = Partial<Record<FileFolderFieldName | `${FileFolderFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const fileFoldersFields: Record<FileFolderFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "object_id": {"name": "object_id", "title": "Object Id", "fieldType": "CharField", "dbFieldType": "varchar(36)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "parent": {"name": "parent", "title": "Parent", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "FileFolder", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "protected": {"name": "protected", "title": "Protected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const fileFoldersCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const fileFoldersPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class FileFolderApi extends ModelApi<FileFolder, FileFolderId, FileFolderCreate, FileFolderUpdate, FileFolderQuery, FileFolderFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/file_folders/");
  }
}

export interface Policy {
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  description: string;
  field_policy: number;
  global_permissions: Array<number>;
  groups: Array<number>;
  id: number;
  name: string;
  row_policy: number;
  updated_by: number | null;
  users: Array<number>;
}

export type PolicyId = number;
export type PolicyFieldName = "created_by" | "datetime_created" | "datetime_updated" | "description" | "field_policy" | "global_permissions" | "groups" | "id" | "name" | "row_policy" | "updated_by" | "users";

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
  "description": {"name": "description", "title": "Description", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "field_policy": {"name": "field_policy", "title": "Field Policy", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "FieldPolicy", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "global_permissions": {"name": "global_permissions", "title": "Global Permissions", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Permission", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "groups": {"name": "groups", "title": "Groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "row_policy": {"name": "row_policy", "title": "Row Policy", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "RowPolicy", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "users": {"name": "users", "title": "Users", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
} as const;

export const accessControlPoliciesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
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
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
} as const;

export const accessControlRowPoliciesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
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
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "permissions": {"name": "permissions", "title": "Permissions", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Permission", "editable": true, "requiredOnCreate": true, "tsType": "Array<number>", "choices": null},
  "row_policy": {"name": "row_policy", "title": "Row Policy", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "RowPolicy", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "rule": {"name": "rule", "title": "Rule", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "unknown", "choices": null},
} as const;

export const accessControlRowPolicyRulesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
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
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "permission": {"name": "permission", "title": "Permission", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "Permission", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "row_policy_rule": {"name": "row_policy_rule", "title": "Row Policy Rule", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "RowPolicyRule", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const rowPolicyRulePermissionsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const rowPolicyRulePermissionsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class RowPolicyRulePermissionApi extends ModelApi<RowPolicyRulePermission, RowPolicyRulePermissionId, RowPolicyRulePermissionCreate, RowPolicyRulePermissionUpdate, RowPolicyRulePermissionQuery, RowPolicyRulePermissionFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/row_policy_rule_permissions/");
  }
}

export interface Sidebar {
  id: number;
  name: string;
  selected: boolean;
  user: number;
}

export type SidebarId = number;
export type SidebarFieldName = "id" | "name" | "selected" | "user";

export interface SidebarCreate {
  name?: string;
  selected?: boolean;
  user: number;
}

export type SidebarUpdate = Partial<SidebarCreate>;
export type SidebarQuery = Partial<Record<SidebarFieldName | `${SidebarFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const sidebarsFields: Record<SidebarFieldName, BloomerpFieldMetadata> = {
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const sidebarsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
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
  "icon": {"name": "icon", "title": "Icon", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "is_folder": {"name": "is_folder", "title": "Is Folder", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "parent": {"name": "parent", "title": "Parent", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "SidebarItem", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "position": {"name": "position", "title": "Position", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "sidebar": {"name": "sidebar", "title": "Sidebar", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "Sidebar", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "url": {"name": "url", "title": "Url", "fieldType": "CharField", "dbFieldType": "varchar(2048)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
} as const;

export const sidebarItemsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const sidebarItemsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class SidebarItemApi extends ModelApi<SidebarItem, SidebarItemId, SidebarItemCreate, SidebarItemUpdate, SidebarItemQuery, SidebarItemFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/sidebar_items/");
  }
}

export interface SqlQuery {
  avatar: string | null;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: string;
  name: string;
  query: string;
  updated_by: number | null;
}

export type SqlQueryId = string;
export type SqlQueryFieldName = "avatar" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "name" | "query" | "updated_by";

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
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "FileField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "UUIDField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "query": {"name": "query", "title": "Query", "fieldType": "TextField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const sqlQueriesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
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
  schema: unknown;
  type: string;
  updated_by: number | null;
}

export type TileId = string;
export type TileFieldName = "auto_generated" | "avatar" | "created_by" | "datetime_created" | "datetime_updated" | "description" | "icon" | "id" | "name" | "schema" | "type" | "updated_by";

export interface TileCreate {
  auto_generated?: boolean;
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
  "auto_generated": {"name": "auto_generated", "title": "Auto Generated", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "FileField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "description": {"name": "description", "title": "Description", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "icon": {"name": "icon", "title": "Icon", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "UUIDField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "schema": {"name": "schema", "title": "Schema", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "unknown", "choices": null},
  "type": {"name": "type", "title": "Type", "fieldType": "CharField", "dbFieldType": "varchar(32)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "ANALYTICS_TILE", "label": "Analytics Tile"}, {"value": "CANVAS_TILE", "label": "Canvas"}, {"value": "LINKS_TILE", "label": "Links"}, {"value": "TEXT_TILE", "label": "Text"}]},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const tilesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
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
  labels: Array<number>;
  object_id: string | null;
  priority: string;
  requested_by: number | null;
  required_by: string;
  status: string;
  title: string;
  updated_by: number | null;
}

export type TodoId = string;
export type TodoFieldName = "assigned_to" | "content" | "content_type" | "created_by" | "datetime_completed" | "datetime_created" | "datetime_updated" | "effort" | "id" | "labels" | "object_id" | "priority" | "requested_by" | "required_by" | "status" | "title" | "updated_by";

export interface TodoCreate {
  assigned_to?: number | null;
  content?: string | null;
  content_type?: number | null;
  created_by?: number | null;
  effort?: number;
  labels?: Array<number>;
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
  "assigned_to": {"name": "assigned_to", "title": "Assigned To", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "content": {"name": "content", "title": "Content", "fieldType": "TextField", "dbFieldType": "text", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_completed": {"name": "datetime_completed", "title": "Datetime Completed", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "effort": {"name": "effort", "title": "Effort", "fieldType": "IntegerField", "dbFieldType": "integer", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": [{"value": 1, "label": "XS"}, {"value": 2, "label": "S"}, {"value": 4, "label": "M"}, {"value": 8, "label": "L"}, {"value": 16, "label": "XL"}]},
  "id": {"name": "id", "title": "Id", "fieldType": "UUIDField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "labels": {"name": "labels", "title": "Labels", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "TodoLabel", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "object_id": {"name": "object_id", "title": "Object Id", "fieldType": "CharField", "dbFieldType": "varchar(36)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "priority": {"name": "priority", "title": "Priority", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "urgent", "label": "Urgent"}, {"value": "high", "label": "High"}, {"value": "medium", "label": "Medium"}, {"value": "low", "label": "Low"}]},
  "requested_by": {"name": "requested_by", "title": "Requested By", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "required_by": {"name": "required_by", "title": "Required By", "fieldType": "DateField", "dbFieldType": "date", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "status": {"name": "status", "title": "Status", "fieldType": "CharField", "dbFieldType": "varchar(50)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "backlog", "label": "Backlog"}, {"value": "in_progress", "label": "In Progress"}, {"value": "in_review", "label": "In Review"}, {"value": "completed", "label": "Completed"}, {"value": "cancelled", "label": "Cancelled"}, {"value": "duplicate", "label": "Duplicate"}]},
  "title": {"name": "title", "title": "Title", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const todosCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const todosPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class TodoApi extends ModelApi<Todo, TodoId, TodoCreate, TodoUpdate, TodoQuery, TodoFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/todos/");
  }
}

export interface TodoLabel {
  color: string;
  id: number;
  name: string;
}

export type TodoLabelId = number;
export type TodoLabelFieldName = "color" | "id" | "name";

export interface TodoLabelCreate {
  color: string;
  name: string;
}

export type TodoLabelUpdate = Partial<TodoLabelCreate>;
export type TodoLabelQuery = Partial<Record<TodoLabelFieldName | `${TodoLabelFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const todoLabelsFields: Record<TodoLabelFieldName, BloomerpFieldMetadata> = {
  "color": {"name": "color", "title": "Color", "fieldType": "CharField", "dbFieldType": "varchar(7)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(100)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
} as const;

export const todoLabelsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const todoLabelsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class TodoLabelApi extends ModelApi<TodoLabel, TodoLabelId, TodoLabelCreate, TodoLabelUpdate, TodoLabelQuery, TodoLabelFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/todo_labels/");
  }
}

export interface User {
  avatar: string | null;
  date_joined: string;
  date_view_preference: string;
  datetime_view_preference: string;
  email: string;
  file_view_preference: string;
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
export type UserFieldName = "avatar" | "date_joined" | "date_view_preference" | "datetime_view_preference" | "email" | "file_view_preference" | "first_name" | "groups" | "id" | "is_active" | "is_staff" | "is_superuser" | "last_login" | "last_name" | "password" | "user_permissions" | "username";

export interface UserCreate {
  avatar?: string | null;
  date_joined?: string;
  date_view_preference?: string;
  datetime_view_preference?: string;
  email?: string;
  file_view_preference?: string;
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
  "avatar": {"name": "avatar", "title": "Avatar", "fieldType": "FileField", "dbFieldType": "varchar(100)", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string | null", "choices": null},
  "date_joined": {"name": "date_joined", "title": "Date Joined", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "date_view_preference": {"name": "date_view_preference", "title": "Date View Preference", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "d-m-Y", "label": "Day-Month-Year (15-08-2000)"}, {"value": "m-d-Y", "label": "Month-Day-Year (08-15-2000)"}, {"value": "Y-m-d", "label": "Year-Month-Day (2000-08-15)"}]},
  "datetime_view_preference": {"name": "datetime_view_preference", "title": "Datetime View Preference", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "d-m-Y H:i", "label": "Day-Month-Year Hour:Minute (15-08-2000 12:30)"}, {"value": "m-d-Y H:i", "label": "Month-Day-Year Hour:Minute (08-15-2000 12:30)"}, {"value": "Y-m-d H:i", "label": "Year-Month-Day Hour:Minute (2000-08-15 12:30)"}]},
  "email": {"name": "email", "title": "Email", "fieldType": "CharField", "dbFieldType": "varchar(254)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "file_view_preference": {"name": "file_view_preference", "title": "File View Preference", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "card", "label": "Card View"}, {"value": "list", "label": "List View"}]},
  "first_name": {"name": "first_name", "title": "First Name", "fieldType": "CharField", "dbFieldType": "varchar(150)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "groups": {"name": "groups", "title": "Groups", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Group", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "is_active": {"name": "is_active", "title": "Is Active", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "is_staff": {"name": "is_staff", "title": "Is Staff", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "is_superuser": {"name": "is_superuser", "title": "Is Superuser", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "last_login": {"name": "last_login", "title": "Last Login", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": true, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "last_name": {"name": "last_name", "title": "Last Name", "fieldType": "CharField", "dbFieldType": "varchar(150)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "password": {"name": "password", "title": "Password", "fieldType": "CharField", "dbFieldType": "varchar(128)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "user_permissions": {"name": "user_permissions", "title": "User Permissions", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "Permission", "editable": true, "requiredOnCreate": false, "tsType": "Array<number>", "choices": null},
  "username": {"name": "username", "title": "Username", "fieldType": "CharField", "dbFieldType": "varchar(150)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
} as const;

export const usersCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const usersPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class UserApi extends ModelApi<User, UserId, UserCreate, UserUpdate, UserQuery, UserFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/users/");
  }
}

export interface UserCreateViewPreference {
  content_type: number;
  field_layout: unknown;
  id: number;
  name: string;
  selected: boolean;
  user: number;
}

export type UserCreateViewPreferenceId = number;
export type UserCreateViewPreferenceFieldName = "content_type" | "field_layout" | "id" | "name" | "selected" | "user";

export interface UserCreateViewPreferenceCreate {
  content_type: number;
  field_layout?: unknown;
  name?: string;
  selected?: boolean;
  user: number;
}

export type UserCreateViewPreferenceUpdate = Partial<UserCreateViewPreferenceCreate>;
export type UserCreateViewPreferenceQuery = Partial<Record<UserCreateViewPreferenceFieldName | `${UserCreateViewPreferenceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const userCreateViewPreferencesFields: Record<UserCreateViewPreferenceFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "field_layout": {"name": "field_layout", "title": "Field Layout", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const userCreateViewPreferencesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const userCreateViewPreferencesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class UserCreateViewPreferenceApi extends ModelApi<UserCreateViewPreference, UserCreateViewPreferenceId, UserCreateViewPreferenceCreate, UserCreateViewPreferenceUpdate, UserCreateViewPreferenceQuery, UserCreateViewPreferenceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/user_create_view_preferences/");
  }
}

export interface UserDetailViewPreference {
  content_type: number;
  field_layout: unknown;
  id: number;
  name: string;
  selected: boolean;
  tab_state: unknown;
  user: number;
}

export type UserDetailViewPreferenceId = number;
export type UserDetailViewPreferenceFieldName = "content_type" | "field_layout" | "id" | "name" | "selected" | "tab_state" | "user";

export interface UserDetailViewPreferenceCreate {
  content_type: number;
  field_layout?: unknown;
  name?: string;
  selected?: boolean;
  tab_state?: unknown;
  user: number;
}

export type UserDetailViewPreferenceUpdate = Partial<UserDetailViewPreferenceCreate>;
export type UserDetailViewPreferenceQuery = Partial<Record<UserDetailViewPreferenceFieldName | `${UserDetailViewPreferenceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const userDetailViewPreferencesFields: Record<UserDetailViewPreferenceFieldName, BloomerpFieldMetadata> = {
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "field_layout": {"name": "field_layout", "title": "Field Layout", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "tab_state": {"name": "tab_state", "title": "Tab State", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const userDetailViewPreferencesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const userDetailViewPreferencesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class UserDetailViewPreferenceApi extends ModelApi<UserDetailViewPreference, UserDetailViewPreferenceId, UserDetailViewPreferenceCreate, UserDetailViewPreferenceUpdate, UserDetailViewPreferenceQuery, UserDetailViewPreferenceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/user_detail_view_preferences/");
  }
}

export interface UserListViewPreference {
  calendar_end_field: number | null;
  calendar_start_field: number | null;
  calendar_view_mode: string;
  content_type: number;
  display_fields: unknown;
  id: number;
  kanban_group_by_field: number | null;
  name: string;
  page_size: number;
  page_type: string;
  selected: boolean;
  split_view_enabled: boolean;
  user: number;
  view_type: string;
}

export type UserListViewPreferenceId = number;
export type UserListViewPreferenceFieldName = "calendar_end_field" | "calendar_start_field" | "calendar_view_mode" | "content_type" | "display_fields" | "id" | "kanban_group_by_field" | "name" | "page_size" | "page_type" | "selected" | "split_view_enabled" | "user" | "view_type";

export interface UserListViewPreferenceCreate {
  calendar_end_field?: number | null;
  calendar_start_field?: number | null;
  calendar_view_mode?: string;
  content_type: number;
  display_fields?: unknown;
  kanban_group_by_field?: number | null;
  name?: string;
  page_size?: number;
  page_type?: string;
  selected?: boolean;
  split_view_enabled?: boolean;
  user: number;
  view_type?: string;
}

export type UserListViewPreferenceUpdate = Partial<UserListViewPreferenceCreate>;
export type UserListViewPreferenceQuery = Partial<Record<UserListViewPreferenceFieldName | `${UserListViewPreferenceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const userListViewPreferencesFields: Record<UserListViewPreferenceFieldName, BloomerpFieldMetadata> = {
  "calendar_end_field": {"name": "calendar_end_field", "title": "Calendar End Field", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "ApplicationField", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "calendar_start_field": {"name": "calendar_start_field", "title": "Calendar Start Field", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "ApplicationField", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "calendar_view_mode": {"name": "calendar_view_mode", "title": "Calendar View Mode", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "day", "label": "Day"}, {"value": "week", "label": "Week"}, {"value": "month", "label": "Month"}]},
  "content_type": {"name": "content_type", "title": "Content Type", "fieldType": "ForeignKey", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": "ContentType", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "display_fields": {"name": "display_fields", "title": "Display Fields", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "kanban_group_by_field": {"name": "kanban_group_by_field", "title": "Kanban Group By Field", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "ApplicationField", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "page_size": {"name": "page_size", "title": "Page Size", "fieldType": "PositiveIntegerField", "dbFieldType": "integer unsigned", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": [{"value": 10, "label": "10"}, {"value": 25, "label": "25"}, {"value": 50, "label": "50"}, {"value": 100, "label": "100"}]},
  "page_type": {"name": "page_type", "title": "Page Type", "fieldType": "CharField", "dbFieldType": "varchar(20)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "pagination", "label": "Pagination"}, {"value": "infinite_scroll", "label": "Infinite Scroll"}]},
  "selected": {"name": "selected", "title": "Selected", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "split_view_enabled": {"name": "split_view_enabled", "title": "Split View Enabled", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "view_type": {"name": "view_type", "title": "View Type", "fieldType": "CharField", "dbFieldType": "varchar(50)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": [{"value": "table", "label": "Table"}, {"value": "kanban", "label": "Kanban"}, {"value": "card", "label": "Card"}, {"value": "calendar", "label": "Calendar"}, {"value": "gant", "label": "Gant"}, {"value": "pivot_table", "label": "Pivot"}]},
} as const;

export const userListViewPreferencesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const userListViewPreferencesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class UserListViewPreferenceApi extends ModelApi<UserListViewPreference, UserListViewPreferenceId, UserListViewPreferenceCreate, UserListViewPreferenceUpdate, UserListViewPreferenceQuery, UserListViewPreferenceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/user_list_view_preferences/");
  }
}

export interface Workflow {
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: number;
  name: string;
  updated_by: number | null;
}

export type WorkflowId = number;
export type WorkflowFieldName = "created_by" | "datetime_created" | "datetime_updated" | "id" | "name" | "updated_by";

export interface WorkflowCreate {
  created_by?: number | null;
  name: string;
  updated_by?: number | null;
}

export type WorkflowUpdate = Partial<WorkflowCreate>;
export type WorkflowQuery = Partial<Record<WorkflowFieldName | `${WorkflowFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workflowsFields: Record<WorkflowFieldName, BloomerpFieldMetadata> = {
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
} as const;

export const workflowsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workflowsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkflowApi extends ModelApi<Workflow, WorkflowId, WorkflowCreate, WorkflowUpdate, WorkflowQuery, WorkflowFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workflows/");
  }
}

export interface WorkflowEdge {
  from_node: number;
  id: number;
  to_node: number;
}

export type WorkflowEdgeId = number;
export type WorkflowEdgeFieldName = "from_node" | "id" | "to_node";

export interface WorkflowEdgeCreate {
  from_node: number;
  to_node: number;
}

export type WorkflowEdgeUpdate = Partial<WorkflowEdgeCreate>;
export type WorkflowEdgeQuery = Partial<Record<WorkflowEdgeFieldName | `${WorkflowEdgeFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workflowEdgesFields: Record<WorkflowEdgeFieldName, BloomerpFieldMetadata> = {
  "from_node": {"name": "from_node", "title": "From Node", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "WorkflowNode", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "to_node": {"name": "to_node", "title": "To Node", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "WorkflowNode", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const workflowEdgesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workflowEdgesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkflowEdgeApi extends ModelApi<WorkflowEdge, WorkflowEdgeId, WorkflowEdgeCreate, WorkflowEdgeUpdate, WorkflowEdgeQuery, WorkflowEdgeFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workflow_edges/");
  }
}

export interface WorkflowNode {
  config: unknown;
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: number;
  pos_x: number;
  pos_y: number;
  type: string;
  updated_by: number | null;
  workflow: number;
}

export type WorkflowNodeId = number;
export type WorkflowNodeFieldName = "config" | "created_by" | "datetime_created" | "datetime_updated" | "id" | "pos_x" | "pos_y" | "type" | "updated_by" | "workflow";

export interface WorkflowNodeCreate {
  config?: unknown;
  created_by?: number | null;
  pos_x?: number;
  pos_y?: number;
  type: string;
  updated_by?: number | null;
  workflow: number;
}

export type WorkflowNodeUpdate = Partial<WorkflowNodeCreate>;
export type WorkflowNodeQuery = Partial<Record<WorkflowNodeFieldName | `${WorkflowNodeFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workflowNodesFields: Record<WorkflowNodeFieldName, BloomerpFieldMetadata> = {
  "config": {"name": "config", "title": "Config", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "pos_x": {"name": "pos_x", "title": "Pos X", "fieldType": "IntegerField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "pos_y": {"name": "pos_y", "title": "Pos Y", "fieldType": "IntegerField", "dbFieldType": "integer", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "type": {"name": "type", "title": "Type", "fieldType": "CharField", "dbFieldType": "varchar(32)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": true, "tsType": "string", "choices": [{"value": "TRIGGER", "label": "Trigger"}, {"value": "ACTION", "label": "Action"}, {"value": "FLOW", "label": "Flow"}]},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "workflow": {"name": "workflow", "title": "Workflow", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "Workflow", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const workflowNodesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workflowNodesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkflowNodeApi extends ModelApi<WorkflowNode, WorkflowNodeId, WorkflowNodeCreate, WorkflowNodeUpdate, WorkflowNodeQuery, WorkflowNodeFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workflow_nodes/");
  }
}

export interface WorkflowRun {
  created_by: number | null;
  datetime_created: string;
  datetime_updated: string;
  id: number;
  updated_by: number | null;
  workflow: number;
}

export type WorkflowRunId = number;
export type WorkflowRunFieldName = "created_by" | "datetime_created" | "datetime_updated" | "id" | "updated_by" | "workflow";

export interface WorkflowRunCreate {
  created_by?: number | null;
  updated_by?: number | null;
  workflow: number;
}

export type WorkflowRunUpdate = Partial<WorkflowRunCreate>;
export type WorkflowRunQuery = Partial<Record<WorkflowRunFieldName | `${WorkflowRunFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workflowRunsFields: Record<WorkflowRunFieldName, BloomerpFieldMetadata> = {
  "created_by": {"name": "created_by", "title": "Created By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "datetime_created": {"name": "datetime_created", "title": "Datetime Created", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "datetime_updated": {"name": "datetime_updated", "title": "Datetime Updated", "fieldType": "DateTimeField", "dbFieldType": "datetime", "nullable": false, "many": false, "relatedModel": null, "editable": false, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "updated_by": {"name": "updated_by", "title": "Updated By", "fieldType": "UserField", "dbFieldType": "bigint", "nullable": true, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": false, "tsType": "number | null", "choices": null},
  "workflow": {"name": "workflow", "title": "Workflow", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "Workflow", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const workflowRunsCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workflowRunsPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkflowRunApi extends ModelApi<WorkflowRun, WorkflowRunId, WorkflowRunCreate, WorkflowRunUpdate, WorkflowRunQuery, WorkflowRunFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workflow_runs/");
  }
}

export interface Workspace {
  id: number;
  is_default: boolean;
  layout: unknown;
  module_id: string;
  name: string;
  shared_with: Array<number>;
  user: number;
}

export type WorkspaceId = number;
export type WorkspaceFieldName = "id" | "is_default" | "layout" | "module_id" | "name" | "shared_with" | "user";

export interface WorkspaceCreate {
  is_default?: boolean;
  layout?: unknown;
  module_id?: string;
  name?: string;
  shared_with: Array<number>;
  user: number;
}

export type WorkspaceUpdate = Partial<WorkspaceCreate>;
export type WorkspaceQuery = Partial<Record<WorkspaceFieldName | `${WorkspaceFieldName}__${string}`, QueryValue | QueryValue[]>>;

export const workspacesFields: Record<WorkspaceFieldName, BloomerpFieldMetadata> = {
  "id": {"name": "id", "title": "Id", "fieldType": "BigAutoField", "dbFieldType": null, "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "number", "choices": null},
  "is_default": {"name": "is_default", "title": "Is Default", "fieldType": "BooleanField", "dbFieldType": "bool", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "boolean", "choices": null},
  "layout": {"name": "layout", "title": "Layout", "fieldType": "JSONField", "dbFieldType": "text", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "unknown", "choices": null},
  "module_id": {"name": "module_id", "title": "Module Id", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "name": {"name": "name", "title": "Name", "fieldType": "CharField", "dbFieldType": "varchar(255)", "nullable": false, "many": false, "relatedModel": null, "editable": true, "requiredOnCreate": false, "tsType": "string", "choices": null},
  "shared_with": {"name": "shared_with", "title": "Shared With", "fieldType": "ManyToManyField", "dbFieldType": null, "nullable": false, "many": true, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "Array<number>", "choices": null},
  "user": {"name": "user", "title": "User", "fieldType": "ForeignKey", "dbFieldType": "bigint", "nullable": false, "many": false, "relatedModel": "User", "editable": true, "requiredOnCreate": true, "tsType": "number", "choices": null},
} as const;

export const workspacesCapabilities: BloomerpModelCapabilities = {"list": true, "retrieve": true, "create": true, "update": true, "partialUpdate": true, "destroy": true} as const;
export const workspacesPublicAccess: BloomerpModelPublicAccessMetadata = {"listAllowed": false, "readAllowed": false, "listFields": [], "readFields": [], "nesting": [], "authenticatedFallbackEnabled": true} as const;

export class WorkspaceApi extends ModelApi<Workspace, WorkspaceId, WorkspaceCreate, WorkspaceUpdate, WorkspaceQuery, WorkspaceFieldName> {
  constructor(client: BloomerpHttpClient) {
    super(client, "/api/workspaces/");
  }
}

export class BloomerpSdk {
  public readonly client: BloomerpHttpClient;
  public readonly auth: AuthApi;
  public readonly metadata = {
    authStrategies: bloomerpAuthStrategyTypes,
    models: {
      aiConversations: {
        endpoint: "/api/ai_conversations/",
        capabilities: aiConversationsCapabilities,
        publicAccess: aiConversationsPublicAccess,
        fields: aiConversationsFields,
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
      accessControlFieldPolicies: {
        endpoint: "/api/access_control_field_policies/",
        capabilities: accessControlFieldPoliciesCapabilities,
        publicAccess: accessControlFieldPoliciesPublicAccess,
        fields: accessControlFieldPoliciesFields,
      },
      files: {
        endpoint: "/api/files/",
        capabilities: filesCapabilities,
        publicAccess: filesPublicAccess,
        fields: filesFields,
      },
      fileFolders: {
        endpoint: "/api/file_folders/",
        capabilities: fileFoldersCapabilities,
        publicAccess: fileFoldersPublicAccess,
        fields: fileFoldersFields,
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
      todoLabels: {
        endpoint: "/api/todo_labels/",
        capabilities: todoLabelsCapabilities,
        publicAccess: todoLabelsPublicAccess,
        fields: todoLabelsFields,
      },
      users: {
        endpoint: "/api/users/",
        capabilities: usersCapabilities,
        publicAccess: usersPublicAccess,
        fields: usersFields,
      },
      userCreateViewPreferences: {
        endpoint: "/api/user_create_view_preferences/",
        capabilities: userCreateViewPreferencesCapabilities,
        publicAccess: userCreateViewPreferencesPublicAccess,
        fields: userCreateViewPreferencesFields,
      },
      userDetailViewPreferences: {
        endpoint: "/api/user_detail_view_preferences/",
        capabilities: userDetailViewPreferencesCapabilities,
        publicAccess: userDetailViewPreferencesPublicAccess,
        fields: userDetailViewPreferencesFields,
      },
      userListViewPreferences: {
        endpoint: "/api/user_list_view_preferences/",
        capabilities: userListViewPreferencesCapabilities,
        publicAccess: userListViewPreferencesPublicAccess,
        fields: userListViewPreferencesFields,
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
      workspaces: {
        endpoint: "/api/workspaces/",
        capabilities: workspacesCapabilities,
        publicAccess: workspacesPublicAccess,
        fields: workspacesFields,
      },
    },
  } as const;
  public readonly aiConversations: AIConversationApi;
  public readonly activityLogs: ActivityLogApi;
  public readonly applicationFields: ApplicationFieldApi;
  public readonly bookmarks: BookmarkApi;
  public readonly comments: CommentApi;
  public readonly documentTemplates: DocumentTemplateApi;
  public readonly documentTemplateHeaders: DocumentTemplateHeaderApi;
  public readonly documentTemplateStylings: DocumentTemplateStylingApi;
  public readonly accessControlFieldPolicies: FieldPolicyApi;
  public readonly files: FileApi;
  public readonly fileFolders: FileFolderApi;
  public readonly accessControlPolicies: PolicyApi;
  public readonly accessControlRowPolicies: RowPolicyApi;
  public readonly accessControlRowPolicyRules: RowPolicyRuleApi;
  public readonly rowPolicyRulePermissions: RowPolicyRulePermissionApi;
  public readonly sidebars: SidebarApi;
  public readonly sidebarItems: SidebarItemApi;
  public readonly sqlQueries: SqlQueryApi;
  public readonly tiles: TileApi;
  public readonly todos: TodoApi;
  public readonly todoLabels: TodoLabelApi;
  public readonly users: UserApi;
  public readonly userCreateViewPreferences: UserCreateViewPreferenceApi;
  public readonly userDetailViewPreferences: UserDetailViewPreferenceApi;
  public readonly userListViewPreferences: UserListViewPreferenceApi;
  public readonly workflows: WorkflowApi;
  public readonly workflowEdges: WorkflowEdgeApi;
  public readonly workflowNodes: WorkflowNodeApi;
  public readonly workflowRuns: WorkflowRunApi;
  public readonly workspaces: WorkspaceApi;

  constructor(config: BloomerpSdkConfig) {
    this.client = new BloomerpHttpClient(config);
    this.auth = new AuthApi(this.client);
    this.aiConversations = new AIConversationApi(this.client);
    this.activityLogs = new ActivityLogApi(this.client);
    this.applicationFields = new ApplicationFieldApi(this.client);
    this.bookmarks = new BookmarkApi(this.client);
    this.comments = new CommentApi(this.client);
    this.documentTemplates = new DocumentTemplateApi(this.client);
    this.documentTemplateHeaders = new DocumentTemplateHeaderApi(this.client);
    this.documentTemplateStylings = new DocumentTemplateStylingApi(this.client);
    this.accessControlFieldPolicies = new FieldPolicyApi(this.client);
    this.files = new FileApi(this.client);
    this.fileFolders = new FileFolderApi(this.client);
    this.accessControlPolicies = new PolicyApi(this.client);
    this.accessControlRowPolicies = new RowPolicyApi(this.client);
    this.accessControlRowPolicyRules = new RowPolicyRuleApi(this.client);
    this.rowPolicyRulePermissions = new RowPolicyRulePermissionApi(this.client);
    this.sidebars = new SidebarApi(this.client);
    this.sidebarItems = new SidebarItemApi(this.client);
    this.sqlQueries = new SqlQueryApi(this.client);
    this.tiles = new TileApi(this.client);
    this.todos = new TodoApi(this.client);
    this.todoLabels = new TodoLabelApi(this.client);
    this.users = new UserApi(this.client);
    this.userCreateViewPreferences = new UserCreateViewPreferenceApi(this.client);
    this.userDetailViewPreferences = new UserDetailViewPreferenceApi(this.client);
    this.userListViewPreferences = new UserListViewPreferenceApi(this.client);
    this.workflows = new WorkflowApi(this.client);
    this.workflowEdges = new WorkflowEdgeApi(this.client);
    this.workflowNodes = new WorkflowNodeApi(this.client);
    this.workflowRuns = new WorkflowRunApi(this.client);
    this.workspaces = new WorkspaceApi(this.client);
  }
}

export default BloomerpSdk;
