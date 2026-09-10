import DrawFlow from 'drawflow';
import { getItemNavigationKey } from '@/utils/itemNavigation';

export interface EdgeSelection {
    fromNodeId: string;
    toNodeId: string;
    outputClass: string;
    inputClass: string;
}

export function edgeKey(edge: EdgeSelection): string {
    return `${edge.fromNodeId}:${edge.outputClass}->${edge.toNodeId}:${edge.inputClass}`;
}

export function edgeFromElement(element: Element): EdgeSelection | null {
    const classes = [...element.classList];
    const from = classes.find(value => value.startsWith('node_out_node-'));
    const to = classes.find(value => value.startsWith('node_in_node-'));
    if (!from || !to) return null;
    return {
        fromNodeId: from.replace('node_out_node-', ''),
        toNodeId: to.replace('node_in_node-', ''),
        outputClass: classes.find(value => value.startsWith('output_')) || 'output_1',
        inputClass: classes.find(value => value.startsWith('input_')) || 'input_1',
    };
}

interface SelectionActions {
    changed(): void;
    renameNode(id: number): void;
    renameEdge(edge: EdgeSelection): void;
    copy(ids: number[]): unknown;
    paste(snapshot: unknown, offset: number): number[];
    zoom(delta: number): void;
}

/** Owns canvas input; Drawflow continues to own drawing and connecting ports. */
export default class WorkflowSelection {
    private enabled = true;
    private nodes = new Set<number>();
    private edges = new Map<string, EdgeSelection>();
    private anchor: number | null = null;
    private clipboard: unknown = null;
    private pasteCount = 0;
    private events = new AbortController();
    private drag: { x: number; y: number; moving: boolean; moved: boolean } | null = null;
    private marquee: HTMLDivElement;
    private selectionBeforeDrag = { nodes: new Set<number>(), edges: new Map<string, EdgeSelection>() };

    constructor(private root: HTMLElement, private canvas: HTMLElement, private editor: DrawFlow, private actions: SelectionActions) {
        this.marquee = document.createElement('div');
        this.marquee.className = 'workflow-selection-box';
        this.marquee.hidden = true;
        canvas.append(this.marquee);
        canvas.tabIndex = 0;
        canvas.setAttribute('aria-label', 'Workflow canvas');
        const signal = this.events.signal;
        canvas.addEventListener('mousedown', this.onMouseDown, { capture: true, signal });
        window.addEventListener('mousemove', this.onMouseMove, { signal });
        window.addEventListener('mouseup', this.onMouseUp, { signal });
        window.addEventListener('blur', this.onMouseUp, { signal });
        canvas.addEventListener('keydown', this.onKeyDown, { capture: true, signal });
        canvas.addEventListener('wheel', this.onWheel, { capture: true, passive: false, signal });
        canvas.addEventListener('contextmenu', this.onContextMenu, { capture: true, signal });
        root.querySelector('[data-selection-delete]')?.addEventListener('click', () => this.deleteSelection(), { signal });
        root.querySelector('[data-selection-rename]')?.addEventListener('click', () => this.rename(), { signal });
        root.querySelector('[data-selection-duplicate]')?.addEventListener('click', () => {
            if (this.nodes.size) this.selectNodes(this.actions.paste(this.actions.copy([...this.nodes]), 40));
        }, { signal });
        this.render();
    }

    destroy(): void {
        this.events.abort();
        this.marquee.remove();
    }

    setEnabled(enabled: boolean): void {
        this.enabled = enabled;
        if (!enabled) {
            this.clear();
            this.drag = null;
            this.marquee.hidden = true;
        }
        this.render();
    }

    private isEditing(target: EventTarget | null): boolean {
        return target instanceof Element && !!target.closest('input, textarea, select, [contenteditable="true"]');
    }

    private selectedEdge(target: Element): EdgeSelection | null {
        const label = target.closest<HTMLElement>('[data-workflow-edge-label]');
        if (label) return {
            fromNodeId: label.dataset.fromNodeId!, toNodeId: label.dataset.toNodeId!,
            outputClass: label.dataset.outputClass!, inputClass: label.dataset.inputClass!,
        };
        const connection = target.closest('.connection');
        return connection ? edgeFromElement(connection) : null;
    }

    private onMouseDown = (event: MouseEvent): void => {
        if (!this.enabled) return;
        if (event.button !== 0 || this.isEditing(event.target)) return;
        const target = event.target as Element;
        if (target.closest('.input, .output')) return;
        // Suppress Drawflow's single selection and empty-space mouse panning.
        event.preventDefault();
        event.stopImmediatePropagation();
        this.canvas.focus({ preventScroll: true });
        const node = target.closest<HTMLElement>('.drawflow-node');
        const edge = this.selectedEdge(target);
        if (node) {
            const id = Number(node.id.replace('node-', ''));
            if (event.shiftKey && this.nodes.has(id)) this.nodes.delete(id);
            else {
                if (!event.shiftKey && !this.nodes.has(id)) this.clear();
                this.nodes.add(id);
                this.anchor = id;
            }
        } else if (edge) {
            const key = edgeKey(edge);
            if (!event.shiftKey) this.clear();
            if (event.shiftKey && this.edges.has(key)) this.edges.delete(key);
            else this.edges.set(key, edge);
        } else {
            if (!event.shiftKey) this.clear();
            this.selectionBeforeDrag = { nodes: new Set(this.nodes), edges: new Map(this.edges) };
        }
        if (!edge) this.drag = { x: event.clientX, y: event.clientY, moving: !!node, moved: false };
        this.render();
    };

    private onMouseMove = (event: MouseEvent): void => {
        if (!this.enabled) return;
        if (!this.drag) return;
        const dx = event.clientX - this.drag.x;
        const dy = event.clientY - this.drag.y;
        if (!this.drag.moved && Math.hypot(dx, dy) < 3) return;
        this.drag.moved = true;
        if (this.drag.moving) {
            this.moveNodes(dx / this.editor.zoom, dy / this.editor.zoom);
            this.drag.x = event.clientX;
            this.drag.y = event.clientY;
            return;
        }
        const bounds = this.canvas.getBoundingClientRect();
        const left = Math.max(bounds.left, Math.min(this.drag.x, event.clientX));
        const top = Math.max(bounds.top, Math.min(this.drag.y, event.clientY));
        const right = Math.min(bounds.right, Math.max(this.drag.x, event.clientX));
        const bottom = Math.min(bounds.bottom, Math.max(this.drag.y, event.clientY));
        this.marquee.hidden = false;
        Object.assign(this.marquee.style, { left: `${left - bounds.left}px`, top: `${top - bounds.top}px`, width: `${right - left}px`, height: `${bottom - top}px` });
        this.nodes = new Set(this.selectionBeforeDrag.nodes);
        this.edges = new Map(this.selectionBeforeDrag.edges);
        const intersects = (rect: DOMRect) => rect.right >= left && rect.left <= right && rect.bottom >= top && rect.top <= bottom;
        this.canvas.querySelectorAll<HTMLElement>('.drawflow-node').forEach(node => {
            if (intersects(node.getBoundingClientRect())) this.nodes.add(Number(node.id.replace('node-', '')));
        });
        this.canvas.querySelectorAll<SVGPathElement>('.connection .main-path').forEach(path => {
            if (!intersects(path.getBoundingClientRect())) return;
            // Sample the actual curve, rather than selecting its entire bounding box.
            const matrix = path.getScreenCTM();
            if (!matrix) return;
            const length = path.getTotalLength();
            const steps = Math.max(20, Math.ceil(length * this.editor.zoom / 4));
            for (let step = 0; step <= steps; step++) {
                const point = path.getPointAtLength(length * step / steps).matrixTransform(matrix);
                if (point.x >= left && point.x <= right && point.y >= top && point.y <= bottom) {
                    const edge = edgeFromElement(path.closest('.connection')!);
                    if (edge) this.edges.set(edgeKey(edge), edge);
                    break;
                }
            }
        });
        this.anchor = [...this.nodes].at(-1) ?? null;
        this.render();
    };

    private onMouseUp = (): void => {
        if (this.drag?.moving && this.drag.moved) this.actions.changed();
        this.drag = null;
        this.marquee.hidden = true;
    };

    private moveNodes(dx: number, dy: number): void {
        for (const id of this.nodes) {
            const node = this.editor.drawflow.drawflow.Home.data[id];
            const element = this.canvas.querySelector<HTMLElement>(`#node-${id}`);
            if (!node || !element) continue;
            node.pos_x += dx;
            node.pos_y += dy;
            element.style.left = `${node.pos_x}px`;
            element.style.top = `${node.pos_y}px`;
            this.editor.updateConnectionNodes(`node-${id}`);
        }
        this.actions.changed();
    }

    private onContextMenu = (event: MouseEvent): void => {
        if (!this.enabled) return;
        if (this.isEditing(event.target)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        const target = event.target as Element;
        const node = target.closest<HTMLElement>('.drawflow-node');
        const edge = this.selectedEdge(target);
        if (node) this.selectNodes([Number(node.id.replace('node-', ''))], false);
        else if (edge) { this.clear(); this.edges.set(edgeKey(edge), edge); this.render(); }
        else return;
        this.rename();
    };

    private rename(): void {
        if (this.nodes.size + this.edges.size !== 1) return;
        if (this.nodes.size) this.actions.renameNode([...this.nodes][0]);
        else this.actions.renameEdge([...this.edges.values()][0]);
    }

    private deleteSelection(): void {
        for (const edge of this.edges.values()) {
            this.editor.removeSingleConnection(edge.fromNodeId, edge.toNodeId, edge.outputClass, edge.inputClass);
        }
        for (const id of this.nodes) this.editor.removeNodeId(`node-${id}`);
        this.clear();
        this.render();
        this.actions.changed();
        this.canvas.focus({ preventScroll: true });
    }

    private clear(): void {
        this.nodes.clear();
        this.edges.clear();
        this.anchor = null;
    }

    private selectNodes(ids: number[], includeEdges = true): void {
        this.clear();
        this.nodes = new Set(ids);
        this.anchor = ids.at(-1) ?? null;
        if (includeEdges) this.selectInternalEdges();
        this.render();
        this.canvas.focus({ preventScroll: true });
    }

    private selectInternalEdges(): void {
        this.canvas.querySelectorAll('.connection').forEach(element => {
            const edge = edgeFromElement(element);
            if (edge && this.nodes.has(Number(edge.fromNodeId)) && this.nodes.has(Number(edge.toNodeId))) this.edges.set(edgeKey(edge), edge);
        });
    }

    private navigate(key: string, extend: boolean): void {
        const nodes = [...this.canvas.querySelectorAll<HTMLElement>('.drawflow-node')];
        const current = nodes.find(node => node.id === `node-${this.anchor}`);
        const origin = current?.getBoundingClientRect() || this.canvas.getBoundingClientRect();
        const horizontal = key === 'ArrowLeft' || key === 'ArrowRight';
        const direction = key === 'ArrowLeft' || key === 'ArrowUp' ? -1 : 1;
        const candidates = nodes.filter(node => node !== current).map(node => {
            const rect = node.getBoundingClientRect();
            const dx = rect.x + rect.width / 2 - (origin.x + origin.width / 2);
            const dy = rect.y + rect.height / 2 - (origin.y + origin.height / 2);
            return { node, forward: (horizontal ? dx : dy) * direction, distance: Math.hypot(dx, dy) };
        }).filter(candidate => !current || candidate.forward > 1).sort((a, b) => a.distance - b.distance);
        const next = candidates[0]?.node;
        if (!next) return;
        if (!extend) this.clear();
        this.anchor = Number(next.id.replace('node-', ''));
        this.nodes.add(this.anchor);
        if (extend) this.selectInternalEdges();
        this.render();
        const rect = next.getBoundingClientRect();
        const viewport = this.canvas.getBoundingClientRect();
        if (rect.left < viewport.left || rect.right > viewport.right || rect.top < viewport.top || rect.bottom > viewport.bottom) {
            this.pan(viewport.x + viewport.width / 2 - rect.x - rect.width / 2, viewport.y + viewport.height / 2 - rect.y - rect.height / 2);
        }
    }

    private onKeyDown = (event: KeyboardEvent): void => {
        if (!this.enabled) return;
        if (this.isEditing(event.target) || event.isComposing) return;
        const navigation = getItemNavigationKey(event);
        const command = (event.metaKey || event.ctrlKey) && !event.altKey;
        let handled = true;
        if (navigation) this.navigate(navigation, event.shiftKey);
        else if (event.key === 'Escape') { this.clear(); this.render(); }
        else if (event.key === 'Delete' || event.key === 'Backspace') this.deleteSelection();
        else if (command && event.key.toLowerCase() === 'c' && this.nodes.size) {
            this.clipboard = this.actions.copy([...this.nodes]); this.pasteCount = 0;
        } else if (command && event.key.toLowerCase() === 'v' && this.clipboard) {
            this.selectNodes(this.actions.paste(this.clipboard, 40 * ++this.pasteCount));
        } else if (command && ['+', '=', '-'].includes(event.key)) this.actions.zoom(event.key === '-' ? -0.1 : 0.1);
        else if (!event.ctrlKey && !event.altKey && !event.metaKey && event.key.startsWith('Arrow')) {
            const dx = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0;
            const dy = event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0;
            if (event.shiftKey) this.moveNodes(dx * 10, dy * 10);
            else this.pan(-dx * 40, -dy * 40);
        } else handled = false;
        if (handled) { event.preventDefault(); event.stopImmediatePropagation(); }
    };

    private onWheel = (event: WheelEvent): void => {
        if (this.isEditing(event.target)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        if (event.ctrlKey || event.metaKey) this.actions.zoom(-event.deltaY * 0.01);
        else {
            const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? this.canvas.clientHeight : 1;
            this.pan(-event.deltaX * unit, -event.deltaY * unit);
        }
    };

    private pan(dx: number, dy: number): void {
        this.editor.canvas_x += dx;
        this.editor.canvas_y += dy;
        this.editor.precanvas.style.transform = `translate(${this.editor.canvas_x}px, ${this.editor.canvas_y}px) scale(${this.editor.zoom})`;
    }

    private render(): void {
        this.canvas.querySelectorAll<HTMLElement>('.drawflow-node').forEach(element => {
            const selected = this.nodes.has(Number(element.id.replace('node-', '')));
            element.classList.toggle('workflow-selected', selected);
        });
        this.canvas.querySelectorAll('.connection').forEach(element => {
            const edge = edgeFromElement(element);
            element.classList.toggle('workflow-selected', !!edge && this.edges.has(edgeKey(edge)));
        });
        const count = this.nodes.size + this.edges.size;
        const toolbar = this.root.querySelector<HTMLElement>('[data-selection-actions]');
        if (toolbar) toolbar.hidden = !this.enabled || !count;
        const rename = this.root.querySelector<HTMLButtonElement>('[data-selection-rename]');
        if (rename) rename.hidden = count !== 1;
        const duplicate = this.root.querySelector<HTMLButtonElement>('[data-selection-duplicate]');
        const hasTrigger = [...this.nodes].some(id => this.editor.drawflow.drawflow.Home.data[id]?.data.nodeType === 'TRIGGER');
        if (duplicate) {
            duplicate.hidden = !this.nodes.size;
            duplicate.disabled = hasTrigger && this.nodes.size === 1;
            duplicate.title = hasTrigger ? 'Only one trigger is allowed. Duplicate copies the other selected nodes.' : 'Duplicate selected nodes and their internal connections';
        }
        const notice = this.root.querySelector<HTMLElement>('[data-selection-notice]');
        if (notice) { notice.hidden = !hasTrigger; notice.textContent = 'Triggers cannot be duplicated.'; }
        const status = this.root.querySelector<HTMLElement>('[data-selection-status]');
        if (status) status.textContent = count ? `${this.nodes.size} nodes, ${this.edges.size} connections selected` : '';
    }
}
