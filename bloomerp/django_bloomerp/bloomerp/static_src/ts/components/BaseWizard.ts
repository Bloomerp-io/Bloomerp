import BaseComponent from "./BaseComponent";

type WizardCallback = (wizard: BaseWizard) => void;
type WizardAction = "next" | "back";

interface PendingWizardRequest {
    action: WizardAction;
    stepIndex: number;
}

interface WizardResponse {
    stepIndex: number | null;
    totalSteps: number | null;
    hasError: boolean;
    hasWizard: boolean;
}

export default class BaseWizard extends BaseComponent {
    private static callbackRegistry = new Map<string, {
        onDone: WizardCallback | null;
        onNext: WizardCallback | null;
        onPrevious: WizardCallback | null;
    }>();

    private form: HTMLFormElement | null = null;
    private submitHandler: ((event: SubmitEvent) => void) | null = null;
    private afterRequestHandler: ((event: Event) => void) | null = null;
    private pendingRequest: PendingWizardRequest | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.form = this.element.querySelector("form");
        if (!this.form) return;

        this.submitHandler = (event: SubmitEvent) => this.handleSubmit(event);
        this.afterRequestHandler = (event: Event) => this.handleAfterRequest(event);

        this.form.addEventListener("submit", this.submitHandler);
        this.form.addEventListener("htmx:afterRequest", this.afterRequestHandler);
    }

    public destroy(): void {
        if (this.form && this.submitHandler) {
            this.form.removeEventListener("submit", this.submitHandler);
        }

        if (this.form && this.afterRequestHandler) {
            this.form.removeEventListener("htmx:afterRequest", this.afterRequestHandler);
        }

        this.form = null;
        this.submitHandler = null;
        this.afterRequestHandler = null;
        this.pendingRequest = null;
    }

    public setOnDone(callback: WizardCallback): void {
        this.getCallbacks().onDone = callback;
    }

    public setOnNext(callback: WizardCallback): void {
        this.getCallbacks().onNext = callback;
    }

    public setOnPrevious(callback: WizardCallback): void {
        this.getCallbacks().onPrevious = callback;
    }

    /**
     * 
     * @returns the index (0-based)
     */
    public getCurrentStepIndex(): number {
        return this.parseNumber(this.element?.dataset.wizardStepIndex, 0);
    }

    /**
     * 
     * @returns the step number (1-based)
     */
    public getCurrentStepNumber(): number {
        return this.getCurrentStepIndex() + 1;
    }

    public getTotalSteps(): number {
        return this.parseNumber(this.element?.dataset.wizardTotalSteps, 1);
    }

    private handleSubmit(event: SubmitEvent): void {
        const submitter = event.submitter as HTMLButtonElement | HTMLInputElement | null;
        const action = submitter?.name === "_wizard_action" && submitter.value === "back" ? "back" : "next";

        this.pendingRequest = {
            action,
            stepIndex: this.getCurrentStepIndex(),
        };
    }

    private handleAfterRequest(event: Event): void {
        const pendingRequest = this.pendingRequest;
        this.pendingRequest = null;

        if (!pendingRequest) return;

        const detail = (event as CustomEvent).detail;
        if (detail?.successful === false) return;

        if (pendingRequest.action === "back") {
            this.getCallbacks().onPrevious?.(this);
            return;
        }

        const response = this.parseWizardResponse(detail?.xhr?.responseText || "");
        if (response.hasError) return;

        if (!response.hasWizard) {
            this.getCallbacks().onDone?.(this);
            return;
        }

        if (response.stepIndex !== null && response.stepIndex > pendingRequest.stepIndex) {
            this.getCallbacks().onNext?.(this);
            return;
        }

        if (
            response.stepIndex !== null
            && response.totalSteps !== null
            && pendingRequest.stepIndex >= response.totalSteps - 1
            && response.stepIndex <= pendingRequest.stepIndex
        ) {
            this.getCallbacks().onDone?.(this);
        }
    }

    private parseWizardResponse(responseText: string): WizardResponse {
        if (!responseText.trim()) {
            return { stepIndex: null, totalSteps: null, hasError: false, hasWizard: false };
        }

        const documentFragment = new DOMParser().parseFromString(responseText, "text/html");
        const wizardRoot = documentFragment.querySelector<HTMLElement>('[bloomerp-component="base-wizard"]');

        if (!wizardRoot) {
            return { stepIndex: null, totalSteps: null, hasError: false, hasWizard: false };
        }

        return {
            stepIndex: this.parseNumber(wizardRoot.dataset.wizardStepIndex, null),
            totalSteps: this.parseNumber(wizardRoot.dataset.wizardTotalSteps, null),
            hasError: wizardRoot.dataset.wizardHasError === "true",
            hasWizard: true,
        };
    }

    private getCallbacks(): { onDone: WizardCallback | null; onNext: WizardCallback | null; onPrevious: WizardCallback | null } {
        const key = this.getWizardKey();
        const callbacks = BaseWizard.callbackRegistry.get(key) || {
            onDone: null,
            onNext: null,
            onPrevious: null,
        };

        BaseWizard.callbackRegistry.set(key, callbacks);
        return callbacks;
    }

    private getWizardKey(): string {
        const action = this.form?.getAttribute("action") || window.location.href;
        const url = new URL(action, window.location.href);
        const stepQueryParam = this.element?.dataset.wizardStepQueryParam || "step";

        url.searchParams.delete(stepQueryParam);
        return `${url.pathname}?${url.searchParams.toString()}`;
    }

    private parseNumber<TFallback extends number | null>(value: string | undefined, fallback: TFallback): number | TFallback {
        const parsedValue = Number.parseInt(value || "", 10);
        return Number.isNaN(parsedValue) ? fallback : parsedValue;
    }
}
