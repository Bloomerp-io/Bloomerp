import { getCsrfToken } from "@/utils/cookies";
import showMessage from "@/utils/messages";
import { getComponent } from "../BaseComponent";
import { MessageType } from "../UiMessage";
import { DetailViewCell, type DetailViewCellChangeDetail, type DetailViewCellValue } from "../detail_view_components/DetailViewCell";

type BehaviorEvent = "initial" | "change";
type Evaluation = { field: string; event: BehaviorEvent };
type BehaviorResponse = {
    revision: number;
    values: Array<{ field: string; value: unknown }>;
    states: Array<{ field: string; visible: boolean }>;
    messages: Array<{ type: "info" | "success" | "warning" | "danger"; message: string }>;
};
type Field = { element: HTMLElement; cell: DetailViewCell; name: string };

/** Transport saved behavior events and apply backend results to the current form. */
export default class FormBehaviorRuntime {
    private revision = 0;
    private generation = 0;
    private pending = new Map<string, Evaluation>();
    private failed = new Map<string, Evaluation>();
    private initialSignatures = new WeakMap<HTMLElement, string>();
    private visibility = new Map<HTMLElement, { hidden: boolean; aria: string | null }>();
    private controller: AbortController | null = null;
    private running: Promise<void> | null = null;
    private form: HTMLFormElement | null;
    private destroyed = false;
    private submitting = false;
    private resubmitting = false;

    /** Bind evaluation to one layout container and its enclosing submission form. */
    public constructor(private root: HTMLElement) {
        this.form = root.closest("form");
    }

    /** Subscribe only when the server supplied an executable layout owner. */
    public initialize(): void {
        if (!this.root.dataset.behaviorUrl || !this.root.dataset.behaviorOwnerId) return;
        this.root.addEventListener(DetailViewCell.changeEventName, this.onChange);
        this.form?.addEventListener("submit", this.onSubmit, true);
        this.refresh();
    }

    /** Discard requests whose draft has been undone, reset, or replaced. */
    public invalidate(): void {
        this.revision += 1;
        this.generation += 1;
        this.controller?.abort();
        this.pending.clear();
        this.failed.clear();
    }

    /** Restore presentation alongside the container's value reset. */
    public reset(): void {
        this.invalidate();
        for (const [element, state] of this.visibility) {
            element.classList.toggle("hidden", state.hidden);
            element.removeAttribute("data-behavior-hidden");
            if (state.aria === null) element.removeAttribute("aria-hidden");
            else element.setAttribute("aria-hidden", state.aria);
        }
        this.visibility.clear();
    }

    /** Remove listeners and prevent detached forms from receiving late responses. */
    public destroy(): void {
        this.destroyed = true;
        this.invalidate();
        this.root.removeEventListener(DetailViewCell.changeEventName, this.onChange);
        this.form?.removeEventListener("submit", this.onSubmit, true);
    }

    /** Initialize newly rendered or reconfigured listeners after component setup. */
    public refresh(): void {
        this.invalidate();
        queueMicrotask((): void => {
            if (this.destroyed || !this.root.isConnected || !this.root.dataset.behaviorUrl) return;
            for (const field of this.fields()) {
                const signature = field.element.dataset.layoutItemConfig ?? "{}";
                if (this.initialSignatures.get(field.element) === signature) continue;
                this.initialSignatures.set(field.element, signature);
                if (this.listens(field, "initial")) this.enqueue({ field: field.name, event: "initial" });
            }
            void this.flush();
        });
    }

    /** Read only top-level, rendered form cells, excluding nested row editors. */
    private fields(): Field[] {
        const result: Field[] = [];
        for (const element of this.root.querySelectorAll<HTMLElement>('[bloomerp-component="detail-view-value"][data-field-name]')) {
            if (element.closest('[bloomerp-component="object-crud-view-container"]') !== this.root) continue;
            if (!element.querySelector('[data-layout-item-body] input, [data-layout-item-body] select, [data-layout-item-body] textarea')) continue;
            const cell = getComponent(element);
            if (cell instanceof DetailViewCell) result.push({ element, cell, name: element.dataset.fieldName! });
        }
        return result;
    }

    /** Inspect event subscriptions only; conditions and actions belong to the backend. */
    private listens(field: Field, event: BehaviorEvent): boolean {
        const config = JSON.parse(field.element.dataset.layoutItemConfig ?? "{}").behaviors;
        return config?.version === 1 && Array.isArray(config.behaviors)
            && config.behaviors.some((behavior: { enabled: boolean; events: BehaviorEvent[] }): boolean =>
                behavior.enabled !== false && (behavior.events ?? ["change"]).includes(event));
    }

    /** Coalesce repeated edits to a listener while preserving listener order. */
    private enqueue(evaluation: Evaluation): void {
        this.pending.set(`${evaluation.event}:${evaluation.field}`, evaluation);
    }

    /** Invalidate old snapshots on every user edit, including non-listener fields. */
    private onChange = (event: Event): void => {
        const detail = (event as CustomEvent<DetailViewCellChangeDetail>).detail;
        if (!detail || detail.source === "behavior") return;
        const field = this.fields().find((candidate: Field): boolean => candidate.cell === detail.cell);
        if (!field) return;
        this.revision += 1;
        for (const evaluation of this.failed.values()) this.enqueue(evaluation);
        this.failed.clear();
        if (this.listens(field, "change")) this.enqueue({ field: field.name, event: "change" });
        void this.flush();
    };

    /** Wait for backend changes before native or HTMX submission serializes widgets. */
    private onSubmit = (event: SubmitEvent): void => {
        if (this.resubmitting || (!this.running && !this.pending.size && !this.failed.size)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!this.submitting) void this.submitWhenReady(event.submitter);
    };

    /** Retry failed evaluations once and submit only a successfully evaluated draft. */
    private async submitWhenReady(submitter: HTMLElement | null): Promise<void> {
        this.submitting = true;
        try {
            for (const evaluation of this.failed.values()) this.enqueue(evaluation);
            this.failed.clear();
            await this.flush();
            if (this.destroyed || !this.root.isConnected || this.failed.size) return;
            this.resubmitting = true;
            this.form?.requestSubmit(submitter);
        } finally {
            this.resubmitting = false;
            this.submitting = false;
        }
    }

    /** Maintain one request at a time so later listeners see earlier results. */
    private async flush(): Promise<void> {
        if (!this.running) this.running = this.drain();
        try {
            await this.running;
        } finally {
            this.running = null;
        }
    }

    /** Evaluate queued snapshots, retrying stale results against the latest draft. */
    private async drain(): Promise<void> {
        while (this.pending.size && !this.destroyed) {
            const [key, evaluation] = this.pending.entries().next().value!;
            this.pending.delete(key);
            const revision = this.revision;
            const generation = this.generation;
            this.controller = new AbortController();
            try {
                const values: Record<string, unknown> = {};
                for (const field of this.fields()) {
                    const value = field.cell.value;
                    values[field.name] = field.element.dataset.behaviorValueKind === "json" && typeof value === "string"
                        ? (value.trim() ? JSON.parse(value) : null) : value;
                }
                const response = await fetch(this.root.dataset.behaviorUrl!, {
                    method: "POST",
                    credentials: "same-origin",
                    signal: this.controller.signal,
                    headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() ?? "" },
                    body: JSON.stringify({
                        [this.root.dataset.behaviorOwnerKey!]: this.root.dataset.behaviorOwnerId,
                        ...(this.root.dataset.behaviorObjectId ? { object_id: this.root.dataset.behaviorObjectId } : {}),
                        listener_field: evaluation.field, event: evaluation.event, revision, values,
                    }),
                });
                if (generation !== this.generation || this.destroyed) continue;
                if (revision !== this.revision) {
                    if (!this.pending.has(key)) this.enqueue(evaluation);
                    continue;
                }
                if (!response.ok || response.redirected) {
                    const error = await response.json().catch((): null => null);
                    throw new Error(error?.detail ?? error?.error ?? `Behavior evaluation failed (${response.status}).`);
                }
                const result: BehaviorResponse = await response.json();
                if (generation !== this.generation || this.destroyed) continue;
                if (revision !== this.revision) {
                    if (!this.pending.has(key)) this.enqueue(evaluation);
                    continue;
                }
                if (result.revision !== revision) throw new Error("Behavior response revision does not match the draft.");
                this.apply(result, evaluation.event === "change");
                this.failed.delete(key);
            } catch (error: unknown) {
                if (generation !== this.generation || this.destroyed) continue;
                this.failed.set(key, evaluation);
                this.message(error instanceof Error ? error.message : "Behavior evaluation failed.", MessageType.ERROR);
            }
        }
        this.controller = null;
    }

    /** Apply server values through existing widget adapters without firing more behaviors. */
    private apply(result: BehaviorResponse, trackChanges: boolean): void {
        const fields = new Map(this.fields().map((field: Field): [string, Field] => [field.name, field]));
        for (const update of [...result.values, ...result.states]) {
            if (!fields.has(update.field)) throw new Error(`Behavior target '${update.field}' is not rendered.`);
        }
        for (const update of result.values) {
            const field = fields.get(update.field);
            if (!field) throw new Error(`Behavior target '${update.field}' is not rendered.`);
            const value: DetailViewCellValue = field.element.dataset.behaviorValueKind === "json"
                ? JSON.stringify(update.value)
                : Array.isArray(update.value) ? update.value.map(String) : String(update.value ?? "");
            field.cell.setValue(value, trackChanges, "behavior");
        }
        for (const update of result.states) {
            const field = fields.get(update.field);
            if (!field) throw new Error(`Behavior target '${update.field}' is not rendered.`);
            const element = field.element;
            if (trackChanges && !this.visibility.has(element)) this.visibility.set(element, {
                hidden: element.classList.contains("hidden"), aria: element.getAttribute("aria-hidden"),
            });
            element.classList.toggle("hidden", !update.visible);
            element.toggleAttribute("data-behavior-hidden", !update.visible);
            element.setAttribute("aria-hidden", String(!update.visible));
        }
        for (const message of result.messages) {
            const types = { info: MessageType.INFO, success: MessageType.SUCCESS, warning: MessageType.WARNING, danger: MessageType.ERROR };
            this.message(message.message, types[message.type]);
        }
    }

    /** Escape backend text before passing it to the shared HTML message component. */
    private message(text: string, type: MessageType): void {
        const element = document.createElement("span");
        element.textContent = text;
        showMessage(element.innerHTML, type);
    }
}
