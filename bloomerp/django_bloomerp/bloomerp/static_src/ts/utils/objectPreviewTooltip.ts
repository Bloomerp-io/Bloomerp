type ObjectPreviewTooltipOptions = {
    element: HTMLElement;
    objectId: string;
    contentTypeId: string;
};

type CleanupFn = () => void;

class ObjectPreviewTooltipManager {
    private readonly previewDelayMs = 1000;
    private tooltipEl: HTMLDivElement | null = null;
    private tooltipContentEl: HTMLDivElement | null = null;
    private showTimer: number | null = null;
    private hideTimer: number | null = null;
    private activePreviewKey: string | null = null;
    private loadedPreviewKey: string | null = null;
    private requestToken = 0;
    private hoveredAnchorKey: string | null = null;
    private isHoveringTooltip = false;

    public attach({ element, objectId, contentTypeId }: ObjectPreviewTooltipOptions): CleanupFn {
        const previewKey = this.getPreviewKey(contentTypeId, objectId);

        const onEnter = () => {
            this.hoveredAnchorKey = previewKey;
            this.scheduleShow(element, objectId, contentTypeId);
        };
        const onLeave = () => {
            if (this.hoveredAnchorKey === previewKey) {
                this.hoveredAnchorKey = null;
            }
            this.scheduleHide();
        };
        const onFocus = () => {
            this.hoveredAnchorKey = previewKey;
            this.scheduleShow(element, objectId, contentTypeId);
        };
        const onBlur = () => {
            if (this.hoveredAnchorKey === previewKey) {
                this.hoveredAnchorKey = null;
            }
            this.scheduleHide();
        };

        element.addEventListener("mouseenter", onEnter);
        element.addEventListener("mouseleave", onLeave);
        element.addEventListener("focus", onFocus);
        element.addEventListener("blur", onBlur);

        return () => {
            element.removeEventListener("mouseenter", onEnter);
            element.removeEventListener("mouseleave", onLeave);
            element.removeEventListener("focus", onFocus);
            element.removeEventListener("blur", onBlur);

            if (this.hoveredAnchorKey === previewKey) {
                this.hoveredAnchorKey = null;
                this.scheduleHide();
            }
        };
    }

    public hide(): void {
        this.clearTimers();
        this.activePreviewKey = null;
        this.hoveredAnchorKey = null;
        this.isHoveringTooltip = false;
        if (this.tooltipEl) {
            this.tooltipEl.classList.add("hidden");
        }
    }

    public destroy(): void {
        this.hide();
        this.tooltipEl?.remove();
        this.tooltipEl = null;
        this.tooltipContentEl = null;
    }

    private getPreviewKey(contentTypeId: string, objectId: string): string {
        return `${contentTypeId}:${objectId}`;
    }

    private scheduleShow(anchor: HTMLElement, objectId: string, contentTypeId: string): void {
        const previewKey = this.getPreviewKey(contentTypeId, objectId);
        const tooltipVisible = !!this.tooltipEl && !this.tooltipEl.classList.contains("hidden");
        if (this.activePreviewKey === previewKey && (this.showTimer !== null || tooltipVisible)) {
            return;
        }

        this.clearTimers();
        this.activePreviewKey = previewKey;
        this.showTimer = window.setTimeout(() => {
            this.showTimer = null;
            this.show(anchor, objectId, contentTypeId);
        }, this.previewDelayMs);
    }

    private async show(anchor: HTMLElement, objectId: string, contentTypeId: string): Promise<void> {
        if (this.hideTimer) {
            window.clearTimeout(this.hideTimer);
            this.hideTimer = null;
        }

        const previewKey = this.getPreviewKey(contentTypeId, objectId);
        const tooltip = this.ensureTooltip();
        this.activePreviewKey = previewKey;

        if (!tooltip.classList.contains("hidden") && this.loadedPreviewKey === previewKey) {
            this.positionTooltip(anchor);
            return;
        }

        this.setLoading();
        tooltip.classList.remove("hidden");
        this.positionTooltip(anchor);

        const requestToken = ++this.requestToken;
        const previewUrl = `/components/object-preview/${contentTypeId}/${encodeURIComponent(objectId)}/`;

        try {
            const response = await fetch(previewUrl, {
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });

            if (!response.ok) {
                throw new Error(`Preview request failed with status ${response.status}`);
            }

            const html = await response.text();
            if (requestToken !== this.requestToken || this.activePreviewKey !== previewKey) {
                return;
            }

            if (this.tooltipContentEl) {
                this.tooltipContentEl.innerHTML = html;
            }
            this.loadedPreviewKey = previewKey;
            this.positionTooltip(anchor);
        } catch (error) {
            if (requestToken !== this.requestToken || this.activePreviewKey !== previewKey) {
                return;
            }

            if (this.tooltipContentEl) {
                this.tooltipContentEl.innerHTML = '<div class="rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500 shadow-xl">Preview unavailable</div>';
            }
            this.positionTooltip(anchor);
            console.error("Object preview tooltip error", error);
        }
    }

    private ensureTooltip(): HTMLDivElement {
        if (this.tooltipEl && this.tooltipContentEl) {
            return this.tooltipEl;
        }

        const tooltip = document.createElement("div");
        tooltip.className = "foreign-field-preview-tooltip hidden fixed z-[120]";

        const content = document.createElement("div");
        content.className = "foreign-field-preview-tooltip-content";
        tooltip.appendChild(content);

        tooltip.addEventListener("mouseenter", () => {
            this.isHoveringTooltip = true;
            if (this.hideTimer) {
                window.clearTimeout(this.hideTimer);
                this.hideTimer = null;
            }
        });
        tooltip.addEventListener("mouseleave", () => {
            this.isHoveringTooltip = false;
            this.scheduleHide();
        });

        document.body.appendChild(tooltip);
        this.tooltipEl = tooltip;
        this.tooltipContentEl = content;
        return tooltip;
    }

    private setLoading(): void {
        if (!this.tooltipContentEl) return;
        this.tooltipContentEl.innerHTML = `
            <div class="w-[28rem] max-w-[min(28rem,calc(100vw-2rem))] rounded-2xl border border-gray-200 bg-white px-4 py-3 shadow-xl">
                <div class="space-y-2 animate-pulse">
                    <div class="h-4 w-2/3 rounded bg-gray-200"></div>
                    <div class="h-3 w-1/3 rounded bg-gray-100"></div>
                    <div class="mt-4 h-12 rounded bg-gray-100"></div>
                    <div class="h-12 rounded bg-gray-100"></div>
                </div>
            </div>
        `;
    }

    private positionTooltip(anchor: HTMLElement): void {
        if (!this.tooltipEl) return;

        const anchorRect = anchor.getBoundingClientRect();
        const tooltipRect = this.tooltipEl.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        let left = anchorRect.left + (anchorRect.width / 2) - (tooltipRect.width / 2);
        left = Math.max(12, Math.min(left, viewportWidth - tooltipRect.width - 12));

        let top = anchorRect.top - tooltipRect.height - 12;
        if (top < 12) {
            top = anchorRect.bottom + 12;
        }
        if (top + tooltipRect.height > viewportHeight - 12) {
            top = Math.max(12, viewportHeight - tooltipRect.height - 12);
        }

        this.tooltipEl.style.left = `${left}px`;
        this.tooltipEl.style.top = `${top}px`;
    }

    private scheduleHide(): void {
        if (this.showTimer) {
            window.clearTimeout(this.showTimer);
            this.showTimer = null;
        }
        if (this.hideTimer) {
            window.clearTimeout(this.hideTimer);
        }
        this.hideTimer = window.setTimeout(() => {
            if (this.hoveredAnchorKey || this.isHoveringTooltip) {
                this.hideTimer = null;
                return;
            }
            this.hide();
        }, 150);
    }

    private clearTimers(): void {
        if (this.showTimer) {
            window.clearTimeout(this.showTimer);
            this.showTimer = null;
        }
        if (this.hideTimer) {
            window.clearTimeout(this.hideTimer);
            this.hideTimer = null;
        }
    }
}

const objectPreviewTooltipManager = new ObjectPreviewTooltipManager();

export function attachObjectPreviewTooltip(options: ObjectPreviewTooltipOptions): CleanupFn {
    return objectPreviewTooltipManager.attach(options);
}

export function hideObjectPreviewTooltip(): void {
    objectPreviewTooltipManager.hide();
}
