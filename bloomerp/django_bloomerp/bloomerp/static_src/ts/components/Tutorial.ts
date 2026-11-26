import DOMPurify from "dompurify";
import Sortable, { type SortableEvent } from "sortablejs";
import BaseComponent, { getComponent } from "./BaseComponent";
import { MessageType } from "./UiMessage";
import type { BloomerpTextEditor } from "./text_editor/BloomerpTextEditor";
import { getSdk } from "../sdk/getSdk";
import { BloomerpHttpError } from "../sdk/sdk";
import type {
    CustomEligibleTutorialsOutputTutorialsItem,
    CustomTutorialPlaybackPostOutput as TutorialPresentation,
    CustomTutorialPlaybackPostOutputStepsItem as TutorialPresentationStep,
    CustomTutorialRevisionsTutorialRevisionSettingsPatchInput as TutorialRevisionSettingsPatch,
    CustomTutorialRevisionsTutorialRevisionSettingsPatchOutput as TutorialRevisionSettings,
    CustomTutorialRevisionsTutorialRevisionStepsOutputStepsItem as TutorialStepSummary,
    CustomTutorialStepsTutorialStepDetailGetOutput as TutorialStepEditorValues,
    CustomTutorialStepsTutorialStepDetailPutInput as TutorialStepUpdate,
} from "../sdk/sdk";
import { t } from "../utils/i18n";
import { getLocalStorageValue, setLocalStorageValue } from "../utils/localStorage";
import showMessage from "../utils/messages";
import { getModal, getTopModal } from "../utils/modals";
import { isMacPlatform } from "../utils/shortcuts";
import { positionTooltip, setTooltipTopLayer } from "../utils/tooltip";

interface TutorialState {
    revisionId: string;
    createMode: boolean;
    currentStep: number;
    revisionSteps?: Record<string, number>;
}

interface RevisionSettingsValues {
    trigger_path: string;
    auto_start: boolean;
}

interface RevisionSettingsDraft {
    revisionId: string;
    form: HTMLFormElement;
    saved: TutorialRevisionSettings;
    values: RevisionSettingsValues;
    timer?: number;
}

interface PanelPosition {
    left: number;
    top: number;
}

interface PanelPreferences {
    position: PanelPosition | null;
}

interface PanelDrag {
    pointerId: number;
    offsetX: number;
    offsetY: number;
    position: PanelPosition | null;
}

interface StepDraft {
    id: string;
    revisionId: string;
    editing: boolean;
    pagePath?: string;
    interaction?: StepInteraction;
    interactionChanged?: boolean;
}

interface StepHighlight {
    id: string;
    label: string;
    selector: string;
    allow_interaction: boolean;
}

type StepActionPhase = "before" | "after";

interface StepAction {
    kind: "click" | "fill" | "select" | "wait";
    highlight_id: string;
    selector: string;
    value: string;
}

interface StepInteraction {
    highlights: StepHighlight[];
    tooltip_highlight_id: string;
    advance_highlight_id: string;
    before: StepAction[];
    after: StepAction[];
}

interface ResolvedHighlight {
    highlight: StepHighlight;
    target: HTMLElement | null;
    menuTrigger: HTMLElement | null;
}

interface HighlightRect {
    left: number;
    right: number;
    top: number;
    bottom: number;
}

type SelectionIntent = { kind: "highlight"; id?: string } | { kind: "action"; phase: StepActionPhase; index: number };

interface TutorialVisit {
    stepId: string;
    pageUrl?: string;
}

interface PreviewCursor {
    revisionId: string;
    stepId: string | null;
    pageUrl?: string;
    advanceAt?: number;
    navigate?: boolean;
    learner?: boolean;
    beforeIndex?: number;
    afterIndex?: number;
    exit?: { focus: boolean; navigate: boolean };
    history?: TutorialVisit[];
}

interface PreviewRun extends TutorialPresentation {
    revisionId: string;
    index: number;
    cursor?: PreviewCursor;
    learner: boolean;
}

const stepModalId = "tutorial-step-modal";
const introductionIndex = -1;

const keyboardMoves = new Map<string, [number, number]>([
    ["ArrowLeft", [-16, 0]],
    ["ArrowRight", [16, 0]],
    ["ArrowUp", [0, -16]],
    ["ArrowDown", [0, 16]],
]);

/** Keep tutorial authoring and playback active across app navigation. */
export default class Tutorial extends BaseComponent {
    private readonly lifecycle = new AbortController();
    private storageKey = "";
    private state: TutorialState | null = null;
    private panelPreferences: PanelPreferences = { position: null };
    private drag: PanelDrag | null = null;
    private creatingRevision = false;
    private settingsRevisionId: string | null = null;
    private settingsRequest: AbortController | null = null;
    private settingsDraft: RevisionSettingsDraft | null = null;
    private readonly settingsWrites = new Map<string, Promise<void>>();
    private stepRequest: AbortController | null = null;
    private stepForm: HTMLFormElement | null = null;
    private stepDraft: StepDraft | null = null;
    private savingStep = false;
    private rowActionPending = false;
    private stepSortable: Sortable | null = null;
    private orderBeforeDrag: string[] = [];
    private reorderingSteps = false;
    private selection: AbortController | null = null;
    private selectionIntent: SelectionIntent | null = null;
    private previewTarget: HTMLElement | null = null;
    private preview: PreviewRun | null = null;
    private previewRequest: AbortController | null = null;
    private actionRequest: AbortController | null = null;
    private automatedTarget: HTMLElement | null = null;
    private actionFailure: StepActionPhase | null = null;
    private presentationTarget: HTMLElement | null = null;
    private presentationPrimary: HTMLElement | null = null;
    private previewLayoutFrame: number | null = null;
    private previewDrag: Omit<PanelDrag, "position"> | null = null;
    private previewPosition: PanelPosition | null = null;
    private highlightInteraction = new Map<HTMLElement, boolean>();
    private popoverHighlightTargets = new Set<HTMLElement>();
    private tooltipPopoverOwner: HTMLElement | null = null;
    private previewAdvanceTimer: number | undefined;
    private eligibleTutorials: CustomEligibleTutorialsOutputTutorialsItem[] | null = null;
    private learnerPage = "";
    private autoStartedOnPage = false;

    /** Restore authoring state and load the signed-in user's tutorial catalog. */
    public override initialize(): void {
        const panel = this.element;
        const userId = panel?.dataset.userId;
        if (!panel || !userId) return;

        this.storageKey = `bloomerp:tutorial:${userId}`;
        this.restoreState();

        const options = { signal: this.lifecycle.signal };
        this.stepForm = document.querySelector<HTMLFormElement>("#tutorial-step-form");
        const settings = panel.querySelector("[data-tutorial-settings]");
        settings?.addEventListener("input", this.onRevisionSettingsEdit, options);
        settings?.addEventListener("change", this.onRevisionSettingsEdit, options);
        settings?.addEventListener("submit", this.onRevisionSettingsEdit, options);
        window.addEventListener("pagehide", this.flushActiveRevisionSettings, options);
        this.stepForm?.addEventListener("submit", this.saveStep, options);
        this.stepForm?.querySelector("[name='advance_mode']")
            ?.addEventListener("change", this.updateStepAdvanceFields, options);
        this.stepForm?.addEventListener("click", this.onInteractionClick, options);
        this.stepForm?.addEventListener("input", this.onInteractionInput, options);
        document.addEventListener("bloomerp:tutorial-create", this.onCreate, options);
        document.addEventListener("bloomerp:tutorial-edit", this.onEditRevision, options);
        document.addEventListener("bloomerp:tutorial-published", this.onRevisionPublished, options);
        document.addEventListener("click", this.onLearnerStart, options);
        panel.querySelector("[data-tutorial-exit]")?.addEventListener("click", this.exitCreateMode, options);
        panel.querySelector("[data-tutorial-preview-start]")?.addEventListener("click", this.startPreview, options);
        panel.querySelector("[data-tutorial-add-step]")?.addEventListener("click", this.requestStep, options);
        const rows = panel.querySelector<HTMLTableSectionElement>("[data-tutorial-step-rows]");
        if (rows) {
            rows.addEventListener("click", this.onStepAction, options);
            rows.addEventListener("keydown", this.onStepReorderKey, options);
            this.stepSortable = Sortable.create(rows, {
                animation: 150,
                dataIdAttr: "data-step-id",
                draggable: "tr[data-step-id]",
                handle: "[data-tutorial-step-drag]",
                ghostClass: "opacity-50",
                onStart: this.onStepSortStart,
                onMove: this.canReorderSteps,
                onEnd: this.onStepSortEnd,
            });
        }
        panel.querySelector("[data-tutorial-cancel-selection]")?.addEventListener("click", this.cancelSelection, options);

        const handle = panel.querySelector<HTMLButtonElement>("[data-tutorial-drag]");
        handle?.addEventListener("pointerdown", this.startDrag, options);
        handle?.addEventListener("pointermove", this.moveDrag, options);
        handle?.addEventListener("lostpointercapture", this.endDrag, options);
        handle?.addEventListener("keydown", this.moveWithKeyboard, options);
        window.addEventListener("resize", this.repositionPanel, options);

        const presentation = document.getElementById("tutorial-presentation");
        const previewHandle = presentation?.querySelector<HTMLButtonElement>("[data-tutorial-preview-drag]");
        previewHandle?.addEventListener("pointerdown", this.startPreviewDrag, options);
        previewHandle?.addEventListener("pointermove", this.movePreviewDrag, options);
        previewHandle?.addEventListener("lostpointercapture", this.endPreviewDrag, options);
        previewHandle?.addEventListener("keydown", this.movePreviewWithKeyboard, options);
        presentation?.addEventListener("pointerdown", this.isolatePresentationEvent, options);
        presentation?.addEventListener("click", this.isolatePresentationEvent, options);
        presentation?.querySelector("[data-tutorial-preview-previous]")?.addEventListener("click", this.previousPreviewStep, options);
        presentation?.querySelector("[data-tutorial-preview-next]")?.addEventListener("click", this.nextPreviewStep, options);
        presentation?.querySelector("[data-tutorial-action-retry]")?.addEventListener("click", this.retryStepActions, options);
        for (const close of presentation?.querySelectorAll("[data-tutorial-preview-close]") ?? []) {
            close.addEventListener("click", this.onClosePreview, options);
        }
        for (const event of ["pointerdown", "click", "dblclick", "auxclick", "contextmenu", "keydown"]) {
            window.addEventListener(event, this.blockBackdropClick, { ...options, capture: true });
        }
        document.addEventListener("keydown", this.onPreviewKey, { ...options, capture: true });
        document.addEventListener("click", this.onPreviewTargetClick, { ...options, capture: true });
        document.addEventListener("dblclick", this.onPreviewTargetClick, { ...options, capture: true });
        document.addEventListener("input", this.onPreviewTargetInput, { ...options, capture: true });
        document.addEventListener("scroll", this.updatePreviewLayout, { ...options, capture: true });
        document.addEventListener("htmx:afterSettle", this.onPreviewUrlChange, options);
        document.addEventListener("htmx:historyRestore", this.onPreviewUrlChange, options);
        document.addEventListener("bloomerp:modal-opened", this.updatePreviewLayout, options);
        document.addEventListener("bloomerp:modal-closed", this.updatePreviewLayout, options);
        document.addEventListener("transitionend", this.onPreviewLayoutTransition, options);
        document.addEventListener("transitioncancel", this.onPreviewLayoutTransition, options);
        const sidebar = document.getElementById("sidebar");
        if (sidebar) {
            const visibility = new MutationObserver(this.updatePreviewLayout);
            visibility.observe(sidebar, { attributeFilter: ["inert"] });
            /** Stop observing sidebar visibility when the player is torn down. */
            function stopObservingSidebar(): void {
                visibility.disconnect();
            }
            this.lifecycle.signal.addEventListener("abort", stopObservingSidebar, { once: true });
        }
        document.addEventListener("toggle", this.onPreviewPopoverToggle, { ...options, capture: true });
        window.addEventListener("resize", this.updatePreviewLayout, options);
        window.addEventListener("hashchange", this.onPreviewUrlChange, options);
        window.addEventListener("popstate", this.onPreviewUrlChange, options);
        window.addEventListener("pageshow", this.onPreviewUrlChange, options);
        const navigation = (window as Window & { navigation?: EventTarget }).navigation;
        navigation?.addEventListener("currententrychange", this.onPreviewUrlChange, options);
        void this.loadEligibleTutorials();
    }

    /** Reconcile authoring mode after the browser restores a cached page. */
    public override onHistoryRestore(): void {
        if (this.storageKey) this.restoreState();
    }

    /** Release the action listener and any pending revision request. */
    public override destroy(): void {
        this.flushActiveRevisionSettings();
        this.settingsDraft = null;
        this.lifecycle.abort();
        this.stopTrackingPreviewLayout();
        window.clearTimeout(this.previewAdvanceTimer);
        this.settingsRequest?.abort();
        this.stepRequest?.abort();
        this.previewRequest?.abort();
        this.actionRequest?.abort();
        this.stepSortable?.destroy();
        this.stepSortable = null;
        this.stopSelection();
        this.drawHighlight(null, false);
        const card = document.getElementById("tutorial-presentation");
        if (card) this.resetPreviewPlacement(card);
        super.destroy();
    }

    /** Read the revision endpoint from the object action that emitted the event. */
    private onCreate = (event: Event): void => {
        const action = event.target;
        if (!(action instanceof HTMLButtonElement) || !action.dataset.tutorialRevisionUrl) return;
        void this.createRevision(action.dataset.tutorialRevisionUrl);
    };

    /** Save a draft on the server before entering authoring mode in the browser. */
    private async createRevision(url: string): Promise<void> {
        if (this.creatingRevision) return;
        this.creatingRevision = true;
        const signal = this.lifecycle.signal;

        try {
            const result = await getSdk().client.request<{ revision_id: string }>(url, {
                method: "POST",
                fetchOptions: { mode: "same-origin" },
                signal,
            });
            if (typeof result?.revision_id !== "string" || !result.revision_id) {
                throw new Error("Revision creation returned no revision ID.");
            }
            this.enterRevision(result.revision_id);
        } catch {
            if (!signal.aborted) {
                showMessage(t("The tutorial revision could not be created."), MessageType.ERROR);
            }
        } finally {
            this.creatingRevision = false;
        }
    }

    /** Reopen the draft selected in the revisions list. */
    private onEditRevision = (event: Event): void => {
        const action = event.target;
        if (!(action instanceof HTMLButtonElement) || this.creatingRevision
            || this.savingStep || this.rowActionPending || this.reorderingSteps) return;
        const revisionId = action.dataset.tutorialRevisionId;
        if (revisionId) this.enterRevision(revisionId);
    };

    /** Leave authoring mode when the currently open draft is published. */
    private onRevisionPublished = (event: Event): void => {
        if (event instanceof CustomEvent && this.state?.createMode
            && event.detail?.revisionId === this.state.revisionId) {
            this.exitCreateMode();
        }
    };

    /** Open the editor at the last saved step for this revision. */
    private enterRevision(revisionId: string): void {
        this.closePreview(false);
        if (this.isActiveRevision(revisionId)) return;
        this.clearStepDraft();

        const revisionSteps = { ...this.state?.revisionSteps };
        if (this.state) revisionSteps[this.state.revisionId] = this.state.currentStep;
        this.saveState({
            revisionId,
            createMode: true,
            currentStep: revisionSteps[revisionId] ?? 0,
            revisionSteps,
        });
    }

    /** Exit authoring mode without changing the saved draft. */
    private exitCreateMode = (): void => {
        this.closePreview(false);
        this.clearStepDraft();
        if (this.state) this.saveState({ ...this.state, createMode: false });
    };

    /** Load the trigger settings and route choices once per active draft. */
    private async loadRevisionSettings(): Promise<void> {
        const form = this.element?.querySelector<HTMLFormElement>("[data-tutorial-settings]");
        const fields = form?.querySelector("fieldset");
        const routes = form?.querySelector("datalist");
        const status = form?.querySelector<HTMLElement>("[data-tutorial-settings-status]");
        const revisionId = this.state?.createMode ? this.state.revisionId : null;
        if (!form || !fields || !routes || !status || revisionId === this.settingsRevisionId) return;

        this.flushActiveRevisionSettings();
        this.settingsDraft = null;
        this.settingsRequest?.abort();
        this.settingsRevisionId = revisionId;
        fields.disabled = true;
        status.textContent = "";
        status.hidden = true;
        if (!revisionId) return;

        const request = new AbortController();
        this.settingsRequest = request;
        try {
            await this.settingsWrites.get(revisionId);
            if (request.signal.aborted) return;
            const settings = await getSdk().custom.tutorialRevisionsTutorialRevisionSettingsGet({}, { pk: revisionId }, {
                signal: request.signal,
            });
            if (request.signal.aborted) return;
            routes.replaceChildren();
            for (const route of settings.routes) {
                const option = document.createElement("option");
                option.value = route.url;
                option.label = route.description ? `${route.name} - ${route.description}` : route.name;
                routes.append(option);
            }
            const draft: RevisionSettingsDraft = {
                revisionId, form, saved: settings,
                values: { trigger_path: settings.trigger_path ?? "", auto_start: settings.auto_start ?? false },
            };
            this.settingsDraft = draft;
            this.updateRevisionSettingsForm(draft);
            fields.disabled = false;
            this.repositionPanel();
        } catch {
            if (request.signal.aborted) return;
            this.settingsRevisionId = null;
            status.textContent = t("Could not load tutorial settings.");
            status.hidden = false;
        }
    }

    /** Display the latest edit and apply the permissions returned by the server. */
    private updateRevisionSettingsForm(draft: RevisionSettingsDraft): void {
        const { form, saved, values } = draft;
        const trigger = form.querySelector<HTMLInputElement>("[name='trigger_path']");
        const autoStart = form.querySelector<HTMLInputElement>("[name='auto_start']");
        if (trigger) {
            if (trigger.value !== values.trigger_path) trigger.value = values.trigger_path;
            trigger.disabled = !saved.can_edit_trigger;
        }
        if (autoStart) {
            autoStart.checked = values.auto_start;
            autoStart.disabled = !saved.can_edit_auto_start;
        }
    }

    /** Debounce route typing and save committed changes and checkbox clicks immediately. */
    private onRevisionSettingsEdit = (event: Event): void => {
        if (event.type === "submit") event.preventDefault();
        if (event instanceof InputEvent && event.isComposing) return;
        const draft = this.settingsDraft;
        if (!draft || event.currentTarget !== draft.form || draft.form.querySelector("fieldset")?.disabled) return;
        const { form, values } = draft;
        const trigger = form.querySelector<HTMLInputElement>("[name='trigger_path']");
        const autoStart = form.querySelector<HTMLInputElement>("[name='auto_start']");
        if (event.type === "input" && event.target !== trigger) return;
        const triggerPath = trigger && !trigger.disabled ? trigger.value : values.trigger_path;
        const startsAutomatically = autoStart && !autoStart.disabled ? autoStart.checked : values.auto_start;
        if (triggerPath !== values.trigger_path || startsAutomatically !== values.auto_start) {
            draft.values = { trigger_path: triggerPath, auto_start: startsAutomatically };
        }
        window.clearTimeout(draft.timer);
        if (event.type === "input") {
            /** Save the latest text after typing settles. */
            const save = (): void => this.flushRevisionSettings(draft);
            draft.timer = window.setTimeout(save, 400);
        } else {
            this.flushRevisionSettings(draft);
        }
    };

    /** Flush a pending edit when leaving the draft or page. */
    private flushActiveRevisionSettings = (): void => {
        if (this.settingsDraft) this.flushRevisionSettings(this.settingsDraft);
    };

    /** Let one writer per revision finish before starting another. */
    private flushRevisionSettings(draft: RevisionSettingsDraft): void {
        window.clearTimeout(draft.timer);
        draft.timer = undefined;
        if (this.settingsWrites.has(draft.revisionId)) return;
        const write = this.persistRevisionSettings(draft);
        this.settingsWrites.set(draft.revisionId, write);
        /** Release the completed writer before the next edit can be saved. */
        const removeWriter = (): void => {
            this.settingsWrites.delete(draft.revisionId);
        };
        void write.then(removeWriter, removeWriter);
    }

    /** Send only editable fields that differ from the last saved values. */
    private revisionSettingsPatch(draft: RevisionSettingsDraft): TutorialRevisionSettingsPatch {
        const { values, saved } = draft;
        const patch: TutorialRevisionSettingsPatch = {};
        if (saved.can_edit_trigger && values.trigger_path !== (saved.trigger_path ?? "")) patch.trigger_path = values.trigger_path;
        if (saved.can_edit_auto_start && values.auto_start !== (saved.auto_start ?? false)) patch.auto_start = values.auto_start;
        return patch;
    }

    /** Save only changed controls and merge responses without overwriting newer edits. */
    private async persistRevisionSettings(draft: RevisionSettingsDraft): Promise<void> {
        do {
            const values = draft.values;
            const patch = this.revisionSettingsPatch(draft);
            if (Object.keys(patch).length === 0) return;
            this.setRevisionSettingsStatus(draft, t("Saving settings…"));
            try {
                const settings = await getSdk().custom.tutorialRevisionsTutorialRevisionSettingsPatch(
                    patch, { pk: draft.revisionId }, { fetchOptions: { keepalive: true } },
                );
                const latest = draft.values;
                draft.saved = settings;
                draft.values = {
                    trigger_path: latest.trigger_path === values.trigger_path ? settings.trigger_path ?? "" : latest.trigger_path,
                    auto_start: latest.auto_start === values.auto_start ? settings.auto_start ?? false : latest.auto_start,
                };
                if (this.settingsDraft === draft) this.updateRevisionSettingsForm(draft);
                if (Object.keys(this.revisionSettingsPatch(draft)).length === 0) {
                    this.setRevisionSettingsStatus(draft, t("Settings saved."));
                }
            } catch (error) {
                this.setRevisionSettingsStatus(draft, error instanceof BloomerpHttpError
                    ? error.message : t("Could not save tutorial settings."));
                if (draft.values === values) return;
            }
        } while (draft.timer === undefined);
    }

    /** Report the active draft's save status without changing another draft's form. */
    private setRevisionSettingsStatus(draft: RevisionSettingsDraft, message: string): void {
        if (this.settingsDraft !== draft) return;
        const status = draft.form.querySelector<HTMLElement>("[data-tutorial-settings-status]");
        if (!status) return;
        status.textContent = message;
        status.hidden = !message;
        this.repositionPanel();
    }

    /** Open an empty form for a new step on the current page. */
    private requestStep = (event: Event): void => {
        if (!this.state?.createMode || this.savingStep || this.rowActionPending || this.reorderingSteps) return;
        if (!(event.currentTarget instanceof HTMLElement)) return;

        this.openStepForm(event.currentTarget, {
            id: crypto.randomUUID(),
            revisionId: this.state.revisionId,
            editing: false,
            pagePath: window.location.pathname,
        });
    };

    /** Use the same dialog for a new step or the saved values of an existing step. */
    private openStepForm(opener: HTMLElement, draft: StepDraft, values?: TutorialStepEditorValues): void {
        const form = this.stepForm;
        if (!form) return;

        const modal = getModal(stepModalId);
        if (!modal) return;
        this.stepDraft = draft;
        draft.interaction = values?.interaction === null ? undefined
            : (values?.interaction as StepInteraction | undefined) ?? this.emptyStepInteraction();
        draft.pagePath = values?.page_path ?? draft.pagePath;
        form.reset();
        const title = form.querySelector<HTMLInputElement>("[name='name']");
        const page = form.querySelector<HTMLInputElement>("[name='page_path']");
        const size = form.querySelector<HTMLSelectElement>("[name='size']");
        const backdrop = form.querySelector<HTMLInputElement>("[name='include_backdrop']");
        const showAsTooltip = form.querySelector<HTMLInputElement>("[name='show_as_tooltip']");
        const advanceMode = form.querySelector<HTMLSelectElement>("[name='advance_mode']");
        const advanceDelay = form.querySelector<HTMLInputElement>("[name='advance_delay_ms']");
        const advanceUrl = form.querySelector<HTMLInputElement>("[name='advance_url_pattern']");
        const hideNext = form.querySelector<HTMLInputElement>("[name='hide_next_button']");
        if (title) title.value = values?.name ?? "";
        if (page) {
            page.disabled = values?.page_path === null;
            page.value = draft.pagePath ?? "";
        }
        if (size) {
            size.disabled = values?.size === null;
            size.value = size.disabled ? "" : values?.size ?? "small";
        }
        if (backdrop) backdrop.checked = values?.include_backdrop ?? true;
        if (showAsTooltip) {
            showAsTooltip.readOnly = values?.show_as_tooltip === null;
            showAsTooltip.checked = values?.show_as_tooltip ?? false;
        }
        if (advanceMode) {
            advanceMode.disabled = values?.advance_mode === null;
            advanceMode.value = advanceMode.disabled ? "" : values?.advance_mode ?? "manual";
        }
        if (advanceDelay) {
            advanceDelay.disabled = values?.advance_delay_ms === null;
            advanceDelay.value = advanceDelay.disabled ? "" : String(values?.advance_delay_ms ?? 0);
        }
        if (advanceUrl) {
            advanceUrl.readOnly = values?.advance_url_pattern === null;
            advanceUrl.value = values?.advance_url_pattern ?? "";
        }
        if (hideNext) {
            hideNext.readOnly = values?.hide_next_button === null;
            hideNext.checked = values?.hide_next_button ?? false;
        }
        this.updateStepAdvanceFields();
        this.descriptionEditor()?.setValue(values?.text ?? "");
        form.querySelector("[contenteditable]")?.setAttribute("aria-labelledby", "tutorial-step-description-label");
        this.setStepError("");
        this.renderStepInteraction();
        modal.setTitle(draft.editing ? t("Edit step") : t("Add step"));
        modal.setOpener(opener);
        modal.open();
        title?.focus();
    }

    /** Show only the options that apply to the selected advance condition. */
    private updateStepAdvanceFields = (): void => {
        const mode = this.stepForm?.querySelector<HTMLSelectElement>("[name='advance_mode']")?.value;
        const delay = this.stepForm?.querySelector<HTMLInputElement>("[name='advance_delay_ms']");
        if (delay) {
            delay.min = mode === "delay" ? "1" : "0";
            delay.required = mode === "delay";
            const marker = this.stepForm?.querySelector<HTMLElement>("[data-tutorial-delay-required]");
            if (marker) marker.hidden = !delay.required || delay.disabled;
        }
        const urlField = this.stepForm?.querySelector<HTMLElement>("[data-tutorial-advance-url-field]");
        const urlInput = urlField?.querySelector<HTMLInputElement>("input");
        if (urlField && urlInput) {
            urlField.hidden = mode !== "navigation";
            urlInput.disabled = urlField.hidden || urlInput.readOnly;
        }
        const hideNextField = this.stepForm?.querySelector<HTMLElement>("[data-tutorial-hide-next-field]");
        const hideNext = hideNextField?.querySelector<HTMLInputElement>("input");
        if (hideNextField && hideNext) {
            hideNextField.hidden = !mode || mode === "manual";
            hideNext.disabled = hideNextField.hidden || hideNext.readOnly;
        }
        const field = this.stepForm?.querySelector<HTMLElement>("[data-tutorial-advance-highlight-field]");
        const select = field?.querySelector<HTMLSelectElement>("select");
        const interaction = this.stepDraft?.interaction;
        if (field && select) {
            const enabled = !!interaction && (mode === "click" || mode === "dblclick" || mode === "input");
            field.hidden = !enabled;
            select.disabled = !enabled;
            select.required = enabled;
            const highlight = interaction?.highlights.find(item => item.id === interaction.advance_highlight_id);
            const backdrop = this.stepForm?.querySelector<HTMLInputElement>("[name='include_backdrop']");
            const message = enabled && backdrop?.checked && highlight && !highlight.allow_interaction
                ? t("Allow interaction on the advance highlight while the backdrop is on.") : "";
            select.setCustomValidity(message);
            const error = field.querySelector<HTMLElement>("[role='status']");
            if (error) {
                error.textContent = message;
                error.hidden = !message;
            }
        }
    };

    /** Get the existing rich-text widget that owns the description field. */
    private descriptionEditor(): BloomerpTextEditor | null {
        const host = this.stepForm?.querySelector<HTMLElement>('[bloomerp-component="bloomerp-text-editor"]');
        return host ? getComponent(host) as BloomerpTextEditor | null : null;
    }

    /** Save the form through the SDK and refresh the sequence table. */
    private saveStep = async (event: SubmitEvent): Promise<void> => {
        event.preventDefault();
        const { stepForm: form, stepDraft: draft, state } = this;
        if (!form || !draft || !state?.createMode || state.revisionId !== draft.revisionId || this.savingStep) return;

        const fields = new FormData(form);
        this.savingStep = true;
        this.setStepBusy(true);
        this.setStepError("");
        try {
            const sdk = getSdk().custom;
            const options = { signal: this.lifecycle.signal };
            const size = fields.get("size");
            const page = fields.get("page_path")?.toString().trim();
            const mode = fields.get("advance_mode");
            const delay = fields.get("advance_delay_ms");
            const hideNext = form.querySelector<HTMLInputElement>("[name='hide_next_button']");
            const showAsTooltip = form.querySelector<HTMLInputElement>("[name='show_as_tooltip']");
            const body: TutorialStepUpdate = {
                name: String(fields.get("name") ?? ""),
                text: this.descriptionEditor()?.getValue() ?? String(fields.get("tutorial_step_description") ?? ""),
                size: size === "small" || size === "medium" || size === "large" ? size : undefined,
                include_backdrop: fields.has("include_backdrop"),
                show_as_tooltip: showAsTooltip && !showAsTooltip.readOnly
                    && (!showAsTooltip.disabled || draft.interactionChanged) ? fields.has("show_as_tooltip") : undefined,
                advance_mode: mode === "manual" || mode === "click" || mode === "dblclick" || mode === "input" || mode === "navigation" || mode === "delay"
                    ? mode : undefined,
                advance_delay_ms: delay === null ? undefined : Number(delay),
                advance_url_pattern: fields.get("advance_url_pattern")?.toString().trim(),
                hide_next_button: hideNext && !hideNext.readOnly && (!hideNext.disabled || mode === "manual")
                    ? fields.has("hide_next_button") : undefined,
                interaction: !draft.editing || draft.interactionChanged ? draft.interaction : undefined,
            };
            const step = draft.editing
                ? await sdk.tutorialStepsTutorialStepDetailPut({
                    ...body,
                    page_path: page === draft.pagePath ? undefined : page,
                }, { pk: draft.id }, options)
                : await sdk.tutorialRevisionsCreateTutorialStep({
                    ...body,
                    size: body.size === "small" ? undefined : body.size,
                    show_as_tooltip: body.show_as_tooltip || undefined,
                    advance_mode: body.advance_mode === "manual" ? undefined : body.advance_mode,
                    advance_delay_ms: body.advance_delay_ms || undefined,
                    advance_url_pattern: body.advance_url_pattern || undefined,
                    hide_next_button: body.hide_next_button || undefined,
                    step_id: draft.id,
                    page_path: page ?? window.location.pathname,
                }, { pk: draft.revisionId }, options);
            if (this.stepDraft !== draft || this.lifecycle.signal.aborted) return;
            this.clearStepDraft();
            this.saveState({ ...state, currentStep: step.sequence });
        } catch (error) {
            if (this.stepDraft === draft && !this.lifecycle.signal.aborted) {
                this.setStepError(error instanceof BloomerpHttpError && typeof error.body === "object"
                    ? error.message : t("The step could not be saved."));
            }
        } finally {
            this.savingStep = false;
            this.setStepBusy(false);
        }
    };

    /** Prevent repeated submits or starting a selection while a save is pending. */
    private setStepBusy(busy: boolean): void {
        const form = this.stepForm;
        if (!form) return;
        form.setAttribute("aria-busy", String(busy));
        const buttons = document.getElementById(stepModalId)?.querySelectorAll<HTMLButtonElement>(
            "[form='tutorial-step-form'], [data-tutorial-select-target]",
        );
        for (const button of buttons ?? []) {
            button.disabled = busy;
        }
    }

    /** Show a server or validation error as plain text in the dialog. */
    private setStepError(message: string): void {
        const error = this.stepForm?.querySelector<HTMLElement>("[data-tutorial-step-error]");
        if (error) {
            error.textContent = message;
            error.hidden = !message;
        }
    }

    /** Close the form and remove any selection UI when its draft is discarded. */
    private clearStepDraft(): void {
        if (!this.stepDraft) return;
        this.stepDraft = null;
        this.stopSelection();
        getModal(stepModalId)?.close();
    }

    /** Close the modal before collecting a target without resetting its fields. */
    private beginSelection(intent: SelectionIntent): void {
        if (!this.stepDraft || this.savingStep || this.selection) return;
        const modal = getModal(stepModalId);
        if (!modal) return;

        this.selectionIntent = intent;
        this.selection = new AbortController();
        modal.element.addEventListener("bloomerp:modal-closed", this.startSelection, {
            once: true,
            signal: this.selection.signal,
        });
        modal.close();
    }

    /** Activate page picking once the modal's backdrop has been removed. */
    private startSelection = (): void => {
        if (!this.selection) return;

        const options = { capture: true, signal: this.selection.signal };
        document.addEventListener("pointermove", this.previewSelection, options);
        document.addEventListener("pointerdown", this.blockSelectionPointerDown, options);
        document.addEventListener("click", this.selectTarget, options);
        document.addEventListener("keydown", this.onSelectionKey, options);
        document.addEventListener("scroll", this.renderTargetPreview, options);
        window.addEventListener("resize", this.renderTargetPreview, options);
        this.renderMode();
        this.element?.querySelector<HTMLElement>("[data-tutorial-cancel-selection]")?.focus();
    };

    /** Return from picking while keeping the previous field values and target. */
    private cancelSelection = (): void => {
        if (!this.selection) return;
        this.stopSelection();
        if (!this.stepDraft) return;
        this.renderStepInteraction();
        getModal(stepModalId)?.open();
    };

    /** Clear the overlay and release all document listeners for picking. */
    private stopSelection(): void {
        if (!this.selection) return;
        this.selection.abort();
        this.selection = null;
        this.selectionIntent = null;
        this.previewTarget = null;
        this.renderTargetPreview();
        this.renderMode();
    }

    /** Cancel target selection with Escape and keep the form open for editing. */
    private onSelectionKey = (event: KeyboardEvent): void => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        event.stopImmediatePropagation();
        this.cancelSelection();
    };

    /** Identify a primary click using only the platform's selection modifier. */
    private isSelectionClick(event: MouseEvent): boolean {
        const modified = isMacPlatform() ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey;
        return event.button === 0 && modified && !event.altKey && !event.shiftKey;
    }

    /** Suppress pointer-down behavior only for a target-selection click. */
    private blockSelectionPointerDown = (event: PointerEvent): void => {
        if (!this.isSelectionClick(event) || !(event.target instanceof Node) || this.element?.contains(event.target)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
    };

    /** Preview the selectable control or container under the pointer. */
    private previewSelection = (event: PointerEvent): void => {
        this.previewTarget = this.selectableTarget(event.target);
        this.renderTargetPreview();
    };

    /** Capture a modified click and leave ordinary page interactions alone. */
    private selectTarget = (event: MouseEvent): void => {
        if (!this.isSelectionClick(event) || !(event.target instanceof Node) || this.element?.contains(event.target)) return;
        event.preventDefault();
        event.stopImmediatePropagation();

        const target = this.selectableTarget(event.target);
        const draft = this.stepDraft;
        const intent = this.selectionIntent;
        if (!target || !draft?.interaction || !intent) return;
        const interaction = draft.interaction;
        const selector = this.selectorForTarget(target);
        if (intent.kind === "action") {
            const action = interaction[intent.phase][intent.index];
            if (!action) return;
            action.selector = selector;
            action.highlight_id = "";
        } else {
            const highlight = interaction.highlights.find(candidate => candidate.id === intent.id);
            if (highlight) {
                highlight.selector = selector;
            } else {
                const id = crypto.randomUUID();
                const label = (target.getAttribute("aria-label") || target.textContent || "")
                    .replace(/\s+/g, " ").trim().slice(0, 120) || t("Highlight") + " " + (interaction.highlights.length + 1);
                interaction.highlights.push({ id, label, selector, allow_interaction: false });
                interaction.advance_highlight_id ||= id;
                interaction.tooltip_highlight_id ||= id;
            }
        }
        draft.interactionChanged = true;
        this.cancelSelection();
    };

    /** Prefer the intended input, link, button, or menu item over its containing block. */
    private selectableTarget(target: EventTarget | null): HTMLElement | null {
        if (!(target instanceof Element) || this.element?.contains(target)) return null;
        const intent = this.selectionIntent;
        const mode = intent?.kind === "action" ? this.stepDraft?.interaction?.[intent.phase][intent.index]?.kind : undefined;
        const selector = mode === "fill"
            ? "input, textarea, [contenteditable]"
            : mode === "select" ? "select"
                : "[data-tutorial-anchor], button, a[href], input, select, textarea, [role='button'], [role='menuitem'], [role='option']";
        const element = target.closest<HTMLElement>(selector) ?? target.closest<HTMLElement>("div");
        if (!element) return null;
        const bounds = element.getBoundingClientRect();
        return bounds.width && bounds.height ? element : null;
    }

    /** Prefer durable anchors and IDs, using a scoped DOM path for unmarked elements. */
    private selectorForTarget(target: HTMLElement): string {
        if (target.dataset.tutorialAnchor) {
            const selector = `[data-tutorial-anchor="${CSS.escape(target.dataset.tutorialAnchor)}"]`;
            if (document.querySelectorAll(selector).length === 1) return selector;
        }

        const parts: string[] = [];
        let element: HTMLElement | null = target;
        while (element && element !== document.body) {
            if (element.id) {
                const selector = `#${CSS.escape(element.id)}`;
                if (document.querySelectorAll(selector).length === 1) {
                    return [selector, ...parts].join(" > ");
                }
            }
            let position = 1;
            for (let sibling = element.previousElementSibling; sibling; sibling = sibling.previousElementSibling) {
                if (sibling.localName === element.localName) position++;
            }
            parts.unshift(`${element.localName}:nth-of-type(${position})`);
            element = element.parentElement;
        }
        return ["body", ...parts].join(" > ");
    }

    /** Keep the non-interactive highlight aligned with its target as the page scrolls. */
    private renderTargetPreview = (): void => {
        const backdrop = this.stepForm?.querySelector<HTMLInputElement>("[name='include_backdrop']");
        this.drawHighlight(this.previewTarget, backdrop?.checked === true);
    };

    /** Draw a page highlight for element picking or presentation. */
    private drawHighlight(target: HTMLElement | null, backdrop: boolean): void {
        this.drawHighlights(target ? [target] : [], backdrop && target !== null);
    }

    /** Measure each live target, draw its ring, and cut its area from the backdrop. */
    private drawHighlights(targets: HTMLElement[], backdrop: boolean): Map<HTMLElement, DOMRect> {
        const targetBounds = new Map<HTMLElement, DOMRect>();
        for (const target of new Set(targets)) {
            if (target.isConnected) targetBounds.set(target, target.getBoundingClientRect());
        }

        const preview = document.getElementById("tutorial-target-preview");
        const template = preview?.querySelector<HTMLTemplateElement>("template");
        const popovers = new Set<HTMLElement>();
        const rects: HighlightRect[] = [];
        let ringIndex = 1;
        for (const [target, bounds] of targetBounds) {
            if (typeof target.showPopover === "function" && target.closest(":popover-open")) {
                popovers.add(target);
                if (!this.popoverHighlightTargets.has(target)) target.setAttribute("data-tutorial-popover-highlight", "");
            } else if (preview && template) {
                let ring = preview.children[ringIndex] as HTMLElement | undefined;
                if (!ring) {
                    ring = template.content.firstElementChild?.cloneNode(true) as HTMLElement;
                    preview.append(ring);
                }
                ring.dataset.ringActive = "";
                ringIndex++;
                Object.assign(ring.style, { left: `${bounds.left}px`, top: `${bounds.top}px`,
                    width: `${bounds.width}px`, height: `${bounds.height}px` });
            }
            rects.push({
                left: Math.max(0, bounds.left), right: Math.min(window.innerWidth, bounds.right),
                top: Math.max(0, bounds.top), bottom: Math.min(window.innerHeight, bounds.bottom),
            });
        }
        for (const previous of this.popoverHighlightTargets) {
            if (!popovers.has(previous)) previous.removeAttribute("data-tutorial-popover-highlight");
        }
        this.popoverHighlightTargets = popovers;
        if (preview) {
            for (const ring of Array.from(preview.children).slice(1)) {
                if (ring.hasAttribute("data-ring-active")) ring.removeAttribute("data-ring-active");
                else ring.remove();
            }
            preview.hidden = preview.children.length === 1;
        }
        const overlay = document.getElementById("tutorial-presentation-backdrop");
        if (overlay) {
            overlay.hidden = !backdrop;
            overlay.style.clipPath = backdrop && rects.length ? this.backdropCutout(rects) : "";
        }
        return targetBounds;
    }

    /** Turn overlapping highlight rectangles into nonoverlapping cutout bands. */
    private backdropCutout(rects: HighlightRect[]): string {
        const visible = rects.filter(rect => rect.left < rect.right && rect.top < rect.bottom);
        const edges = Array.from(new Set(visible.flatMap(rect => [rect.left, rect.right]))).sort((a, b) => a - b);
        let path = `M 0 0 H ${window.innerWidth} V ${window.innerHeight} H 0 Z`;
        for (let index = 1; index < edges.length; index++) {
            const left = edges[index - 1];
            const right = edges[index];
            const band = visible.filter(rect => rect.left <= left && rect.right >= right).sort((a, b) => a.top - b.top);
            let end = 0;
            for (const rect of band) {
                const top = Math.max(end, rect.top);
                if (rect.bottom <= top) continue;
                end = rect.bottom;
                path += ` M ${left} ${top} H ${right} V ${end} H ${left} Z`;
            }
        }
        return `path(evenodd, "${path}")`;
    }

    /** Initialize an unconfigured step with empty highlight and action lists. */
    private emptyStepInteraction(): StepInteraction {
        return { highlights: [], tooltip_highlight_id: "", advance_highlight_id: "", before: [], after: [] };
    }

    /** Render the editable highlight and action rows from the current draft. */
    private renderStepInteraction(): void {
        const form = this.stepForm;
        const interaction = this.stepDraft?.interaction;
        if (!form) return;
        const highlights = form.querySelector<HTMLElement>("[data-tutorial-highlights]");
        const highlightTemplate = form.querySelector<HTMLTemplateElement>("[data-tutorial-highlight-template]");
        const add = form.querySelector<HTMLButtonElement>("[data-tutorial-interaction='add-highlight']");
        if (add) add.disabled = !interaction;
        highlights?.replaceChildren();
        if (highlights && highlightTemplate && interaction) {
            for (const highlight of interaction.highlights) {
                const row = highlightTemplate.content.firstElementChild?.cloneNode(true) as HTMLElement;
                row.dataset.highlightId = highlight.id;
                const label = row.querySelector<HTMLInputElement>("[data-tutorial-highlight-label]");
                const checkbox = row.querySelector<HTMLInputElement>("[data-tutorial-highlight-interactive]");
                if (label) label.value = highlight.label;
                if (checkbox) checkbox.checked = highlight.allow_interaction;
                highlights.append(row);
            }
        }
        const phases: StepActionPhase[] = ["before", "after"];
        const actionTemplate = form.querySelector<HTMLTemplateElement>("[data-tutorial-action-template]");
        for (const phase of phases) {
            const group = form.querySelector<HTMLElement>(`[data-tutorial-action-phase="${phase}"]`);
            const list = group?.querySelector<HTMLElement>("[data-tutorial-action-rows]");
            const addAction = group?.querySelector<HTMLButtonElement>("[data-tutorial-interaction='add-action']");
            if (addAction) addAction.disabled = !interaction;
            list?.replaceChildren();
            if (!interaction || !list || !actionTemplate) continue;
            interaction[phase].forEach((action: StepAction, index: number): void => {
                const row = actionTemplate.content.firstElementChild?.cloneNode(true) as HTMLElement;
                row.dataset.actionIndex = String(index);
                const kind = row.querySelector<HTMLSelectElement>("[data-tutorial-action-kind]");
                const value = row.querySelector<HTMLInputElement>("[data-tutorial-action-value]");
                const up = row.querySelector<HTMLButtonElement>("[data-tutorial-interaction='move-action-up']");
                if (kind) kind.value = action.kind;
                if (value) {
                    value.value = action.value;
                    value.hidden = action.kind !== "fill" && action.kind !== "select";
                }
                if (up) up.disabled = index === 0;
                list.append(row);
            });
        }
        this.refreshHighlightChoices();
        this.updateStepAdvanceFields();
        this.updateTooltipOptions();
    }

    /** Toggle tooltip controls based on the saved highlight list and presentation choice. */
    private updateTooltipOptions(): void {
        const hasSelection = Boolean(this.stepDraft?.interaction?.highlights.length);
        const field = this.stepForm?.querySelector<HTMLElement>("[data-tutorial-tooltip-field]");
        const input = field?.querySelector<HTMLInputElement>("input");
        const anchor = field?.querySelector<HTMLElement>("[data-tutorial-tooltip-anchor-field]");
        const anchorChoice = anchor?.querySelector<HTMLSelectElement>("select");
        if (field && input) {
            field.hidden = !hasSelection;
            input.disabled = !hasSelection || input.readOnly;
            if (anchor) anchor.hidden = input.disabled || !input.checked;
            if (anchorChoice) {
                anchorChoice.disabled = input.disabled || !input.checked;
                anchorChoice.required = !anchorChoice.disabled;
            }
        }
    }

    /** Look up the before or after list containing an action control. */
    private actionPhase(element: Element): StepActionPhase | undefined {
        const phase = element.closest<HTMLElement>("[data-tutorial-action-phase]")?.dataset.tutorialActionPhase;
        return phase === "before" || phase === "after" ? phase : undefined;
    }

    /** Fill one target picker with the current highlight names. */
    private setHighlightOptions(select: HTMLSelectElement, highlights: StepHighlight[], selected: string, emptyLabel: string): void {
        select.replaceChildren(new Option(emptyLabel, ""));
        for (const highlight of highlights) select.add(new Option(highlight.label, highlight.id));
        select.value = selected;
    }

    /** Refresh every reference picker without replacing a highlight name field being edited. */
    private refreshHighlightChoices(): void {
        const interaction = this.stepDraft?.interaction;
        if (!interaction || !this.stepForm) return;
        const choices: ("tooltip_highlight_id" | "advance_highlight_id")[] = ["tooltip_highlight_id", "advance_highlight_id"];
        for (const key of choices) {
            const select = this.stepForm.querySelector<HTMLSelectElement>(`[data-tutorial-highlight-choice="${key}"]`);
            if (select) this.setHighlightOptions(select, interaction.highlights, interaction[key], t("Choose highlight"));
        }
        for (const select of this.stepForm.querySelectorAll<HTMLSelectElement>("[data-tutorial-action-target]")) {
            const phase = this.actionPhase(select);
            const index = Number(select.closest<HTMLElement>("[data-tutorial-action-row]")?.dataset.actionIndex);
            const action = phase ? interaction[phase][index] : undefined;
            if (action) this.setHighlightOptions(select, interaction.highlights, action.highlight_id,
                action.selector ? t("Picked element") : t("Choose target"));
        }
    }

    /** Keep the current highlight and action settings in sync with their controls. */
    private onInteractionInput = (event: Event): void => {
        const field = event.target;
        const draft = this.stepDraft;
        if (!(field instanceof HTMLInputElement || field instanceof HTMLSelectElement) || !draft?.interaction) return;
        const interaction = draft.interaction;
        const selection = interaction.highlights.find(item =>
            item.id === field.closest<HTMLElement>("[data-tutorial-highlight-row]")?.dataset.highlightId);
        const choice = field.dataset.tutorialHighlightChoice;
        const phase = this.actionPhase(field);
        const index = Number(field.closest<HTMLElement>("[data-tutorial-action-row]")?.dataset.actionIndex);
        const action = phase ? interaction[phase][index] : undefined;
        if (selection && field instanceof HTMLInputElement) {
            if (field.hasAttribute("data-tutorial-highlight-label")) {
                selection.label = field.value;
                this.refreshHighlightChoices();
            } else {
                selection.allow_interaction = field.checked;
            }
        } else if (choice === "advance_highlight_id" || choice === "tooltip_highlight_id") {
            interaction[choice] = field.value;
        } else if (action) {
            if (field.hasAttribute("data-tutorial-action-target")) {
                action.highlight_id = field.value;
                action.selector = "";
            } else if (field.hasAttribute("data-tutorial-action-kind")) {
                action.kind = field.value as StepAction["kind"];
                const value = field.closest("[data-tutorial-action-row]")?.querySelector<HTMLInputElement>("[data-tutorial-action-value]");
                if (value) value.hidden = action.kind !== "fill" && action.kind !== "select";
            } else {
                action.value = field.value;
            }
        } else {
            if (field.name === "show_as_tooltip") this.updateTooltipOptions();
            if (field.name === "include_backdrop") this.updateStepAdvanceFields();
            return;
        }
        draft.interactionChanged = true;
        this.updateStepAdvanceFields();
    };

    /** Add, pick, reorder, or remove targets in the current step configuration. */
    private onInteractionClick = (event: Event): void => {
        const draft = this.stepDraft;
        if (!(event.target instanceof Element) || !draft?.interaction || this.savingStep) return;
        const button = event.target.closest<HTMLButtonElement>("[data-tutorial-interaction]");
        if (!button || button.disabled) return;
        const interaction = draft.interaction;
        const id = button.closest<HTMLElement>("[data-tutorial-highlight-row]")?.dataset.highlightId;
        const phase = this.actionPhase(button);
        const index = Number(button.closest<HTMLElement>("[data-tutorial-action-row]")?.dataset.actionIndex);
        switch (button.dataset.tutorialInteraction) {
            case "add-highlight":
            case "pick-highlight":
                this.beginSelection({ kind: "highlight", id });
                return;
            case "pick-action":
                if (phase) this.beginSelection({ kind: "action", phase, index });
                return;
            case "remove-highlight":
                interaction.highlights = interaction.highlights.filter(highlight => highlight.id !== id);
                if (interaction.advance_highlight_id === id) interaction.advance_highlight_id = "";
                if (interaction.tooltip_highlight_id === id) interaction.tooltip_highlight_id = "";
                for (const action of [...interaction.before, ...interaction.after]) {
                    if (action.highlight_id === id) action.highlight_id = "";
                }
                if (!interaction.highlights.length) {
                    const tooltip = this.stepForm?.querySelector<HTMLInputElement>("[name='show_as_tooltip']");
                    if (tooltip && !tooltip.readOnly) tooltip.checked = false;
                }
                break;
            case "add-action":
                if (phase) interaction[phase].push({ kind: "click", highlight_id: "", selector: "", value: "" });
                break;
            case "remove-action":
                if (phase) interaction[phase].splice(index, 1);
                break;
            case "move-action-up":
                if (phase && index > 0) {
                    const list = interaction[phase];
                    [list[index - 1], list[index]] = [list[index], list[index - 1]];
                }
                break;
            default:
                return;
        }
        draft.interactionChanged = true;
        this.renderStepInteraction();
    };

    /** Load the signed-in user's catalog once for this page document. */
    private async loadEligibleTutorials(): Promise<void> {
        const signal = this.lifecycle.signal;
        try {
            const { tutorials } = await getSdk().custom.eligibleTutorials({}, { signal });
            if (signal.aborted) return;
            this.eligibleTutorials = tutorials;
            const cursor = this.readPreviewCursor();
            if (cursor?.learner) this.resumeLearnerPreview(cursor);
            this.updateLearnerOffers();
        } catch {
            // A failed catalog request should leave the page usable.
        }
    }

    /** Read the route marker associated with the actual browser path after a swap. */
    private currentTutorialRoute(): string {
        const marker = document.querySelector<HTMLElement>("#main-content #htmx-addendum")
            ?? document.getElementById("main");
        const path = this.getPreviewDestination(marker?.dataset.tutorialPath ?? null);
        return path?.pathname === window.location.pathname ? marker?.dataset.tutorialRoute ?? "" : "";
    }

    /** Match a revision trigger against the rendered route or the current URL path. */
    private matchesTutorialTrigger(trigger: string, route: string): boolean {
        if (!trigger) return true;
        if (!route) return false;
        if (!trigger.startsWith("/")) return trigger === route;
        const { pathname } = window.location;
        if (!trigger.includes("*")) return this.matchesPathPattern(trigger, pathname);

        // A trailing slash is optional in a tutorial trigger pattern.
        const path = pathname === "/" ? pathname : pathname.replace(/\/$/, "");
        return this.matchesPathPattern(trigger.replace(/\/$/, ""), path);
    }

    /** Offer matching tutorials locally and start at most one automatically per page visit. */
    private updateLearnerOffers(allowAutomatic: boolean = true): void {
        const launcher = document.getElementById("tutorial-launcher");
        const { pathname } = window.location;
        if (this.learnerPage !== pathname) {
            this.learnerPage = pathname;
            this.autoStartedOnPage = false;
        }
        const busy = this.state?.createMode === true || this.preview !== null;
        if (launcher) {
            if (busy && launcher.querySelector("[aria-expanded='true']")) {
                launcher.dispatchEvent(new Event("dropdown-close", { bubbles: true }));
            }
            launcher.hidden = busy;
        }
        if (busy) return;

        const route = this.currentTutorialRoute();
        const matches = (this.eligibleTutorials ?? []).filter(
            (tutorial: CustomEligibleTutorialsOutputTutorialsItem): boolean =>
                this.matchesTutorialTrigger(tutorial.trigger_route, route),
        );
        if (launcher) this.renderLearnerOffers(launcher, matches);
        if (!allowAutomatic || this.previewRequest || this.autoStartedOnPage || !route) return;
        const automatic = matches.find(
            (tutorial: CustomEligibleTutorialsOutputTutorialsItem): boolean =>
                tutorial.auto_start && !!tutorial.trigger_route,
        );
        if (automatic) {
            this.autoStartedOnPage = true;
            void this.startLearnerPlayback(automatic.revision_id, true);
        }
    }

    /** Update the help icon and populate the menu with tutorials for this page. */
    private renderLearnerOffers(launcher: HTMLElement, matches: CustomEligibleTutorialsOutputTutorialsItem[]): void {
        const list = launcher.querySelector<HTMLElement>("[data-tutorial-launcher-items]");
        const template = launcher.querySelector<HTMLTemplateElement>("[data-tutorial-launcher-item]");
        const empty = launcher.querySelector<HTMLElement>("[data-tutorial-launcher-empty]");
        if (!list || !template || !empty) return;
        const hasTutorials = matches.length > 0;
        const trigger = launcher.querySelector("#tutorial-launcher-trigger");
        trigger?.classList.toggle("text-primary-800", hasTutorials);
        trigger?.classList.toggle("text-secondary", !hasTutorials);
        empty.hidden = hasTutorials;

        const revisionIds = matches.map(
            (tutorial: CustomEligibleTutorialsOutputTutorialsItem): string => tutorial.revision_id,
        ).join(",");
        if (list.dataset.revisions === revisionIds) return;
        list.dataset.revisions = revisionIds;
        list.replaceChildren();
        for (const tutorial of matches) {
            const item = template.content.cloneNode(true) as DocumentFragment;
            const button = item.querySelector("button");
            if (!button) continue;
            button.dataset.tutorialStart = tutorial.revision_id;
            button.textContent = tutorial.name;
            list.append(item);
        }
    }

    /** Start a published tutorial from its object action or the current page's help menu. */
    private onLearnerStart = (event: MouseEvent): void => {
        const button = event.target instanceof Element
            ? event.target.closest<HTMLElement>(
                "[data-tutorial-start-revision], #tutorial-launcher [data-tutorial-start]",
            )
            : null;
        if (!button) return;
        const revisionId = button.dataset.tutorialStartRevision ?? button.dataset.tutorialStart;
        if (!revisionId) return;
        if (button.dataset.tutorialStart) {
            const tutorial = this.eligibleTutorials?.find(
                (item: CustomEligibleTutorialsOutputTutorialsItem): boolean => item.revision_id === revisionId,
            );
            if (!tutorial || !this.matchesTutorialTrigger(tutorial.trigger_route, this.currentTutorialRoute())) return;
            button.dispatchEvent(new Event("dropdown-close", { bubbles: true }));
        }
        void this.startLearnerPlayback(revisionId, false);
    };

    /** Load the published presentation when offered, opened, or resumed. */
    private async startLearnerPlayback(
        revisionId: string,
        automatic: boolean,
        cursor?: PreviewCursor,
    ): Promise<void> {
        if (this.state?.createMode || this.preview || this.previewRequest) return;
        const request = new AbortController();
        this.previewRequest = request;
        const tutorial = this.eligibleTutorials?.find(
            (item: CustomEligibleTutorialsOutputTutorialsItem): boolean => item.revision_id === revisionId,
        );
        if (tutorial) tutorial.auto_start = false;
        const path = window.location.pathname;
        try {
            const presentation = await getSdk().custom.tutorialPlaybackPost(
                { revision_id: revisionId, automatic }, { signal: request.signal },
            );
            if (request.signal.aborted || this.state?.createMode || (!cursor && window.location.pathname !== path)) return;
            try {
                window.sessionStorage.setItem(`${this.storageKey}:learner-presentation`, JSON.stringify({
                    revisionId, presentation,
                }));
            } catch {
                // The active run can recover its steps from the server if storage fills up.
            }
            if (!this.presentTutorial(revisionId, presentation, true, cursor)) this.clearLearnerPlayback();
        } catch {
            if (!request.signal.aborted) {
                if (cursor) this.clearLearnerPlayback();
                if (!automatic) showMessage(t("The tutorial could not be opened."), MessageType.ERROR);
            }
        } finally {
            if (this.previewRequest === request) this.previewRequest = null;
        }
    }

    /** Show the introduction for a new run or recover the saved step. */
    private presentTutorial(
        revisionId: string,
        presentation: TutorialPresentation,
        learner: boolean,
        cursor?: PreviewCursor,
    ): boolean {
        const stepId = cursor?.stepId;
        const index = stepId ? presentation.steps.findIndex(
            (step: TutorialPresentationStep): boolean => step.id === stepId,
        ) : introductionIndex;
        if (!presentation.steps.length || (stepId && index === -1)) return false;
        this.preview = { ...presentation, revisionId, index, learner };
        this.presentPreviewStep(!cursor, !cursor?.pageUrl, cursor);
        return true;
    }

    /** Recover an eligible learner's in-progress tutorial after a hard navigation. */
    private resumeLearnerPreview(cursor: PreviewCursor): void {
        if (!this.eligibleTutorials) return;
        const tutorial = this.eligibleTutorials.find(
            (item: CustomEligibleTutorialsOutputTutorialsItem): boolean => item.revision_id === cursor.revisionId,
        );
        if (!tutorial || this.state?.createMode) {
            if (this.preview?.learner) this.closePreview(false);
            else this.clearLearnerPlayback();
            return;
        }
        if (this.preview?.learner && this.preview.revisionId === cursor.revisionId) {
            this.onPreviewUrlChange();
            return;
        }
        try {
            const stored = JSON.parse(window.sessionStorage.getItem(`${this.storageKey}:learner-presentation`) ?? "null");
            if (stored?.revisionId === cursor.revisionId && Array.isArray(stored.presentation?.steps)
                && this.presentTutorial(cursor.revisionId, stored.presentation, true, cursor)) return;
        } catch {
            // An unavailable or older cache is recovered by a fresh start request.
        }
        void this.startLearnerPlayback(cursor.revisionId, false, cursor);
    }

    /** Remove the published presentation and its cursor when the run ends. */
    private clearLearnerPlayback(): void {
        this.storePreviewCursor(null);
        try {
            window.sessionStorage.removeItem(`${this.storageKey}:learner-presentation`);
        } catch {
            // The browser may have disabled session storage.
        }
    }

    /** Record the final step, using the first step for an introduction dismissal. */
    private async recordLearnerOutcome(outcome: "completed" | "dismissed"): Promise<void> {
        const preview = this.preview;
        if (!preview?.learner) return;
        try {
            await getSdk().custom.tutorialPlaybackPatch({
                revision_id: preview.revisionId,
                step_id: (preview.steps[preview.index] ?? preview.steps[0]).id,
                outcome,
            }, { fetchOptions: { keepalive: true } });
        } catch {
            // Closing the UI should work even if progress reporting is unavailable.
        }
    }

    /** Open the presentation preview for the active draft. */
    private startPreview = (): void => {
        const state = this.state;
        if (!state?.createMode || this.previewRequest || this.selection || this.reorderingSteps
            || this.savingStep || this.rowActionPending) return;
        void this.loadPreview(state.revisionId);
    };

    /** Load the draft's presentation and select the saved step when resuming. */
    private async loadPreview(revisionId: string, cursor?: PreviewCursor): Promise<void> {
        this.previewRequest?.abort();
        const request = new AbortController();
        this.previewRequest = request;
        this.updatePreviewButton();
        try {
            const presentation = await getSdk().custom.tutorialRevisionsPreviewTutorialRevision(
                {}, { pk: revisionId }, { signal: request.signal },
            );
            if (request.signal.aborted || !this.isActiveRevision(revisionId)) return;

            if (!this.presentTutorial(revisionId, presentation, false, cursor)) {
                this.closePreview(false);
                showMessage(cursor ? t("The preview step is no longer available.") : t("Add a step before previewing."));
            }
        } catch {
            if (!request.signal.aborted) {
                this.closePreview(false);
                showMessage(t("The tutorial preview could not be opened."), MessageType.ERROR);
            }
        } finally {
            if (this.previewRequest === request) this.previewRequest = null;
            this.updatePreviewButton();
        }
    }

    /** Keep clicks anywhere on the tutorial card out of the page's outside-click handlers. */
    private isolatePresentationEvent = (event: Event): void => {
        event.stopPropagation();
    };

    /** Advance and focus the next tutorial card. */
    private nextPreviewStep = (): void => {
        this.advancePreview(true, true);
    };

    /** Return to an available earlier step without running the departing step's exit actions. */
    private previousPreviewStep = (): void => {
        const preview = this.preview;
        const cursor = preview?.cursor;
        if (!preview || !cursor || preview.index <= 0) return;

        const history = cursor.history ?? [];
        let visit: TutorialVisit | undefined;
        let index = -1;
        while ((visit = history.pop()) !== undefined) {
            index = preview.steps.slice(0, preview.index).findIndex(
                (step: TutorialPresentationStep): boolean => step.id === visit?.stepId,
            );
            if (index >= 0) break;
        }
        this.actionRequest?.abort();
        this.actionRequest = null;
        this.showStepActionError(null, "");
        preview.index = index >= 0 ? index : preview.index - 1;
        this.presentPreviewStep(true, true, undefined, visit?.pageUrl);
    };

    /** Block page interaction on the introduction and honor highlight access on steps. */
    private blockBackdropClick = (event: Event): void => {
        const preview = this.preview;
        if (!preview || preview.steps[preview.index]?.include_backdrop === false) return;
        if (event instanceof KeyboardEvent && (event.key === "Tab" || event.key === "Escape")) return;
        const path = event.composedPath();
        const card = document.getElementById("tutorial-presentation");
        if (card?.hidden !== false || path.includes(card)) return;
        if (this.automatedTarget && !event.isTrusted && path.includes(this.automatedTarget)) return;
        for (const element of path) {
            if (!(element instanceof HTMLElement)) continue;
            const allowed = this.highlightInteraction.get(element);
            if (allowed === undefined) continue;
            if (allowed) return;
            break;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
    };

    /** Advance on the configured mouse gesture after the highlighted control handles it. */
    private onPreviewTargetClick = (event: MouseEvent): void => {
        const preview = this.preview;
        const target = this.presentationTarget;
        if (!preview || !target || this.actionRequest || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        if (event.target instanceof Element && event.target.closest("#tutorial-presentation")) return;
        if (preview.steps[preview.index]?.advance_mode !== event.type || !event.composedPath().includes(target)) return;
        const pageAction = event.target instanceof Element
            && event.target.closest("a[href], button[type='submit'], input[type='submit'], button:not([type])") !== null;
        this.queuePreviewAdvance(!pageAction);
    };

    /** Advance when the learner enters nonempty text in the highlighted control. */
    private onPreviewTargetInput = (event: Event): void => {
        const { preview, presentationTarget } = this;
        if (!preview || !presentationTarget || this.actionRequest || preview.steps[preview.index]?.advance_mode !== "input"
            || !(event instanceof InputEvent) || event.isComposing || !event.composedPath().includes(presentationTarget)) return;
        const input = event.target;
        const value = input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement
            ? input.value
            : input instanceof HTMLElement && input.isContentEditable ? input.textContent : "";
        if (value?.trim()) this.queuePreviewAdvance(true);
    };

    /** Advance on a changed URL that satisfies the current step's navigation trigger. */
    private onPreviewUrlChange = (): void => {
        const preview = this.preview;
        const pageUrl = preview?.cursor?.pageUrl;
        const step = preview?.steps[preview.index];
        if (pageUrl && pageUrl !== window.location.href && step?.advance_mode === "navigation"
            && (!step.advance_url_pattern || this.matchesPathPattern(step.advance_url_pattern, window.location.pathname))) {
            this.queuePreviewAdvance(false);
        }
        this.updatePreviewLayout();
        this.updateLearnerOffers();
    };

    /** Persist the first matching trigger so a reload can finish the same delay. */
    private queuePreviewAdvance(navigate: boolean): void {
        const preview = this.preview;
        const cursor = preview?.cursor;
        if (!preview || !cursor?.stepId || cursor.advanceAt !== undefined || cursor.exit || this.actionRequest || this.actionFailure) return;
        cursor.advanceAt = Date.now() + preview.steps[preview.index].advance_delay_ms;
        cursor.navigate = navigate;
        this.storePreviewCursor(cursor);
        this.schedulePreviewAdvance();
    }

    /** Run the pending trigger once while leaving page focus and navigation intact. */
    private schedulePreviewAdvance(): void {
        window.clearTimeout(this.previewAdvanceTimer);
        const cursor = this.preview?.cursor;
        if (cursor?.advanceAt === undefined || cursor.exit) return;

        /** Ignore callbacks left behind by a completed or manually advanced step. */
        const completeAdvance = (): void => {
            if (this.preview?.cursor === cursor) {
                this.advancePreview(false, cursor.navigate === true && cursor.pageUrl === window.location.href);
            }
        };
        this.previewAdvanceTimer = window.setTimeout(completeAdvance, Math.max(0, cursor.advanceAt - Date.now()));
    }

    /** Start the first step or run outstanding exit actions before advancing. */
    private advancePreview(focusTutorial: boolean, navigate: boolean): void {
        const preview = this.preview;
        const cursor = preview?.cursor;
        if (!preview || !cursor || this.actionRequest) return;
        const interaction = preview.steps[preview.index]?.interaction as StepInteraction | undefined;
        if (interaction && (cursor.afterIndex ?? 0) < interaction.after.length) {
            cursor.exit = { focus: focusTutorial, navigate };
            this.storePreviewCursor(cursor);
            void this.finishStepActions(preview, cursor, interaction);
            return;
        }
        this.advancePreviewCard(preview, focusTutorial, navigate);
    }

    /** Display the following step or finish the presentation after a successful advance. */
    private advancePreviewCard(preview: PreviewRun, focusTutorial: boolean, navigate: boolean): void {
        this.showStepActionError(null, "");
        if (preview.index + 1 === preview.steps.length) {
            void this.recordLearnerOutcome("completed");
            this.closePreview(focusTutorial);
            return;
        }
        const cursor = preview.cursor;
        if (cursor?.stepId) {
            (cursor.history ??= []).push({ stepId: cursor.stepId, pageUrl: cursor.pageUrl });
        }
        preview.index++;
        this.presentPreviewStep(navigate, focusTutorial);
    }

    /** Save the tab's cursor and open a destination only for an authored step. */
    private presentPreviewStep(
        navigate: boolean,
        focusTutorial: boolean,
        restored?: PreviewCursor,
        visitedPageUrl?: string,
    ): void {
        const preview = this.preview;
        const card = document.getElementById("tutorial-presentation");
        if (!preview || !card || this.actionRequest) return;
        this.stopTrackingPreviewLayout();

        const step = preview.steps[preview.index];
        preview.cursor = restored ?? {
            revisionId: preview.revisionId,
            stepId: step?.id ?? null,
            learner: preview.learner,
            history: preview.cursor?.history,
        };
        const canResume = this.storePreviewCursor(preview.cursor);
        window.clearTimeout(this.previewAdvanceTimer);
        if (!step) {
            this.renderPreviewCard(preview, card, focusTutorial);
            return;
        }
        const destination = this.getPreviewDestination(step.destination_url);
        const visitedPage = step.destination_url === "" ? this.getVisitedTutorialPage(visitedPageUrl) : null;
        const targetPage = destination ?? visitedPage;
        const pageChanged = visitedPage
            ? visitedPage.href !== window.location.href
            : destination?.pathname !== window.location.pathname;
        if (navigate && canResume && targetPage && pageChanged) {
            card.hidden = true;
            this.presentationTarget = null;
            this.presentationPrimary = null;
            this.highlightInteraction.clear();
            this.closeTutorialTooltip(card);
            this.renderMode();
            window.location.assign(targetPage.href);
            return;
        }

        const interaction = step.interaction as StepInteraction;
        const onStepPage = step.destination_url === "" || destination?.pathname === window.location.pathname;
        if (!preview.cursor.exit && onStepPage && (preview.cursor.beforeIndex ?? 0) < interaction.before.length) {
            card.hidden = true;
            this.closeTutorialTooltip(card);
            this.drawHighlights([], false);
            this.renderMode();
            void this.enterStepActions(preview, preview.cursor, interaction, card, focusTutorial);
            return;
        }
        this.renderPreviewCard(preview, card, focusTutorial);
        if (preview.cursor.exit) this.advancePreview(preview.cursor.exit.focus, preview.cursor.exit.navigate);
    }

    /** Render the introduction or the current step and set its available navigation controls. */
    private renderPreviewCard(preview: PreviewRun, card: HTMLElement, focusTutorial: boolean): void {
        const step = preview.steps[preview.index];
        const previous = card.querySelector<HTMLButtonElement>("[data-tutorial-preview-previous]");
        const next = card.querySelector<HTMLButtonElement>("[data-tutorial-preview-next]");

        this.presentationTarget = null;
        this.presentationPrimary = null;
        this.highlightInteraction.clear();
        card.dataset.size = step?.size ?? "medium";
        const title = card.querySelector<HTMLElement>("#tutorial-presentation-title");
        const text = card.querySelector<HTMLElement>("[data-tutorial-preview-text]");
        const count = card.querySelector<HTMLElement>("[data-tutorial-preview-count]");
        if (title) title.textContent = step?.name ?? preview.introduction.name;
        if (text) {
            text.innerHTML = DOMPurify.sanitize(step?.text ?? preview.introduction.description, { USE_PROFILES: { html: true } });
            text.hidden = !text.innerHTML;
        }
        if (count) {
            count.hidden = !step;
            count.textContent = step
                ? t("Step {current} of {total}")
                    .replace("{current}", String(preview.index + 1)).replace("{total}", String(preview.steps.length))
                : "";
        }
        if (previous) previous.hidden = preview.index <= 0;
        if (next) {
            next.disabled = false;
            next.textContent = step
                ? preview.index + 1 === preview.steps.length ? t("Finish") : t("Next")
                : t("Start");
        }
        card.hidden = false;
        this.renderMode();
        this.onPreviewUrlChange();
        this.schedulePreviewAdvance();
        if (focusTutorial) title?.focus({ preventScroll: true });
    }

    /** Recover a previously displayed URL only if it belongs to this application. */
    private getVisitedTutorialPage(pageUrl: string | undefined): URL | null {
        if (!pageUrl) return null;
        try {
            const url = new URL(pageUrl);
            return url.origin === window.location.origin ? url : null;
        } catch {
            return null;
        }
    }

    /** Run entry actions and display the instructions once they finish or fail. */
    private async enterStepActions(preview: PreviewRun, cursor: PreviewCursor, interaction: StepInteraction, card: HTMLElement, focus: boolean): Promise<void> {
        this.showStepActionError(null, "");
        const error = await this.runStepActions("before", cursor, interaction);
        if (this.preview !== preview || preview.cursor !== cursor || this.lifecycle.signal.aborted) return;
        if (error) this.showStepActionError("before", error);
        this.renderPreviewCard(preview, card, focus);
    }

    /** Run exit actions and advance only after the sequence completes. */
    private async finishStepActions(preview: PreviewRun, cursor: PreviewCursor, interaction: StepInteraction): Promise<void> {
        this.showStepActionError(null, "");
        const next = document.querySelector<HTMLButtonElement>("#tutorial-presentation [data-tutorial-preview-next]");
        if (next) next.disabled = true;
        const error = await this.runStepActions("after", cursor, interaction);
        if (this.preview !== preview || preview.cursor !== cursor || this.lifecycle.signal.aborted) return;
        if (next) next.disabled = false;
        if (error) {
            this.showStepActionError("after", error);
            this.updatePreviewLayout();
            return;
        }
        this.advancePreviewCard(preview, cursor.exit?.focus ?? false, cursor.exit?.navigate ?? true);
    }

    /** Retry the failed action in its phase without repeating completed actions. */
    private retryStepActions = (): void => {
        const cursor = this.preview?.cursor;
        if (!cursor || !this.actionFailure || this.actionRequest) return;
        if (this.actionFailure === "before") this.presentPreviewStep(false, true, cursor);
        else this.advancePreview(cursor.exit?.focus ?? true, cursor.exit?.navigate ?? true);
    };

    /** Make the failed phase and target visible while leaving the tutorial closable. */
    private showStepActionError(phase: StepActionPhase | null, message: string): void {
        this.actionFailure = phase;
        const card = document.getElementById("tutorial-presentation");
        const error = card?.querySelector<HTMLElement>("[data-tutorial-action-error]");
        const retry = card?.querySelector<HTMLButtonElement>("[data-tutorial-action-retry]");
        if (error) {
            error.textContent = message;
            error.hidden = !message;
        }
        if (retry) retry.hidden = !phase;
    }

    /** Execute ordered actions and checkpoint each dispatch before it can navigate away. */
    private async runStepActions(phase: StepActionPhase, cursor: PreviewCursor, interaction: StepInteraction): Promise<string> {
        const request = new AbortController();
        this.actionRequest = request;
        const progress = phase === "before" ? "beforeIndex" : "afterIndex";
        try {
            for (let index = cursor[progress] ?? 0; index < interaction[phase].length; index++) {
                const action = interaction[phase][index];
                const highlight = interaction.highlights.find(item => item.id === action.highlight_id);
                const selector = highlight?.selector ?? action.selector;
                const failure = (phase === "before" ? t("Before step action {number} could not run on {target}.")
                    : t("After step action {number} could not run on {target}."))
                    .replace("{number}", String(index + 1)).replace("{target}", highlight?.label ?? selector);
                const target = await this.waitForActionTarget(selector, action.kind, request.signal);
                if (request.signal.aborted) return "";
                if (!target) return failure;
                const execute = this.prepareStepAction(action, target);
                if (!execute) return failure;
                cursor[progress] = index + 1;
                this.storePreviewCursor(cursor);
                this.automatedTarget = target;
                try {
                    execute();
                } catch {
                    return failure;
                } finally {
                    this.automatedTarget = null;
                }
            }
            return "";
        } finally {
            if (this.actionRequest === request) this.actionRequest = null;
        }
    }

    /** Wait briefly for a preceding action to render or enable the next target. */
    private async waitForActionTarget(selector: string, kind: StepAction["kind"], signal: AbortSignal): Promise<HTMLElement | null> {
        const deadline = Date.now() + 3000;
        while (!signal.aborted) {
            const target = this.findStepElement(selector);
            const closedMenu = typeof target?.showPopover === "function"
                && target.closest("[data-dropdown-panel][popover]:not(:popover-open)");
            if (target?.getClientRects().length && !closedMenu
                && (kind === "wait" || !target.matches(":disabled, [aria-disabled='true']"))) return target;
            if (Date.now() >= deadline) break;
            await new Promise<void>(resolve => window.setTimeout(resolve, 50));
        }
        return null;
    }

    /** Prepare a control action and reject unsupported fields or missing options before dispatch. */
    private prepareStepAction(action: StepAction, target: HTMLElement): (() => void) | null {
        if (action.kind === "wait") {
            /** Waiting succeeds once the target is present. */
            return (): void => {};
        }
        if (action.kind === "click") {
            /** Dispatch the element's ordinary click behavior. */
            return (): void => target.click();
        }
        if (action.kind === "select" && target instanceof HTMLSelectElement) {
            const options = Array.from(target.options);
            const option = options.find(item => item.value === action.value)
                ?? options.find(item => item.text.trim() === action.value.trim());
            if (!option || option.disabled || option.closest("optgroup:disabled")) return null;
            /** Select the option and notify the existing field handlers. */
            return (): void => {
                target.value = option.value;
                this.dispatchStepInput(target);
            };
        }
        if (action.kind !== "fill") return null;
        if (target instanceof HTMLTextAreaElement || (target instanceof HTMLInputElement
            && ["text", "search", "email", "tel", "url", "number", "date", "time"].includes(target.type))) {
            if (target.readOnly) return null;
            /** Fill a concrete text field and notify the existing field handlers. */
            return (): void => {
                target.value = action.value;
                this.dispatchStepInput(target);
            };
        }
        if (!target.isContentEditable) return null;
        /** Fill an editable text element without interpreting the value as markup. */
        return (): void => {
            target.textContent = action.value;
            this.dispatchStepInput(target);
        };
    }

    /** Notify the same listeners used by direct input and selection. */
    private dispatchStepInput(target: HTMLElement): void {
        target.dispatchEvent(new InputEvent("input", { bubbles: true }));
        target.dispatchEvent(new Event("change", { bubbles: true }));
    }

    /** Restrict browser navigation to local page URLs returned by the preview API. */
    private getPreviewDestination(path: string | null): URL | null {
        if (!path || !path.startsWith("/") || path.startsWith("//")) return null;
        try {
            const url = new URL(path, window.location.origin);
            return url.origin === window.location.origin ? url : null;
        } catch {
            return null;
        }
    }

    /** Match a pathname against an exact path or a pattern containing asterisks. */
    private matchesPathPattern(urlPattern: string, pathname: string): boolean {
        const pattern = this.getPreviewDestination(urlPattern)?.pathname;
        if (!pattern) return false;
        if (!pattern.includes("*")) return pathname === pattern;

        const parts = pattern.split("*");
        const first = parts.shift() ?? "";
        const last = parts.pop() ?? "";
        if (!pathname.startsWith(first) || !pathname.endsWith(last)) return false;
        const end = pathname.length - last.length;
        let offset = first.length;
        for (const part of parts) {
            const start = pathname.indexOf(part, offset);
            if (start === -1) return false;
            offset = start + part.length;
        }
        return offset <= end;
    }

    /** Center the introduction and keep authored steps aligned with their targets. */
    private updatePreviewLayout = (): void => {
        this.stopTrackingPreviewLayout();
        const preview = this.preview;
        const card = document.getElementById("tutorial-presentation");
        if (!preview || card?.hidden !== false) return;

        const step = preview.steps[preview.index];
        if (!step) {
            this.closeTutorialTooltip(card);
            this.drawHighlights([], true);
            this.positionPreviewCard(card, null);
            card.querySelector("[data-tutorial-preview-next]")?.classList.remove("hidden");
            for (const message of card.querySelectorAll<HTMLElement>("[data-tutorial-preview-hint], [data-tutorial-preview-notice]")) {
                message.textContent = "";
                message.hidden = true;
            }
            return;
        }
        const onStepPage = step.destination_url === ""
            || this.getPreviewDestination(step.destination_url)?.pathname === window.location.pathname;
        if (onStepPage && preview.cursor && !preview.cursor.pageUrl) {
            preview.cursor.pageUrl = window.location.href;
            this.storePreviewCursor(preview.cursor);
        }
        const interaction = step.interaction as StepInteraction;
        const resolved = onStepPage ? interaction.highlights.map(highlight => this.resolveHighlight(highlight, step.include_backdrop)) : [];
        const advance = resolved.find(item => item.highlight.id === interaction.advance_highlight_id);
        const tooltip = resolved.find(item => item.highlight.id === interaction.tooltip_highlight_id);
        const target = advance?.target ?? null;
        const menuTrigger = advance?.menuTrigger ?? null;
        const tooltipTarget = tooltip?.target ?? tooltip?.menuTrigger ?? null;
        const highlights: HTMLElement[] = [];
        let needsSidebar = false;
        this.highlightInteraction.clear();
        for (const item of resolved) {
            const element = item.target ?? item.menuTrigger;
            if (!element) continue;
            highlights.push(element);
            const opensSidebar = item.menuTrigger?.id === "sidebar-toggle";
            needsSidebar ||= opensSidebar;
            const mayInteract = this.highlightInteraction.get(element) !== false && (opensSidebar || item.highlight.allow_interaction);
            this.highlightInteraction.set(element, mayInteract);
        }
        const primary = (step.show_as_tooltip ? tooltipTarget : null) ?? target ?? menuTrigger ?? highlights[0] ?? null;
        const previousHighlight = this.presentationPrimary;
        this.presentationTarget = target;
        this.presentationPrimary = primary;
        if (primary && primary !== previousHighlight) {
            primary.scrollIntoView({ block: "center", inline: "nearest" });
        }
        const highlightedBounds = this.drawHighlights(highlights, step.include_backdrop);

        const notice = card.querySelector<HTMLElement>("[data-tutorial-preview-notice]");
        const waitingForDelay = step.advance_mode === "delay" && onStepPage;
        if (waitingForDelay) this.queuePreviewAdvance(true);
        const waitingForNavigation = step.advance_mode === "navigation" && Boolean(preview.cursor?.pageUrl);
        const canNavigate = waitingForNavigation && (Array.from(this.highlightInteraction.values()).includes(true) || !step.include_backdrop);
        const canUseTarget = target !== null && (!step.include_backdrop || this.highlightInteraction.get(target) === true);
        const canAdvanceAutomatically = waitingForDelay || canNavigate
            || (canUseTarget && (step.advance_mode === "click" || step.advance_mode === "dblclick" || step.advance_mode === "input"));
        card.querySelector<HTMLButtonElement>("[data-tutorial-preview-next]")
            ?.classList.toggle("hidden", this.actionFailure === "after" || (!this.actionFailure && step.hide_next_button && canAdvanceAutomatically));
        if (notice) {
            let message = "";
            if (!onStepPage && !waitingForNavigation) {
                message = t("This step’s page could not be opened.");
            }
            else if (onStepPage && !highlights.length && interaction.highlights.length) message = t("The highlighted area is unavailable on this page.");
            if (notice.textContent !== message) notice.textContent = message;
            notice.hidden = !message;
        }
        const hint = card.querySelector<HTMLElement>("[data-tutorial-preview-hint]");
        if (hint) {
            let message = "";
            if (canUseTarget && step.advance_mode === "click") message = t("Click the highlighted area to continue.");
            if (canUseTarget && step.advance_mode === "dblclick") message = t("Double-click the highlighted area to continue.");
            if (canUseTarget && step.advance_mode === "input") message = t("Type in the highlighted input to continue.");
            if (waitingForDelay) message = t("This step advances automatically.");
            if (waitingForNavigation) {
                message = step.advance_url_pattern
                    ? t("Open a page matching {pattern} to continue.").replace("{pattern}", step.advance_url_pattern)
                    : t("Go to a new URL to continue.");
            }
            if (menuTrigger) message = t("Open the highlighted menu to continue.");
            if (needsSidebar) message = t("Open the sidebar to see this highlight.");
            if (hint.textContent !== message) hint.textContent = message;
            hint.hidden = !message;
        }
        if (!this.previewPosition && step.show_as_tooltip && tooltipTarget) {
            this.positionTutorialTooltip(card, tooltipTarget);
        } else {
            if (!this.previewPosition) this.closeTutorialTooltip(card);
            this.positionPreviewCard(card, step.advance_mode === "manual" && !step.include_backdrop ? null : primary ?? null);
        }
        this.trackPreviewLayout(card, highlightedBounds);
    };

    /** Keep the spotlight and card aligned when targets move without a page scroll or resize. */
    private trackPreviewLayout(card: HTMLElement, highlightedBounds: ReadonlyMap<HTMLElement, DOMRect>): void {
        if (!highlightedBounds.size) return;

        /** Refresh the presentation only when a highlighted element moves, resizes, or is replaced. */
        const checkBounds = (): void => {
            this.previewLayoutFrame = null;
            if (!this.preview || card.hidden) return;

            for (const [target, previous] of highlightedBounds) {
                const current = target.getBoundingClientRect();
                if (!target.isConnected || current.x !== previous.x || current.y !== previous.y
                    || current.width !== previous.width || current.height !== previous.height) {
                    this.updatePreviewLayout();
                    return;
                }
            }
            this.previewLayoutFrame = window.requestAnimationFrame(checkBounds);
        };
        this.previewLayoutFrame = window.requestAnimationFrame(checkBounds);
    }

    /** Release measurements when the presentation moves to another step or closes. */
    private stopTrackingPreviewLayout(): void {
        if (this.previewLayoutFrame === null) return;
        window.cancelAnimationFrame(this.previewLayoutFrame);
        this.previewLayoutFrame = null;
    }

    /** Keep the interactive tutorial card anchored above the target and its dropdown. */
    private positionTutorialTooltip(card: HTMLElement, target: HTMLElement): void {
        const owner = typeof card.showPopover === "function" ? target.closest<HTMLElement>(":popover-open") : null;
        if (this.tooltipPopoverOwner !== owner) {
            setTooltipTopLayer(card, false);
            this.tooltipPopoverOwner = owner;
        }
        card.setAttribute("data-tutorial-tooltip", "");
        setTooltipTopLayer(card, true);
        card.dataset.tooltipPosition = positionTooltip(target, card, "bottom", true);
    }

    /** Remove the tooltip position and return the card to the normal document layer. */
    private closeTutorialTooltip(card: HTMLElement): void {
        if (!card.hasAttribute("data-tutorial-tooltip")) return;
        this.tooltipPopoverOwner = null;
        setTooltipTopLayer(card, false);
        card.removeAttribute("data-tutorial-tooltip");
        delete card.dataset.tooltipPosition;
        card.style.removeProperty("top");
        card.style.removeProperty("left");
        card.style.removeProperty("--tooltip-anchor-x");
        card.style.removeProperty("--tooltip-anchor-y");
    }

    /** Keep the card centered unless it would cover an element the learner needs. */
    private positionPreviewCard(card: HTMLElement, target: HTMLElement | null): void {
        if (this.previewPosition) {
            this.placePreviewCard(card, this.previewPosition.left, this.previewPosition.top);
            return;
        }
        card.style.removeProperty("left");
        card.style.removeProperty("top");
        if (!target) return;
        const centered = card.getBoundingClientRect();
        const bounds = target.getBoundingClientRect();
        if (bounds.right <= centered.left || bounds.left >= centered.right
            || bounds.bottom <= centered.top || bounds.top >= centered.bottom) return;

        const gap = 12;
        if (bounds.bottom + centered.height + 2 * gap <= window.innerHeight) {
            card.style.top = `${bounds.bottom + gap + centered.height / 2}px`;
        } else if (bounds.top >= centered.height + 2 * gap) {
            card.style.top = `${bounds.top - gap - centered.height / 2}px`;
        } else if (bounds.right + centered.width + 2 * gap <= window.innerWidth) {
            card.style.left = `${bounds.right + gap + centered.width / 2}px`;
        } else if (bounds.left >= centered.width + 2 * gap) {
            card.style.left = `${bounds.left - gap - centered.width / 2}px`;
        }
    }

    /** Capture the pointer offset so the card stays under its move handle. */
    private startPreviewDrag = (event: PointerEvent): void => {
        const handle = event.currentTarget;
        if (!(handle instanceof HTMLButtonElement) || !event.isPrimary || event.button !== 0) return;
        const card = handle.closest<HTMLElement>("#tutorial-presentation");
        if (!card) return;

        const { left, top } = card.getBoundingClientRect();
        this.previewDrag = {
            pointerId: event.pointerId,
            offsetX: event.clientX - left,
            offsetY: event.clientY - top,
        };
        handle.setPointerCapture(event.pointerId);
    };

    /** Move the card with the pointer that owns the drag. */
    private movePreviewDrag = (event: PointerEvent): void => {
        const drag = this.previewDrag;
        const handle = event.currentTarget;
        if (!drag || drag.pointerId !== event.pointerId || !(handle instanceof HTMLButtonElement)) return;
        const card = handle.closest<HTMLElement>("#tutorial-presentation");
        if (card) this.placePreviewCard(card, event.clientX - drag.offsetX, event.clientY - drag.offsetY);
    };

    /** Release the drag when its pointer is released or cancelled. */
    private endPreviewDrag = (event: PointerEvent): void => {
        if (this.previewDrag?.pointerId === event.pointerId) this.previewDrag = null;
    };

    /** Move the focused tutorial handle with the arrow keys. */
    private movePreviewWithKeyboard = (event: KeyboardEvent): void => {
        const movement = keyboardMoves.get(event.key);
        const handle = event.currentTarget;
        if (!movement || !(handle instanceof HTMLButtonElement)) return;
        const card = handle.closest<HTMLElement>("#tutorial-presentation");
        if (!card) return;

        event.preventDefault();
        const { left, top } = card.getBoundingClientRect();
        this.placePreviewCard(card, left + movement[0], top + movement[1]);
    };

    /** Keep the user's manual placement in bounds for the current playback. */
    private placePreviewCard(card: HTMLElement, left: number, top: number): void {
        card.setAttribute("data-tutorial-positioned", "");
        this.previewPosition = this.fitPanelPosition(card, left, top);
        card.style.left = `${this.previewPosition.left}px`;
        card.style.top = `${this.previewPosition.top}px`;
    }

    /** Restore automatic placement when playback ends. */
    private resetPreviewPlacement(card: HTMLElement): void {
        this.previewDrag = null;
        this.previewPosition = null;
        this.closeTutorialTooltip(card);
        card.removeAttribute("data-tutorial-positioned");
        card.style.removeProperty("left");
        card.style.removeProperty("top");
    }

    /** Realign highlights and the tutorial card when a sliding app surface settles. */
    private onPreviewLayoutTransition = (event: TransitionEvent): void => {
        if (event.target instanceof Element && event.target.matches("#sidebar, [data-modal-container], [data-drawer-panel]")) {
            this.updatePreviewLayout();
        }
    };

    /** Refresh the presentation when a native popover enters or leaves the top layer. */
    private onPreviewPopoverToggle = (event: Event): void => {
        if (event.target instanceof HTMLElement && event.target.id !== "tutorial-presentation"
            && event.target.hasAttribute("popover")) {
            this.updatePreviewLayout();
        }
    };

    /** Find an app element while excluding the tutorial's own controls. */
    private findStepElement(selector: string): HTMLElement | null {
        if (!selector) return null;
        try {
            const target = document.querySelector(selector);
            return target instanceof HTMLElement && !this.element?.contains(target)
                && !target.closest("#tutorial-presentation, #tutorial-step-modal") ? target : null;
        } catch {
            return null;
        }
    }

    /** Resolve a highlight or a visible control that can reveal its collapsed container. */
    private resolveHighlight(highlight: StepHighlight, backdrop: boolean): ResolvedHighlight {
        const target = this.findStepElement(highlight.selector);
        if (target && this.isHighlightCoveredByModal(target)) {
            return { highlight, target: null, menuTrigger: null };
        }
        if (target?.closest("#sidebar[inert]")) {
            const toggle = document.getElementById("sidebar-toggle");
            return { highlight, target: null, menuTrigger: toggle?.getClientRects().length ? toggle : null };
        }
        const closedMenu = typeof target?.showPopover === "function"
            ? target.closest<HTMLElement>("[data-dropdown-panel][popover]:not(:popover-open)") : null;
        if (target?.getClientRects().length && !closedMenu) return { highlight, target, menuTrigger: null };
        if (backdrop && !highlight.allow_interaction) return { highlight, target: null, menuTrigger: null };
        const trigger = closedMenu?.parentElement?.querySelector<HTMLElement>(":scope > [aria-haspopup='true']");
        return { highlight, target: null, menuTrigger: trigger?.getClientRects().length ? trigger : null };
    }

    /** Suppress highlights behind the active modal while allowing controls portalled above it. */
    private isHighlightCoveredByModal(target: HTMLElement): boolean {
        const modal = getTopModal()?.element;
        if (!modal || modal.contains(target)) return false;

        const bounds = target.getBoundingClientRect();
        const x = Math.max(0, Math.min(window.innerWidth - 1, bounds.left + bounds.width / 2));
        const y = Math.max(0, Math.min(window.innerHeight - 1, bounds.top + bounds.height / 2));
        const firstLayer = document.elementsFromPoint(x, y).find(
            (element: Element): boolean => element === target || element === modal,
        );
        return firstLayer === modal;
    }

    /** Close the preview using either of its visible controls. */
    private onClosePreview = (): void => {
        void this.recordLearnerOutcome("dismissed");
        this.closePreview(true);
    };

    /** Keep preview keys usable while a page modal is open behind it. */
    private onPreviewKey = (event: KeyboardEvent): void => {
        if (event.defaultPrevented || !this.preview) return;
        if (event.key === "Escape") {
            event.preventDefault();
            this.onClosePreview();
        } else if (event.key === "Tab" && document.activeElement?.closest("#tutorial-presentation")) {
            event.stopPropagation();
        }
    };

    /** Clear the presentation and return focus to its launcher if requested. */
    private closePreview(restoreFocus: boolean): void {
        if (!this.preview && !this.previewRequest) return;
        const learner = this.preview?.learner;
        this.previewRequest?.abort();
        this.previewRequest = null;
        this.actionRequest?.abort();
        this.actionRequest = null;
        this.showStepActionError(null, "");
        this.preview = null;
        this.stopTrackingPreviewLayout();
        window.clearTimeout(this.previewAdvanceTimer);
        this.presentationTarget = null;
        this.presentationPrimary = null;
        this.highlightInteraction.clear();
        if (learner) this.clearLearnerPlayback();
        else this.storePreviewCursor(null);

        const card = document.getElementById("tutorial-presentation");
        const backdrop = document.getElementById("tutorial-presentation-backdrop");
        if (card) {
            this.resetPreviewPlacement(card);
            card.hidden = true;
        }
        if (backdrop) backdrop.hidden = true;
        this.drawHighlight(null, false);
        this.renderMode();
        this.updatePreviewButton();
        if (restoreFocus) {
            const opener = learner
                ? document.getElementById("tutorial-launcher-trigger")
                : this.element?.querySelector<HTMLElement>("[data-tutorial-preview-start]");
            opener?.focus();
        }
    }

    /** Enable preview after at least one step has loaded. */
    private updatePreviewButton(): void {
        const button = this.element?.querySelector<HTMLButtonElement>("[data-tutorial-preview-start]");
        const rows = this.element?.querySelector("[data-tutorial-step-rows]");
        if (button) button.disabled = this.previewRequest !== null || !rows?.childElementCount;
    }

    /** Store only the per-tab cursor needed to resume a preview across page loads. */
    private storePreviewCursor(cursor: PreviewCursor | null): boolean {
        try {
            const key = `${this.storageKey}:preview`;
            if (cursor) window.sessionStorage.setItem(key, JSON.stringify(cursor));
            else window.sessionStorage.removeItem(key);
            return true;
        } catch {
            return false;
        }
    }

    /** Recover this tab's introduction or authored step cursor. */
    private readPreviewCursor(): PreviewCursor | null {
        try {
            const cursor = JSON.parse(window.sessionStorage.getItem(`${this.storageKey}:preview`) ?? "null") as PreviewCursor | null;
            if (typeof cursor?.revisionId !== "string" || (cursor.stepId !== null && typeof cursor.stepId !== "string")) return null;
            /** Keep valid visits from old or partially restored cursors. */
            function isVisit(visit: TutorialVisit | null): visit is TutorialVisit {
                return typeof visit?.stepId === "string" && (visit.pageUrl === undefined || typeof visit.pageUrl === "string");
            }
            return {
                revisionId: cursor.revisionId,
                stepId: cursor.stepId,
                pageUrl: typeof cursor.pageUrl === "string" ? cursor.pageUrl : undefined,
                advanceAt: Number.isFinite(cursor.advanceAt) ? cursor.advanceAt : undefined,
                navigate: cursor.navigate === true,
                learner: cursor.learner === true,
                beforeIndex: Number.isSafeInteger(cursor.beforeIndex) ? cursor.beforeIndex : undefined,
                afterIndex: Number.isSafeInteger(cursor.afterIndex) ? cursor.afterIndex : undefined,
                exit: cursor.exit ? { focus: cursor.exit.focus === true, navigate: cursor.exit.navigate === true } : undefined,
                history: Array.isArray(cursor.history) ? cursor.history.filter(isVisit) : undefined,
            };
        } catch {
            return null;
        }
    }

    /** Resume preview after navigation or browser history restoration. */
    private resumePreview(): void {
        const cursor = this.readPreviewCursor();
        if (cursor?.learner) {
            this.resumeLearnerPreview(cursor);
            return;
        }
        if (!cursor || !this.isActiveRevision(cursor.revisionId)) {
            this.closePreview(false);
            if (cursor) this.storePreviewCursor(null);
            return;
        }
        if (this.preview?.revisionId === cursor.revisionId && (this.preview.steps[this.preview.index]?.id ?? null) === cursor.stepId) {
            this.presentPreviewStep(false, false, cursor);
        } else {
            void this.loadPreview(cursor.revisionId, cursor);
        }
    }

    /** Edit, copy, or remove a step while keeping the current revision in view. */
    private onStepAction = async (event: Event): Promise<void> => {
        if (!(event.target instanceof Element) || this.savingStep || this.rowActionPending || this.reorderingSteps) return;
        const button = event.target.closest<HTMLButtonElement>("[data-tutorial-step-action]");
        const row = button?.closest("tr");
        const stepId = row?.dataset.stepId;
        const state = this.state;
        if (!button || !stepId || !state?.createMode) return;

        const action = button.dataset.tutorialStepAction;
        if (action !== "edit" && action !== "copy" && action !== "remove") return;
        this.rowActionPending = true;
        button.disabled = true;
        const signal = this.lifecycle.signal;
        try {
            const sdk = getSdk().custom;
            if (action === "edit") {
                const values = await sdk.tutorialStepsTutorialStepDetailGet({}, { pk: stepId }, { signal });
                if (!signal.aborted && this.isActiveRevision(state.revisionId)) {
                    this.openStepForm(button, {
                        id: stepId,
                        revisionId: state.revisionId,
                        editing: true,
                    }, values);
                }
            } else if (action === "copy") {
                const step = await sdk.tutorialStepsTutorialStepDetailPost(
                    { step_id: crypto.randomUUID() }, { pk: stepId }, { signal },
                );
                if (!signal.aborted && this.isActiveRevision(state.revisionId)) {
                    await this.loadSteps();
                    if (!signal.aborted && this.isActiveRevision(state.revisionId)) {
                        this.element?.querySelector<HTMLButtonElement>(
                            `[data-step-id="${CSS.escape(step.id)}"] [data-tutorial-step-action="edit"]`,
                        )?.focus();
                    }
                }
            } else {
                await sdk.tutorialStepsTutorialStepDetailDelete({}, { pk: stepId }, { signal });
                if (!signal.aborted && this.isActiveRevision(state.revisionId)) {
                    if (state.currentStep === Number(row?.dataset.stepSequence)) {
                        this.saveState({ ...state, currentStep: 0 });
                    } else {
                        void this.loadSteps();
                    }
                }
            }
        } catch (error) {
            if (!signal.aborted && this.isActiveRevision(state.revisionId)) {
                if (error instanceof BloomerpHttpError && error.status === 404) void this.loadSteps();
                const messages = {
                    edit: t("The step could not be opened for editing."),
                    copy: t("The step could not be copied."),
                    remove: t("The step could not be removed."),
                };
                showMessage(messages[action], MessageType.ERROR);
            }
        } finally {
            this.rowActionPending = false;
            button.disabled = false;
        }
    };

    /** Check that a response still belongs to the revision shown in the panel. */
    private isActiveRevision(revisionId: string): boolean {
        return this.state?.createMode === true && this.state.revisionId === revisionId;
    }

    /** Keep row reordering separate from other pending writes and list loads. */
    private canReorderSteps = (): boolean => {
        return this.state?.createMode === true && !this.stepRequest && !this.savingStep
            && !this.rowActionPending && !this.reorderingSteps;
    };

    /** Snapshot the row order before moving a step. */
    private onStepSortStart = (): void => {
        this.orderBeforeDrag = this.stepSortable?.toArray() ?? [];
    };

    /** Save only drops that changed the step's position. */
    private onStepSortEnd = (event: SortableEvent): void => {
        const previousOrder = this.orderBeforeDrag;
        this.orderBeforeDrag = [];
        if (previousOrder.length < 2 || event.oldDraggableIndex === event.newDraggableIndex) return;
        void this.saveStepOrder(previousOrder);
    };

    /** Move the focused step one position with the Up or Down arrow. */
    private onStepReorderKey = (event: KeyboardEvent): void => {
        const handle = event.target;
        const sortable = this.stepSortable;
        if (!(handle instanceof HTMLButtonElement) || !handle.matches("[data-tutorial-step-drag]")) return;
        if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
        event.preventDefault();
        if (!sortable || !this.canReorderSteps()) return;

        const row = handle.closest("tr");
        const sibling = event.key === "ArrowUp" ? row?.previousElementSibling : row?.nextElementSibling;
        if (!row || !sibling) return;

        const previousOrder = sortable.toArray();
        if (event.key === "ArrowUp") sibling.before(row);
        else sibling.after(row);
        handle.focus({ preventScroll: true });
        void this.saveStepOrder(previousOrder);
    };

    /** Persist the visual order and restore it if the request fails. */
    private async saveStepOrder(previousOrder: string[]): Promise<void> {
        const sortable = this.stepSortable;
        const state = this.state;
        if (!sortable || !state?.createMode) return;
        if (!this.canReorderSteps()) {
            sortable.sort(previousOrder);
            return;
        }

        this.reorderingSteps = true;
        sortable.option("disabled", true);
        const signal = this.lifecycle.signal;
        try {
            const { steps } = await getSdk().custom.tutorialRevisionsReorderTutorialSteps({
                step_ids: sortable.toArray(),
            }, { pk: state.revisionId }, { signal });
            if (!signal.aborted && this.isActiveRevision(state.revisionId)) {
                this.applyStepSequences(sortable, steps);
                if (this.stepRequest) void this.loadSteps();
            }
        } catch (error) {
            if (!signal.aborted && this.isActiveRevision(state.revisionId)) {
                sortable.sort(previousOrder);
                if (!(error instanceof BloomerpHttpError) || error.status === 409) void this.loadSteps();
                showMessage(t("The step order could not be saved."), MessageType.ERROR);
            }
        } finally {
            this.reorderingSteps = false;
            if (this.stepSortable === sortable) sortable.option("disabled", false);
        }
    }

    /** Apply saved sequence values while keeping focus on the same step. */
    private applyStepSequences(sortable: Sortable, steps: TutorialStepSummary[]): void {
        const sequences = new Map<string, number>();
        for (const step of steps) sequences.set(step.id, step.sequence);

        const state = this.state;
        let currentSequence = state?.currentStep;
        for (const row of sortable.el.querySelectorAll<HTMLTableRowElement>("tr[data-step-id]")) {
            const sequence = sequences.get(row.dataset.stepId ?? "");
            if (sequence === undefined) continue;
            if (state?.currentStep === Number(row.dataset.stepSequence)) currentSequence = sequence;
            row.dataset.stepSequence = String(sequence);
        }
        if (state && currentSequence !== undefined && currentSequence !== state.currentStep) {
            this.persistState({ ...state, currentStep: currentSequence });
        }
        const savedOrder = Array.from(sequences.keys());
        if (savedOrder.join(",") !== sortable.toArray().join(",")) sortable.sort(savedOrder);
    }

    /** Load the active revision's steps and discard responses from superseded requests. */
    private async loadSteps(): Promise<void> {
        this.stepRequest?.abort();
        this.stepRequest = null;
        this.orderBeforeDrag = [];

        const state = this.state;
        const rows = this.element?.querySelector<HTMLTableSectionElement>("[data-tutorial-step-rows]");
        const status = this.element?.querySelector<HTMLElement>("[data-tutorial-steps-status]");
        if (!state?.createMode || !state.revisionId || !rows || !status) return;

        const request = new AbortController();
        this.stepRequest = request;
        rows.replaceChildren();
        this.updatePreviewButton();
        status.hidden = false;
        status.textContent = t("Loading steps…");
        this.repositionPanel();

        try {
            const { steps } = await getSdk().custom.tutorialRevisionsTutorialRevisionSteps(
                {}, { pk: state.revisionId },
                { signal: request.signal },
            );
            if (request.signal.aborted) return;
            this.renderStepRows(rows, steps);
            this.updatePreviewButton();
            status.hidden = steps.length > 0;
            status.textContent = steps.length ? "" : t("No steps yet.");
        } catch {
            if (!request.signal.aborted) status.textContent = t("Could not load tutorial steps.");
        } finally {
            if (this.stepRequest === request) {
                this.stepRequest = null;
                this.repositionPanel();
            }
        }
    }

    /** Render step titles and their compact row controls in sequence order. */
    private renderStepRows(rows: HTMLTableSectionElement, steps: TutorialStepSummary[]): void {
        const labelTemplate = this.element?.querySelector<HTMLTemplateElement>("[data-tutorial-step-label]");
        const actionTemplate = this.element?.querySelector<HTMLTemplateElement>("[data-tutorial-step-actions]");
        for (const step of steps) {
            const row = rows.insertRow();
            row.className = "group/tutorial-step";
            row.dataset.stepId = step.id;
            row.dataset.stepSequence = String(step.sequence);
            const label = row.insertCell();
            label.className = "py-1 wrap-break-word";
            if (labelTemplate) label.append(labelTemplate.content.cloneNode(true));
            const name = label.querySelector("[data-tutorial-step-name]") ?? label;
            name.textContent = step.name;
            const actions = row.insertCell();
            if (actionTemplate) actions.append(actionTemplate.content.cloneNode(true));
        }
    }

    /** Start moving the panel without snapping its corners to the pointer. */
    private startDrag = (event: PointerEvent): void => {
        const handle = event.currentTarget;
        if (!this.element || !(handle instanceof HTMLButtonElement)) return;
        if (!event.isPrimary || event.button !== 0) return;

        const { left, top } = this.element.getBoundingClientRect();
        this.drag = {
            pointerId: event.pointerId,
            offsetX: event.clientX - left,
            offsetY: event.clientY - top,
            position: null,
        };
        handle.setPointerCapture(event.pointerId);
    };

    /** Move the panel with the pointer that owns the drag. */
    private moveDrag = (event: PointerEvent): void => {
        if (this.drag?.pointerId !== event.pointerId) return;
        this.drag.position = this.positionPanel(
            event.clientX - this.drag.offsetX,
            event.clientY - this.drag.offsetY,
        );
    };

    /** Remember the final position when a drag ends. */
    private endDrag = (event: PointerEvent): void => {
        if (this.drag?.pointerId !== event.pointerId) return;
        const { position } = this.drag;
        this.drag = null;
        if (position) this.savePanelPreferences({ position });
    };

    /** Let authors move the focused drag handle with the arrow keys. */
    private moveWithKeyboard = (event: KeyboardEvent): void => {
        const movement = keyboardMoves.get(event.key);
        if (!this.element || !movement) return;
        event.preventDefault();
        const { left, top } = this.element.getBoundingClientRect();
        const position = this.positionPanel(left + movement[0], top + movement[1]);
        if (position) this.savePanelPreferences({ position });
    };

    /** Restore the preferred position within the viewport bounds. */
    private repositionPanel = (): void => {
        const position = this.drag?.position ?? this.panelPreferences.position;
        if (position) this.positionPanel(position.left, position.top);
    };

    /** Move the visible panel and return the coordinates that fit on screen. */
    private positionPanel(left: number, top: number): PanelPosition | null {
        const panel = this.element;
        if (!panel || panel.hidden) return null;

        const position = this.fitPanelPosition(panel, left, top);
        panel.style.left = `${position.left}px`;
        panel.style.top = `${position.top}px`;
        panel.style.right = "auto";
        panel.style.bottom = "auto";
        return position;
    }

    /** Clamp a panel's top-left corner to the current viewport. */
    private fitPanelPosition(panel: HTMLElement, left: number, top: number): PanelPosition {
        const { width, height } = panel.getBoundingClientRect();
        return {
            left: Math.max(0, Math.min(left, window.innerWidth - width)),
            top: Math.max(0, Math.min(top, window.innerHeight - height)),
        };
    }

    /** Restore the authoring session and panel preferences for this account. */
    private restoreState(): void {
        this.state = getLocalStorageValue<TutorialState | null>(this.storageKey, null);
        const preferences = getLocalStorageValue<PanelPreferences | null>(`${this.storageKey}:panel`, null);
        const position = preferences?.position;
        this.panelPreferences = {
            position: position && Number.isFinite(position.left) && Number.isFinite(position.top) ? position : null,
        };
        this.renderMode();
        void this.loadRevisionSettings();
        void this.loadSteps();
        this.resumePreview();
    }

    /** Keep editor window preferences across revisions and page loads. */
    private savePanelPreferences(preferences: PanelPreferences): void {
        this.panelPreferences = preferences;
        setLocalStorageValue(`${this.storageKey}:panel`, preferences);
    }

    /** Persist the revision ID, mode, and step together. */
    private persistState(state: TutorialState): void {
        this.state = state;
        setLocalStorageValue(this.storageKey, state);
    }

    /** Save authoring mode and refresh the panel for a revision change. */
    private saveState(state: TutorialState): void {
        this.persistState(state);
        this.renderMode();
        void this.loadRevisionSettings();
        void this.loadSteps();
    }

    /** Show the editor controls for the current authoring or selection mode. */
    private renderMode(): void {
        const panel = this.element;
        if (!panel) return;

        panel.hidden = this.state?.createMode !== true || !this.state.revisionId || this.preview !== null;
        const selecting = this.selection !== null;
        const content = panel.querySelector<HTMLElement>("[data-tutorial-content]");
        if (content) content.hidden = selecting;
        const picker = panel.querySelector<HTMLElement>("[data-tutorial-picker-controls]");
        if (picker) picker.hidden = !selecting;
        const previewButton = panel.querySelector<HTMLButtonElement>("[data-tutorial-preview-start]");
        if (previewButton) previewButton.hidden = selecting;
        this.repositionPanel();
        this.updateLearnerOffers(false);
    }
}
