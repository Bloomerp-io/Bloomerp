import type { BaseSelection } from "lexical";
import type { ContextMenuItem, ContextMenuSubmenu } from "@/utils/contextMenu";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import type { ActionGroup, ActionOption, ActionSurface, RegisteredAction } from "./actionRegistry";
import { t } from "@/utils/i18n";
import { promptColorSelection } from "./utils/colorPicker";

/** Present registry capabilities consistently in slash menus and toolbar dropdowns. */
export function createActionMenuItems(
    host: BloomerpTextEditor, entries: RegisteredAction[], source: ActionSurface, selection: BaseSelection | null,
): ContextMenuItem[] {
    /** Use the latest typed slash range while retaining snapshots for focus-taking toolbars. */
    function invocationSelection(): BaseSelection | null {
        return source === "slash" ? host.actionRegistry.captureSelection() ?? selection : selection;
    }
    const groups: readonly ActionGroup[] = ["block", "text", "list", "alignment", "table", "insert", "extension"];
    /** Keep each section contiguous while retaining action order within that section. */
    function compareGroups(left: RegisteredAction, right: RegisteredAction): number {
        return groups.indexOf(left.action.group ?? "extension") - groups.indexOf(right.action.group ?? "extension");
    }
    const ordered = [...entries].sort(compareGroups);
    const firstGroup = ordered[0]?.action.group;
    /** Build one menu entry with the same execution path as a toolbar button. */
    function entry(item: RegisteredAction): ContextMenuItem {
        const { id, action, state } = item;
        /** Execute against the range captured before menu focus moved. */
        function run(): void { host.actionRegistry.execute(id, source, invocationSelection()); }
        const result: ContextMenuItem = {
            label: action.label, icon: state.active ? "fa-solid fa-check" : action.icon,
            group: action.group === firstGroup ? undefined : groupLabel(action.group),
            disabled: state.disabled, onClick: run,
        };
        if (action.options) {
            /** Apply the chosen argument through the registered action. */
            function option(value: ActionOption): ContextMenuItem {
                /** Retain source and range while applying one allowed style value. */
                function apply(): void {
                    const target = invocationSelection();
                    /** Apply a custom value to the range saved before the color chooser took focus. */
                    function applyColor(color: string): void {
                        host.actionRegistry.execute(id, source, target, { value: color });
                        host.editor?.focus();
                    }
                    if (value.input === "color") promptColorSelection(host.element, value.value, applyColor);
                    else host.actionRegistry.execute(id, source, target, { value: value.value });
                }
                return { label: value.label, icon: value.input === "color" ? "fa-solid fa-palette" : undefined, onClick: apply };
            }
            result.submenu = { label: action.label, items: action.options.map(option) };
        } else if (action.submenu) {
            /** Restore selection before an existing reference or template picker captures it. */
            function submenu(): ContextMenuSubmenu {
                const definition = action.submenu!(host);
                /** Capture the right editor range even when submenu search takes keyboard focus. */
                function open(): void {
                    host.actionRegistry.restoreSelection(invocationSelection());
                    definition.onOpen?.();
                }
                return { ...definition, onOpen: open };
            }
            result.submenu = submenu;
        }
        return result;
    }
    return ordered.map(entry);
}

/** Present translated section names while keeping registry group identifiers internal. */
function groupLabel(group: import("./actionRegistry").ActionGroup | undefined): string | undefined {
    switch (group) {
        case "block": return t("Text style");
        case "text": return t("Text formatting");
        case "list": return t("Lists");
        case "alignment": return t("Alignment");
        case "table": return t("Table");
        case "insert": return t("Insert");
        case "extension": return t("Actions");
        default: return undefined;
    }
}
