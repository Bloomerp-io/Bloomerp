import BaseComponent from "./BaseComponent";
import {
    formatShortcutForDisplay,
    formatShortcutForAria,
    parseShortcut,
    type ShortcutDefinition,
} from "../utils/shortcuts";
import { getShortcutManager } from "../utils/shortcutManager";

type Action = "focus" | "click";
type Position = "top" | "bottom" | "left" | "right";
type FocusScope = "self" | "target" | "document";

type TooltipState = "hover" | "reveal";

const INTERACTIVE_SELECTOR = [
    "button",
    "a[href]",
    "input",
    "select",
    "textarea",
    "[role='button']",
    "[tabindex]:not([tabindex='-1'])",
].join(", ");

function isValidAction(value: string | undefined): value is Action {
    return value === "focus" || value === "click";
}

function isValidPosition(value: string | undefined): value is Position {
    return value === "top" || value === "bottom" || value === "left" || value === "right";
}

function createTooltipNode(text: string, shortcutLabel: string, position: Position): HTMLElement {
    const wrapper = document.createElement("div");
    wrapper.dataset.shortcutTooltip = "true";
    wrapper.setAttribute("aria-hidden", "true");
    wrapper.className = [
        "absolute",
        "z-50",
        "w-max",
        "max-w-72",
        "rounded-md",
        "border",
        "border-gray-200",
        "bg-white",
        "px-3",
        "py-2",
        "text-xs",
        "text-gray-800",
        "shadow-sm",
        "pointer-events-none",
        "opacity-0",
        "invisible",
        "transition-all",
        "duration-150",
    ].join(" ");

    switch (position) {
        case "bottom":
            wrapper.classList.add("top-full", "left-1/2", "mt-1", "-translate-x-1/2");
            break;
        case "left":
            wrapper.classList.add("right-full", "top-1/2", "mr-1", "-translate-y-1/2");
            break;
        case "right":
            wrapper.classList.add("left-full", "top-1/2", "ml-1", "-translate-y-1/2");
            break;
        case "top":
        default:
            wrapper.classList.add("bottom-full", "left-1/2", "mb-1", "-translate-x-1/2");
            break;
    }

    const row = document.createElement("div");
    row.className = "flex items-center gap-2";

    if (text.trim()) {
        const textNode = document.createElement("div");
        textNode.className = "whitespace-normal break-words text-left";
        textNode.textContent = text.trim();
        row.appendChild(textNode);
    }

    const shortcutNode = document.createElement("span");
    shortcutNode.className = "inline-flex shrink-0 items-center rounded border border-gray-300 bg-gray-50 px-1.5 py-0.5 font-medium text-gray-600";
    shortcutNode.textContent = shortcutLabel;
    row.appendChild(shortcutNode);

    wrapper.appendChild(row);

    const arrow = document.createElement("div");
    arrow.className = "absolute h-2 w-2 rotate-45 border-gray-200 bg-white";

    switch (position) {
        case "bottom":
            arrow.classList.add("left-1/2", "top-0", "-translate-x-1/2", "-translate-y-1/2", "border-t", "border-l");
            break;
        case "left":
            arrow.classList.add("right-0", "top-1/2", "translate-x-1/2", "-translate-y-1/2", "border-t", "border-r");
            break;
        case "right":
            arrow.classList.add("left-0", "top-1/2", "-translate-x-1/2", "-translate-y-1/2", "border-b", "border-l");
            break;
        case "top":
        default:
            arrow.classList.add("bottom-0", "left-1/2", "-translate-x-1/2", "translate-y-1/2", "border-b", "border-r");
            break;
    }

    wrapper.appendChild(arrow);

    return wrapper;
}

export default class ShortcutTooltip extends BaseComponent {
    private action: Action = "click";
    private shortcut: string = "";
    private targetSelector: string = "";
    private focusTargetSelector: string = "";
    private focusScope: string = "self";
    private shortcutDefinition: ShortcutDefinition | null = null;
    private text: string = "";
    private position: Position = "top";
    private tooltipNode: HTMLElement | null = null;
    private targetElement: HTMLElement | null = null;
    private unregisterShortcut: (() => void) | null = null;
    private hoverHandler: (() => void) | null = null;
    private leaveHandler: (() => void) | null = null;
    private focusInHandler: (() => void) | null = null;
    private focusOutHandler: ((event: FocusEvent) => void) | null = null;
    private hoverVisible = false;
    private revealVisible = false;

    public initialize(): void {
        if (!this.element) return;

        this.action = isValidAction(this.element.dataset.action) ? this.element.dataset.action : "click";
        this.shortcut = (this.element.dataset.shortcut || "").trim();
        this.targetSelector = (this.element.dataset.target || "").trim();
        this.focusTargetSelector = (this.element.dataset.focusTarget || "").trim();
        this.focusScope = (this.element.dataset.focusScope || "self").trim();
        this.text = (this.element.dataset.text || "").trim();
        this.position = isValidPosition(this.element.dataset.position) ? this.element.dataset.position : "top";
        this.shortcutDefinition = parseShortcut(this.shortcut);

        if (!this.shortcutDefinition) {
            console.warn("Invalid shortcut definition:", this.shortcut, this.element);
            return;
        }

        this.targetElement = this.getInsideElement();
        if (!this.targetElement) {
            console.warn("Shortcut tooltip requires an interactive child element:", this.element);
            return;
        }

        this.element.classList.add("relative");
        this.targetElement.setAttribute("aria-keyshortcuts", formatShortcutForAria(this.shortcutDefinition));

        this.tooltipNode = createTooltipNode(
            this.text,
            formatShortcutForDisplay(this.shortcutDefinition),
            this.position,
        );
        this.element.appendChild(this.tooltipNode);

        this.hoverHandler = () => this.setTooltipState("hover", true);
        this.leaveHandler = () => this.setTooltipState("hover", false);
        this.focusInHandler = () => this.setTooltipState("hover", true);
        this.focusOutHandler = (event: FocusEvent) => {
            const nextTarget = event.relatedTarget as Node | null;
            if (nextTarget && this.element?.contains(nextTarget)) return;
            this.setTooltipState("hover", false);
        };

        this.element.addEventListener("mouseenter", this.hoverHandler);
        this.element.addEventListener("mouseleave", this.leaveHandler);
        this.element.addEventListener("focusin", this.focusInHandler);
        this.element.addEventListener("focusout", this.focusOutHandler);

        this.unregisterShortcut = getShortcutManager().register({
            rootElement: this.element,
            shortcut: this.shortcutDefinition,
            showHint: () => this.setTooltipState("reveal", true),
            hideHint: () => this.setTooltipState("reveal", false),
            performAction: () => this.performAction(),
        });
    }

    public destroy(): void {
        this.unregisterShortcut?.();
        this.unregisterShortcut = null;

        if (this.hoverHandler) {
            this.element?.removeEventListener("mouseenter", this.hoverHandler);
        }
        if (this.leaveHandler) {
            this.element?.removeEventListener("mouseleave", this.leaveHandler);
        }
        if (this.focusInHandler) {
            this.element?.removeEventListener("focusin", this.focusInHandler);
        }
        if (this.focusOutHandler) {
            this.element?.removeEventListener("focusout", this.focusOutHandler);
        }

        this.tooltipNode?.remove();
        this.tooltipNode = null;

        super.destroy();
    }

    private setTooltipState(state: TooltipState, visible: boolean): void {
        if (!this.tooltipNode) return;

        if (state === "hover") {
            this.hoverVisible = visible;
        } else {
            this.revealVisible = visible;
        }

        const shouldShow = this.hoverVisible || this.revealVisible;
        this.tooltipNode.classList.toggle("opacity-0", !shouldShow);
        this.tooltipNode.classList.toggle("invisible", !shouldShow);
        this.tooltipNode.classList.toggle("opacity-100", shouldShow);
        this.tooltipNode.classList.toggle("visible", shouldShow);
    }

    private getInsideElement(): HTMLElement | null {
        if (!this.element) return null;

        if (this.targetSelector) {
            const explicitTarget = this.element.querySelector<HTMLElement>(this.targetSelector);
            if (explicitTarget) return explicitTarget;

            console.warn("Shortcut tooltip target selector did not match any descendant:", this.targetSelector, this.element);
        }

        const interactiveChild = this.element.querySelector<HTMLElement>(INTERACTIVE_SELECTOR);
        if (interactiveChild) return interactiveChild;

        return this.element.firstElementChild instanceof HTMLElement ? this.element.firstElementChild : this.element;
    }

    private performAction(): void {
        const target = this.getInsideElement();
        if (!target || !this.isActionable(target)) return;

        if (this.action === "focus") {
            target.focus();
        } else if (this.action === "click") {
            target.click();
        }

        this.focusRequestedTarget(target);
    }

    private isActionable(element: HTMLElement): boolean {
        if (!element.isConnected) return false;
        if (element.hasAttribute("disabled") || element.getAttribute("aria-disabled") === "true") return false;

        const style = window.getComputedStyle(element);
        return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
    }

    private focusRequestedTarget(actionTarget: HTMLElement): void {
        if (!this.focusTargetSelector) return;

        let attemptsRemaining = 12;

        const tryFocus = () => {
            const focusTarget = this.resolveFocusTarget(actionTarget);
            if (focusTarget && this.isFocusable(focusTarget) && this.isActionable(focusTarget)) {
                focusTarget.focus();
                if (document.activeElement === focusTarget) {
                    return;
                }
            }

            attemptsRemaining -= 1;
            if (attemptsRemaining <= 0) return;

            window.requestAnimationFrame(tryFocus);
        };

        window.requestAnimationFrame(tryFocus);
    }

    private resolveFocusTarget(actionTarget: HTMLElement): HTMLElement | null {
        const scope = this.resolveFocusScope(actionTarget);
        if (!scope) return null;

        return scope.querySelector<HTMLElement>(this.focusTargetSelector);
    }

    private resolveFocusScope(actionTarget: HTMLElement): ParentNode | null {
        if (!this.element) return null;

        if (this.focusScope === "document") {
            return document;
        }

        if (this.focusScope === "target") {
            return actionTarget;
        }

        if (this.focusScope === "self") {
            return this.element;
        }

        const explicitScope = document.querySelector<HTMLElement>(this.focusScope);
        if (explicitScope) return explicitScope;

        console.warn("Shortcut tooltip focus scope selector did not match any element:", this.focusScope, this.element);
        return null;
    }

    private isFocusable(element: HTMLElement): boolean {
        if (typeof element.focus !== "function") return false;
        if (element.tabIndex >= 0) return true;

        return /^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(element.tagName);
    }
}
