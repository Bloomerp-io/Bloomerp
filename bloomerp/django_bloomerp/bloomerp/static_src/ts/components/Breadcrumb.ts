import BaseComponent from "./BaseComponent";
import { getCookie, setCookie } from "../utils/cookies";

const BREADCRUMB_STATE_COOKIE = "bloomerp_breadcrumb_expanded";
const ANIMATION_DURATION_MS = 220;
const STAGGER_MS = 45;

export default class Breadcrumb extends BaseComponent {
    private toggleButton: HTMLButtonElement | null = null;
    private collapsedItems: HTMLElement[] = [];
    private clickHandler: (() => void) | null = null;
    private expanded = false;

    public initialize(): void {
        if (!this.element) return;

        this.toggleButton = this.element.querySelector<HTMLButtonElement>("[data-breadcrumb-toggle]");
        this.collapsedItems = Array.from(this.element.querySelectorAll<HTMLElement>("[data-breadcrumb-collapsed-item]"));

        if (!this.toggleButton || !this.collapsedItems.length) return;

        this.clickHandler = () => this.toggle();
        this.toggleButton.addEventListener("click", this.clickHandler);
        this.setExpanded(getCookie(BREADCRUMB_STATE_COOKIE) === "true", false);
    }

    public destroy(): void {
        if (this.toggleButton && this.clickHandler) {
            this.toggleButton.removeEventListener("click", this.clickHandler);
        }

        this.toggleButton = null;
        this.collapsedItems = [];
        this.clickHandler = null;
        super.destroy();
    }

    private toggle(): void {
        this.setExpanded(!this.expanded, true);
    }

    private setExpanded(expanded: boolean, animate: boolean): void {
        if (this.expanded === expanded && animate) return;

        this.expanded = expanded;
        setCookie(BREADCRUMB_STATE_COOKIE, expanded ? "true" : "false", 30);
        this.updateToggleButton();

        if (expanded) {
            this.showItems(animate);
            return;
        }

        this.hideItems(animate);
    }

    private showItems(animate: boolean): void {
        this.collapsedItems.forEach((item, index) => {
            const reveal = () => {
                item.setAttribute("aria-hidden", "false");
                item.classList.remove("opacity-0", "scale-95", "-translate-x-1", "pointer-events-none");
                item.classList.add("opacity-100", "scale-100", "translate-x-0");

                if (!animate) {
                    this.withoutTransition(item, () => {
                        item.style.width = "auto";
                    });
                    return;
                }

                item.style.width = `${item.scrollWidth}px`;

                window.setTimeout(() => {
                    if (this.expanded) {
                        item.style.width = "auto";
                    }
                }, ANIMATION_DURATION_MS);
            };

            if (animate) {
                window.setTimeout(reveal, index * STAGGER_MS);
                return;
            }

            reveal();
        });
    }

    private hideItems(animate: boolean): void {
        const items = [...this.collapsedItems].reverse();

        items.forEach((item, index) => {
            const hide = () => {
                item.setAttribute("aria-hidden", "true");

                if (!animate) {
                    this.withoutTransition(item, () => {
                        this.applyHiddenState(item);
                    });
                    return;
                }

                item.style.width = `${item.scrollWidth}px`;

                window.requestAnimationFrame(() => {
                    this.applyHiddenState(item);
                });
            };

            if (animate) {
                window.setTimeout(hide, index * STAGGER_MS);
                return;
            }

            hide();
        });
    }

    private applyHiddenState(item: HTMLElement): void {
        item.classList.add("opacity-0", "scale-95", "-translate-x-1", "pointer-events-none");
        item.classList.remove("opacity-100", "scale-100", "translate-x-0");
        item.style.width = "0px";
    }

    private updateToggleButton(): void {
        if (!this.toggleButton) return;

        this.toggleButton.setAttribute("aria-expanded", this.expanded ? "true" : "false");
        this.toggleButton.setAttribute(
            "aria-label",
            this.expanded ? "Hide breadcrumb path" : "Show breadcrumb path",
        );
        this.toggleButton.classList.toggle("bg-gray-100", this.expanded);
        this.toggleButton.classList.toggle("text-primary-600", this.expanded);
    }

    private withoutTransition(item: HTMLElement, callback: () => void): void {
        const previousTransition = item.style.transition;
        item.style.transition = "none";
        callback();
        item.offsetHeight;
        item.style.transition = previousTransition;
    }
}
