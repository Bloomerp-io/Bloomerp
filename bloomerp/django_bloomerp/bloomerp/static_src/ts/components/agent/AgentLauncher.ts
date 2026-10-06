/** Keep the assistant launcher movable without treating a drag as an open action. */
export default class AgentLauncher {
    private pointerId: number | null = null;
    private startX = 0;
    private startY = 0;
    private startLeft = 0;
    private startTop = 0;
    private dragged = false;

    /** Restore the saved position and bind mouse, touch, and keyboard movement. */
    public constructor(
        private readonly button: HTMLButtonElement,
        private readonly storageKey: string,
        signal: AbortSignal,
    ) {
        this.restorePosition();
        button.addEventListener('pointerdown', this.onPointerDown, { signal });
        button.addEventListener('pointermove', this.onPointerMove, { signal });
        button.addEventListener('pointerup', this.onPointerEnd, { signal });
        button.addEventListener('pointercancel', this.onPointerEnd, { signal });
        button.addEventListener('lostpointercapture', this.onPointerEnd, { signal });
        button.addEventListener('click', this.onClick, { signal, capture: true });
        button.addEventListener('keydown', this.onKeyDown, { signal });
        window.addEventListener('resize', this.onResize, { signal });
        signal.addEventListener('abort', this.onAbort, { once: true });
    }

    /** Read a valid stored location, leaving the default corner untouched otherwise. */
    private restorePosition(): void {
        try {
            const position: unknown = JSON.parse(localStorage.getItem(this.storageKey) || 'null');
            if (typeof position !== 'object' || position === null) return;
            const { x, y } = position as { x?: unknown; y?: unknown };
            if (typeof x === 'number' && typeof y === 'number' && Number.isFinite(x) && Number.isFinite(y)) {
                this.setPosition(x, y);
            }
        } catch { /* Position storage is optional. */ }
    }

    /** Keep the whole orb inside the viewport with a small edge margin. */
    private setPosition(x: number, y: number): void {
        const size = this.button.offsetWidth || 48;
        const left = Math.min(Math.max(8, x), Math.max(8, window.innerWidth - size - 8));
        const top = Math.min(Math.max(8, y), Math.max(8, window.innerHeight - size - 8));
        this.button.style.left = `${left}px`;
        this.button.style.top = `${top}px`;
        this.button.style.right = 'auto';
        this.button.style.bottom = 'auto';
    }

    /** Persist a moved location independently from the current conversation. */
    private savePosition(): void {
        try {
            localStorage.setItem(this.storageKey, JSON.stringify({
                x: Number.parseFloat(this.button.style.left),
                y: Number.parseFloat(this.button.style.top),
            }));
        } catch { /* Movement remains available when storage is disabled. */ }
    }

    /** Capture a primary pointer while retaining normal click behavior until it moves. */
    private onPointerDown = (event: PointerEvent): void => {
        if (event.button !== 0 || !event.isPrimary || this.pointerId !== null) return;
        const bounds = this.button.getBoundingClientRect();
        this.pointerId = event.pointerId;
        this.startX = event.clientX;
        this.startY = event.clientY;
        this.startLeft = bounds.left;
        this.startTop = bounds.top;
        this.dragged = false;
        this.button.setPointerCapture(event.pointerId);
    };

    /** Begin dragging only after deliberate movement, then follow the captured pointer. */
    private onPointerMove = (event: PointerEvent): void => {
        if (event.pointerId !== this.pointerId) return;
        const dx = event.clientX - this.startX;
        const dy = event.clientY - this.startY;
        if (!this.dragged && Math.hypot(dx, dy) < 5) return;
        this.dragged = true;
        event.preventDefault();
        this.button.classList.add('is-dragging');
        this.setPosition(this.startLeft + dx, this.startTop + dy);
    };

    /** Finish the gesture and save deliberate moves without opening the assistant. */
    private onPointerEnd = (event: PointerEvent): void => {
        if (event.pointerId !== this.pointerId) return;
        this.releasePointer();
        if (this.dragged) this.savePosition();
    };

    /** Release capture and drag styling when a gesture ends or the owner is removed. */
    private releasePointer(): void {
        const pointerId = this.pointerId;
        this.pointerId = null;
        this.button.classList.remove('is-dragging');
        if (pointerId !== null && this.button.hasPointerCapture(pointerId)) {
            this.button.releasePointerCapture(pointerId);
        }
    }

    /** Suppress the pointer click generated after a drag while allowing keyboard activation. */
    private onClick = (event: MouseEvent): void => {
        if (!this.dragged || event.detail === 0) return;
        this.dragged = false;
        event.preventDefault();
        event.stopImmediatePropagation();
    };

    /** Allow focused arrow keys to move the orb, with Shift for larger steps. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
        event.preventDefault();
        event.stopPropagation();
        const bounds = this.button.getBoundingClientRect();
        const step = event.shiftKey ? 40 : 10;
        const dx = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0;
        const dy = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0;
        this.setPosition(bounds.left + dx, bounds.top + dy);
        this.savePosition();
    };

    /** Keep a saved location on screen when the viewport becomes smaller. */
    private onResize = (): void => {
        if (!this.button.style.left) return;
        this.setPosition(Number.parseFloat(this.button.style.left), Number.parseFloat(this.button.style.top));
    };

    /** Release an active pointer when the owning chat lifecycle ends. */
    private onAbort = (): void => {
        this.releasePointer();
    };
}
