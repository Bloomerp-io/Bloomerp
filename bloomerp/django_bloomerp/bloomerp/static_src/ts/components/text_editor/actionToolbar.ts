import type { BaseSelection } from "lexical";
import { $isTableSelection } from "@lexical/table";
import { getContextMenu, type ContextMenuController } from "@/utils/contextMenu";
import { t } from "@/utils/i18n";
import { addTooltip } from "@/utils/tooltip";
import { formatShortcutForAria, formatShortcutForDisplay, parseShortcut } from "@/utils/shortcuts";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import type { ActionGroup, ActionSurface, RegisteredAction } from "./actionRegistry";
import { createActionMenuItems } from "./actionMenu";
import "./actionToolbar.css";

type ActionToolbarButton = { element: HTMLButtonElement; destroy: () => void };

/** Create consistent toolbar markup and an owned top tooltip for actions and visibility controls. */
export function createActionToolbarButton(label: string, icon: string, shortcuts: readonly string[] = []): ActionToolbarButton {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-editor-action-button";
    button.dataset.actionControl = "true";
    button.setAttribute("aria-label", label);
    const image = document.createElement("i");
    image.className = icon;
    image.setAttribute("aria-hidden", "true");
    button.appendChild(image);
    const definitions = shortcuts.map(parseShortcut).filter(isShortcut);
    const hint = definitions.map(formatShortcutForDisplay).join(", ");
    if (definitions.length) button.setAttribute("aria-keyshortcuts", definitions.map(formatShortcutForAria).join(" "));
    const destroy = addTooltip(button, {
        title: hint ? label : undefined, text: hint || label, position: "top", portal: true,
    });
    return { element: button, destroy };
}

/** Render a fixed or floating toolbar from the same registry metadata and state. */
export class ActionToolbar {
    public readonly element = document.createElement("div");
    private readonly lifecycle = new AbortController();
    private readonly menu: ContextMenuController;
    private readonly unsubscribe: () => void;
    private tooltipCleanups: Array<() => void> = [];
    private readonly trailingControls: HTMLElement[] = [];
    private renderedSignature = "";

    /** Connect toolbar controls without allowing mouse focus to discard the editor range. */
    public constructor(
        private readonly host: BloomerpTextEditor,
        private readonly source: Extract<ActionSurface, "toolbar" | "selection">,
        private readonly selection: () => BaseSelection | null,
    ) {
        this.element.className = "text-editor-action-toolbar";
        this.element.setAttribute("role", "toolbar");
        this.element.setAttribute("aria-label", source === "selection" ? t("Selection formatting") : t("Text formatting"));
        this.menu = getContextMenu(`editor-actions-${host.element.dataset.editorId}-${source}`);
        if (source === "selection") this.element.appendChild(this.menu.element);
        this.element.addEventListener("mousedown", this.preserveSelection, { signal: this.lifecycle.signal });
        this.element.addEventListener("click", this.onClick, { signal: this.lifecycle.signal });
        this.unsubscribe = host.actionRegistry.subscribe(this.render.bind(this));
        this.render();
    }

    /** Rebuild controls only when capabilities change, then refresh their selected state. */
    public render(): void {
        this.clearTooltips();
        this.element.querySelectorAll("[data-action-control]").forEach(removeControl);
        const entries = this.entries();
        this.renderedSignature = entries.map(actionId).join(",");
        const groups: Array<[ActionGroup, string, string]> = [
            ["block", t("Text style"), "fa-solid fa-font"], ["list", t("Lists"), "fa-solid fa-list-ul"],
            ["alignment", t("Alignment"), "fa-solid fa-align-left"],
        ];
        this.addGroup(...groups[0], entries);
        for (const entry of entries) {
            if (entry.action.group === "text") this.addAction(entry);
        }
        this.addGroup(...groups[1], entries);
        this.addGroup(...groups[2], entries);
        for (const entry of entries) {
            if (!entry.action.group || ["table", "insert", "extension"].includes(entry.action.group)) this.addAction(entry);
        }
        this.element.append(...this.trailingControls);
        this.refresh();
    }

    /** Keep an externally owned control in the action row across registry updates. */
    public appendControl(control: HTMLElement): void {
        this.trailingControls.push(control);
        this.element.appendChild(control);
    }

    /** Update toggle and capability state without replacing focused toolbar controls. */
    public refresh(): void {
        const entries = this.entries();
        if (entries.map(actionId).join(",") !== this.renderedSignature) { this.render(); return; }
        for (const entry of entries) {
            const button = this.element.querySelector<HTMLButtonElement>(`[data-editor-action="${entry.id}"]`);
            if (!button) continue;
            button.disabled = Boolean(entry.state.disabled);
            button.setAttribute("aria-pressed", entry.state.mixed ? "mixed" : String(Boolean(entry.state.active)));
        }
        for (const button of this.element.querySelectorAll<HTMLButtonElement>("[data-editor-action-group]")) {
            const group = entries.filter(matchesGroup);
            /** Match this dropdown's registry action group. */
            function matchesGroup(entry: RegisteredAction): boolean { return entry.action.group === button.dataset.editorActionGroup; }
            button.disabled = group.every(isDisabled);
        }
    }

    /** Use cell transformations for rectangular selections and text actions for ordinary ranges. */
    private entries(): RegisteredAction[] {
        const selection = this.selection();
        const entries = this.host.actionRegistry.list(this.source, selection);
        if (this.source !== "selection" || !$isTableSelection(selection)) return entries;
        /** Keep cell selection controls focused on supported structural operations. */
        function isTableAction(entry: RegisteredAction): boolean { return entry.action.group === "table"; }
        return entries.filter(isTableAction);
    }

    /** Close dropdowns when the selection toolbar is dismissed. */
    public closeMenu(): void { this.menu.hide(); }

    /** Release listeners and this toolbar's private dropdown. */
    public destroy(): void {
        this.lifecycle.abort();
        this.unsubscribe();
        this.clearTooltips();
        this.menu.destroy();
        this.element.remove();
    }

    /** Create an accessible icon button with a discoverable command label. */
    private button(label: string, icon: string, shortcuts: readonly string[] = []): HTMLButtonElement {
        const control = createActionToolbarButton(label, icon, shortcuts);
        this.tooltipCleanups.push(control.destroy);
        return control.element;
    }

    /** Add an inline action or a dropdown backed by its registered arguments. */
    private addAction(entry: RegisteredAction): void {
        const button = this.button(entry.action.label, entry.action.icon, entry.action.shortcuts);
        button.dataset.editorAction = entry.id;
        if (entry.action.options || entry.action.submenu) button.setAttribute("aria-haspopup", "menu");
        if (entry.action.group === "table" || this.source === "toolbar" && (!entry.action.group || ["insert", "extension"].includes(entry.action.group))) {
            button.append(document.createTextNode(` ${entry.action.label}`));
        }
        button.disabled = Boolean(entry.state.disabled);
        button.setAttribute("aria-pressed", entry.state.mixed ? "mixed" : String(Boolean(entry.state.active)));
        this.element.appendChild(button);
    }

    /** Remove portaled hints before controls are rebuilt or the editor is destroyed. */
    private clearTooltips(): void {
        for (const cleanup of this.tooltipCleanups) cleanup();
        this.tooltipCleanups = [];
    }

    /** Group block, list, and layout commands without duplicating their implementation. */
    private addGroup(group: ActionGroup, label: string, icon: string, entries: RegisteredAction[]): void {
        if (!entries.some(matches)) return;
        /** Include this dropdown only when its editor exposes a matching capability. */
        function matches(entry: RegisteredAction): boolean { return entry.action.group === group; }
        const button = this.button(label, icon);
        button.dataset.editorActionGroup = group;
        button.setAttribute("aria-haspopup", "menu");
        const chevron = document.createElement("i");
        chevron.className = "fa-solid fa-chevron-down text-[9px]";
        chevron.setAttribute("aria-hidden", "true");
        button.appendChild(chevron);
        this.element.appendChild(button);
    }

    /** Keep native selection on pointer interaction; keyboard focus remains available. */
    private preserveSelection = (event: MouseEvent): void => {
        if ((event.target as Element).closest("button[data-action-control]")) event.preventDefault();
    };

    /** Dispatch toolbar buttons and dropdown options through the same action registry. */
    private onClick = (event: MouseEvent): void => {
        const button = (event.target as Element).closest<HTMLButtonElement>("button[data-action-control]");
        if (!button || button.disabled) return;
        if (!button.dataset.editorAction && !button.dataset.editorActionGroup) return;
        // An external builder toolbar must not immediately dismiss the picker it opens.
        event.preventDefault();
        event.stopPropagation();
        const selection = this.selection() ?? this.host.actionRegistry.captureSelection();
        const entries = this.host.actionRegistry.list(this.source, selection);
        const group = button.dataset.editorActionGroup;
        const entry = entries.find(matchesId);
        /** Identify the scoped command represented by this button. */
        function matchesId(item: RegisteredAction): boolean { return item.id === button!.dataset.editorAction; }
        if (!group && entry && !entry.action.options && !entry.action.submenu) {
            this.host.actionRegistry.execute(entry.id, this.source, selection);
            return;
        }
        const selected = entries.filter(matches);
        /** Populate this dropdown from the registry rather than another hardcoded command list. */
        function matches(item: RegisteredAction): boolean { return group ? item.action.group === group : item.id === entry?.id; }
        let items = createActionMenuItems(this.host, selected, this.source, selection);
        if (!group && entry?.action.options) {
            const submenu = items[0]?.submenu;
            if (typeof submenu === "object") items = submenu.items ?? [];
        } else if (!group && entry?.action.submenu) {
            const submenu = items[0]?.submenu;
            if (submenu) {
                this.menu.hide();
                this.menu.showSubmenu(typeof submenu === "function" ? submenu() : submenu, button);
            }
            return;
        }
        this.menu.show(event, button, items);
    };
}

/** Remove an old control while retaining the toolbar's owned dropdown element. */
function removeControl(element: Element): void { element.remove(); }
/** Track visible capabilities so contextual actions appear as selection changes. */
function actionId(entry: RegisteredAction): string { return entry.id; }
/** Identify commands disabled for the current range. */
function isDisabled(entry: RegisteredAction): boolean { return Boolean(entry.state.disabled); }
/** Keep only parsed shortcuts when describing the registry's keyboard commands. */
function isShortcut(shortcut: import("@/utils/shortcuts").ShortcutDefinition | null): shortcut is import("@/utils/shortcuts").ShortcutDefinition { return shortcut !== null; }
