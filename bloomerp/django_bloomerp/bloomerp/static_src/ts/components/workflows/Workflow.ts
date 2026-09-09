import getGeneralModal from "@/utils/modals";
import { getCsrfToken } from "@/utils/cookies";
import BaseComponent, { getComponent, initComponents } from "../BaseComponent";
import { BaseWidget } from "../widgets/BaseWidget";
import { Drawer } from "../Drawer";
import DrawFlow from 'drawflow';
import htmx from "htmx.org";
import WorkflowSelection, { edgeFromElement } from "./WorkflowSelection";

interface SavedWorkflowNode {
    id: number;
    client_id: string;
    type: string;
    sub_type: string;
    name?: string | null;
    parameters: Record<string, any>;
    pos_x: number;
    pos_y: number;
    output_ports?: WorkflowOutputPort[];
}

interface SavedWorkflowEdge {
    id?: number;
    from_node: string;
    to_node: string;
    name?: string | null;
    output_port?: string;
}

interface SavedWorkflow {
    workflow_id?: number;
    name?: string;
    nodes?: SavedWorkflowNode[];
    edges?: SavedWorkflowEdge[];
}

interface WorkflowNodeDefinition {
    typeId: string;
    typeName: string;
    subTypeId: string;
    subTypeName: string;
    description: string;
    icon: string;
    outputPorts: WorkflowOutputPort[];
}

interface WorkflowOutputPort {
    id: string;
    label: string;
    max_connections: number | null;
}

interface WorkflowEdgeMetadata {
    id?: number;
    name: string;
}

const WORKFLOW_CANVAS_WIDTH = 12000;
const WORKFLOW_CANVAS_HEIGHT = 12000;
const WORKFLOW_CANVAS_OFFSET_X = 1200;
const WORKFLOW_CANVAS_OFFSET_Y = 900;
const WORKFLOW_DEFAULT_ZOOM_STEP = 0.1;
const WORKFLOW_MIN_ZOOM = 0.2;
const WORKFLOW_MAX_ZOOM = 3;
const WORKFLOW_FIT_PADDING = 120;
const WORKFLOW_FIT_MAX_ZOOM = 1;
const WORKFLOW_FIT_MIN_ZOOM = 0.45;

function parseDrawflowClientId(clientId: string): number | null {
    const match = clientId.match(/^(?:node|draft)-(\d+)$/);
    if (!match) return null;

    const parsed = Number.parseInt(match[1], 10);
    return Number.isFinite(parsed) ? parsed : null;
}

function buildWorkflowClientId(drawflowId: number, workflowNodeId?: number): string {
    return workflowNodeId ? `node-${drawflowId}` : `draft-${drawflowId}`;
}

function normalizeDrawflowId(value: unknown): number | null {
    const parsed = Number.parseInt(String(value), 10);
    return Number.isFinite(parsed) ? parsed : null;
}

function toCanvasPosition(value: unknown, offset: number): number {
    return safePosition(value) + offset;
}

function toStoredPosition(value: unknown, offset: number): number {
    return safePosition(value) - offset;
}

function escapeHtml(value: string): string {
    const element = document.createElement('div');
    element.textContent = value;
    return element.innerHTML;
}

function truncate(value: string, maxLength: number = 48): string {
    if (value.length <= maxLength) return value;
    return `${value.slice(0, maxLength - 1)}…`;
}

function stringifyConfigValue(value: any): string {
    if (value === null || value === undefined || value === '') return 'empty';
    if (typeof value === 'object') return truncate(JSON.stringify(value), 56);
    return truncate(String(value), 56);
}

function parseOutputPorts(value: string | null): WorkflowOutputPort[] {
    const fallback = [{ id: 'default', label: 'Output', max_connections: null }];
    if (!value) return fallback;
    try {
        const ports = JSON.parse(value);
        return Array.isArray(ports) && ports.length ? ports : fallback;
    } catch {
        return fallback;
    }
}

function createWorkflowEdgeKey(
    fromNodeId: number | string,
    toNodeId: number | string,
    outputClass: string = 'output_1',
    inputClass: string = 'input_1',
): string {
    return `${fromNodeId}:${outputClass}->${toNodeId}:${inputClass}`;
}

function connectionInfoToEdgeKey(info: any): string {
    return createWorkflowEdgeKey(
        info.output_id,
        info.input_id,
        info.output_class || 'output_1',
        info.input_class || 'input_1',
    );
}

function getConnectionElement(
    container: HTMLElement,
    fromNodeId: number | string,
    toNodeId: number | string,
    outputClass: string = 'output_1',
    inputClass: string = 'input_1',
): SVGElement | null {
    return container.querySelector<SVGElement>(
        `.connection.node_in_node-${toNodeId}.node_out_node-${fromNodeId}.${outputClass}.${inputClass}`,
    );
}

function createConfigSummary(parameters: Record<string, any> = {}): string {
    const entries = Object.entries(parameters).filter(([key]) => key !== 'csrfmiddlewaretoken');
    if (!entries.length) return '<span class="workflow-node-empty-config">No config yet</span>';

    return entries.slice(0, 3).map(([key, value]) => {
        return `
            <span class="workflow-node-config-chip">
                <span class="workflow-node-config-key">${escapeHtml(key)}</span>
                <span class="workflow-node-config-value">${escapeHtml(stringifyConfigValue(value))}</span>
            </span>
        `;
    }).join('');
}

function createNodeHtml(
    nodeType: string,
    nodeSubType: string,
    nodeId: number,
    definition?: Partial<WorkflowNodeDefinition>,
    parameters?: Record<string, any>,
    workflowNodeId?: number,
    nodeName?: string | null,
): string {
    const typeLabel = definition?.typeName || nodeType;
    const subTypeLabel = definition?.subTypeName || nodeSubType;
    const titleLabel = nodeName?.trim() || subTypeLabel || typeLabel;
    const icon = definition?.icon || 'fa-solid fa-circle-nodes';
    const cardType = nodeType.toLowerCase();

    return `
        <div class="node-content workflow-node-card workflow-node-card--${escapeHtml(cardType)}">
            <div class="node-header workflow-node-header">
                <div class="workflow-node-icon"><i class="${escapeHtml(icon)}"></i></div>
                <div class="workflow-node-title-wrap">
                    <div class="workflow-node-kicker">${escapeHtml(typeLabel)}</div>
                    <div class="workflow-node-title">${escapeHtml(titleLabel)}</div>
                </div>
            </div>
            <div class="node-body">
                <div class="workflow-node-config">${createConfigSummary(parameters)}</div>
            </div>
        </div>
    `;
}

interface Coordinates {
    x:number,
    y:number
}

function safePosition(value: any): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.round(parsed) : 0;
}

export default class Workflow extends BaseComponent {
    private drawflow: DrawFlow;
    private selection: WorkflowSelection | null = null;
    private nodeDrawerElement: HTMLElement | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private lifecycle = new AbortController();
    private nodeId: number = 1;
    private workflowId: string | null = null;
    private workflowName: string = 'Workflow';
    private editingNodeId: number | null = null;
    private nodeDefinitions: Map<string, WorkflowNodeDefinition> = new Map();
    private edgeMetadata: Map<string, WorkflowEdgeMetadata> = new Map();
    private isImportingWorkflow: boolean = false;
    private autosaveTimer: number | null = null;
    private nodeConfigAutosaveTimer: number | null = null;
    private pendingNodeConfigForm: HTMLFormElement | null = null;
    private nodeConfigSaveVersion: number = 0;
    private refreshNodeConfigFormOnNextSave: boolean = false;
    private saveInFlight: Promise<void> | null = null;
    private saveAgainAfterCurrent: boolean = false;
    private nodeDrawerLoadPromise: Promise<void> | null = null;

    private nodeFormEditMode: 'form' | 'json' = 'form';

    private startNodeId: number | null = null;

    public initialize(): void {
        if (!this.element) return;
        this.element.addEventListener('htmx:beforeCleanupElement', event => {
            if (event.target === this.element) this.destroy();
        }, { signal: this.lifecycle.signal });

        this.nodeDrawerElement = this.element.querySelector<HTMLElement>('#node-drawer');

        // Initialize DrawFlow on the drawflow container
        const container = this.element.querySelector('#drawflow') as HTMLElement;
        if (!container) {
            console.error('DrawFlow container not found');
            return;
        }
        
        this.drawflow = new DrawFlow(container);
        
        // Start DrawFlow first
        this.drawflow.start();
        this.setupCanvasWorkspace(container);
        
        // Register events
        this.drawflow.on('nodeCreated', (id: number) => {
            this.scheduleAutosave();
        });
        
        this.drawflow.on('connectionCreated', (info: any) => {
            if (!this.connectionFitsPortLimit(info)) {
                this.drawflow.removeSingleConnection(
                    info.output_id,
                    info.input_id,
                    info.output_class,
                    info.input_class,
                );
                return;
            }
            this.edgeMetadata.set(connectionInfoToEdgeKey(info), { name: '' });
            this.refreshWorkflowEdgeLabels();
            this.scheduleAutosave();
        });
        
        this.drawflow.on('nodeRemoved', (id: number) => {
            this.scheduleAutosave();
        });

        this.drawflow.on('connectionRemoved', (info: any) => {
            this.edgeMetadata.delete(connectionInfoToEdgeKey(info));
            this.refreshWorkflowEdgeLabels();
            this.scheduleAutosave();
        });

        this.drawflow.on('nodeMoved', (id: number) => {
            this.refreshWorkflowEdgeLabels();
            this.scheduleAutosave();
        });
        
        this.drawflow.on('nodeSelected', (id: number) => {
            
        });
        
        // Create initial editor module
        this.drawflow.addModule('Home');
        this.drawflow.changeModule('Home');
        (this.drawflow as any).zoom_max = WORKFLOW_MAX_ZOOM;
        this.workflowId = this.element.getAttribute('data-workflow-id');
        this.buildNodeDefinitions();
        this.importSavedWorkflow();
        
        // Setup toolbar buttons
        this.setupToolbar();

        // Setup double-click handler for nodes
        this.setupNodeDoubleClickHandler();

        // Setup context menu for nodes
        this.selection = new WorkflowSelection(this.element, container, this.drawflow, {
            changed: () => { this.refreshWorkflowEdgeLabels(); this.scheduleAutosave(); },
            renameNode: id => this.startEditingNodeName(id),
            renameEdge: edge => { void this.startEditingWorkflowEdge(edge); },
            copy: ids => this.copyNodes(ids),
            paste: (snapshot, offset) => this.pasteNodes(snapshot as ReturnType<Workflow['copyNodes']>, offset),
            zoom: delta => this.adjustZoom(delta),
        });
        this.setupCanvasHeight(container);

        // Setup node drawer for adding new nodes
        this.setupNodeDrawer();

    }

    public destroy(): void {
        if (this.lifecycle.signal.aborted) return;
        this.selection?.destroy();
        this.getNodeDrawer()?.destroy();
        this.resizeObserver?.disconnect();
        this.lifecycle.abort();
        if (this.autosaveTimer) void this.flushAutosave();
        if (this.nodeConfigAutosaveTimer) {
            window.clearTimeout(this.nodeConfigAutosaveTimer);
            this.nodeConfigAutosaveTimer = null;
            if (this.pendingNodeConfigForm) void this.saveNodeConfigForm(this.pendingNodeConfigForm);
            this.pendingNodeConfigForm = null;
        }
        super.destroy();
    }

    private setupCanvasHeight(container: HTMLElement): void {
        const resize = () => {
            const top = container.getBoundingClientRect().top;
            container.style.height = `${Math.max(240, window.innerHeight - Math.max(0, top) - 16)}px`;
        };
        this.resizeObserver = new ResizeObserver(resize);
        const parent = this.element.closest('#detail-view-content')?.parentElement;
        if (parent) this.resizeObserver.observe(parent);
        window.addEventListener('resize', resize, { signal: this.lifecycle.signal });
        resize();
    }

    private copyNodes(ids: number[]) {
        const nodes = ids.map(id => this.drawflow.getNodeFromId(id)).filter(node => node.data.nodeType !== 'TRIGGER');
        const selected = new Set(nodes.map(node => Number(node.id)));
        const edges = nodes.flatMap(node => Object.entries(node.outputs).flatMap(([outputClass, output]) =>
            output.connections.filter(connection => selected.has(Number(connection.node))).map(connection => ({
                from: Number(node.id), to: Number(connection.node), outputClass,
                inputClass: connection.output,
                name: this.edgeMetadata.get(createWorkflowEdgeKey(node.id, connection.node, outputClass, connection.output))?.name || '',
            })),
        ));
        return structuredClone({ nodes, edges });
    }

    private pasteNodes(snapshot: ReturnType<Workflow['copyNodes']>, offset: number): number[] {
        const ids = new Map<number, number>();
        for (const node of snapshot.nodes) {
            const data = { ...structuredClone(node.data), workflowNodeId: undefined };
            const id = Number(this.drawflow.addNode(
                node.name, Object.keys(node.inputs).length, Object.keys(node.outputs).length,
                node.pos_x + offset, node.pos_y + offset, `${node.name}-${this.nodeId++}`, data,
                createNodeHtml(data.nodeType, data.nodeSubType, this.nodeId, data.nodeDefinition, data.parameters, undefined, data.nodeName), false,
            ));
            ids.set(Number(node.id), id);
            this.decorateNodeOutputPorts(id, data.outputPorts || []);
        }
        for (const edge of snapshot.edges) {
            const from = ids.get(edge.from)!;
            const to = ids.get(edge.to)!;
            this.drawflow.addConnection(from, to, edge.outputClass, edge.inputClass);
            this.edgeMetadata.set(createWorkflowEdgeKey(from, to, edge.outputClass, edge.inputClass), { name: edge.name });
        }
        this.refreshWorkflowEdgeLabels();
        this.scheduleAutosave();
        return [...ids.values()];
    }

    private buildNodeDefinitions(): void {
        this.nodeDefinitions.clear();
        this.element.querySelectorAll<HTMLElement>('[data-node-subtype-id]').forEach((el) => {
            const typeId = el.getAttribute('data-node-type-id') || '';
            const subTypeId = el.getAttribute('data-node-subtype-id') || '';
            if (!typeId || !subTypeId) return;

            this.nodeDefinitions.set(this.nodeDefinitionKey(typeId, subTypeId), {
                typeId,
                typeName: el.getAttribute('data-node-type-name') || typeId,
                subTypeId,
                subTypeName: el.getAttribute('data-node-subtype-name') || subTypeId,
                description: el.getAttribute('data-node-subtype-description') || '',
                icon: el.getAttribute('data-node-subtype-icon') || 'fa-solid fa-circle-nodes',
                outputPorts: parseOutputPorts(el.getAttribute('data-node-output-ports')),
            });
        });
    }

    private nodeDefinitionKey(nodeType: string, nodeSubType: string): string {
        return `${nodeType}:${nodeSubType}`;
    }

    private getNodeDefinition(nodeType: string, nodeSubType: string): WorkflowNodeDefinition | undefined {
        return this.nodeDefinitions.get(this.nodeDefinitionKey(nodeType, nodeSubType));
    }

    private outputPortForClass(
        ports: WorkflowOutputPort[],
        outputClass: string,
    ): WorkflowOutputPort {
        const index = Math.max(0, Number.parseInt(outputClass.replace('output_', ''), 10) - 1);
        return ports[index] || { id: 'default', label: 'Output', max_connections: null };
    }

    private outputClassForPort(ports: WorkflowOutputPort[], portId: string): string {
        const index = ports.findIndex((port) => port.id === portId);
        return `output_${index >= 0 ? index + 1 : 1}`;
    }

    private connectionFitsPortLimit(info: any): boolean {
        const node = this.drawflow.getNodeFromId(info.output_id);
        if (!node) return true;
        const ports = node.data?.outputPorts || [];
        const port = this.outputPortForClass(ports, info.output_class || 'output_1');
        if (port.max_connections === null) return true;
        const connectionCount = node.outputs?.[info.output_class]?.connections?.length || 0;
        return connectionCount <= port.max_connections;
    }

    private decorateNodeOutputPorts(nodeId: number, ports: WorkflowOutputPort[]): void {
        window.requestAnimationFrame(() => {
            const nodeElement = this.element?.querySelector<HTMLElement>(`#node-${nodeId}`);
            if (!nodeElement) return;
            nodeElement.querySelectorAll<HTMLElement>('.outputs .output').forEach((output, index) => {
                const port = ports[index] || { id: 'default', label: 'Output', max_connections: null };
                output.dataset.workflowPortId = port.id;
                output.setAttribute('aria-label', port.label);
                output.setAttribute('title', port.label);
                output.querySelectorAll('[data-workflow-port-label]').forEach((label) => label.remove());
                const label = document.createElement('span');
                label.dataset.workflowPortLabel = 'true';
                label.textContent = port.label;
                label.style.position = 'absolute';
                label.style.right = '12px';
                label.style.transform = 'translateY(-50%)';
                label.style.whiteSpace = 'nowrap';
                label.style.fontSize = '11px';
                label.style.color = '#64748b';
                label.style.pointerEvents = 'none';
                output.appendChild(label);
            });
        });
    }

    private syncNodeOutputPorts(nodeId: number, ports: WorkflowOutputPort[]): void {
        const node = this.drawflow.getNodeFromId(nodeId);
        if (!node) return;

        const previousPorts = node.data?.outputPorts || [];
        const connections = Object.entries(node.outputs || {}).flatMap(
            ([outputClass, output]: [string, any]) => (output.connections || []).flatMap((connection: any) => {
                const toNodeId = normalizeDrawflowId(connection.node);
                if (toNodeId === null) return [];
                const inputClass = connection.output || 'input_1';
                return [{
                    outputClass,
                    inputClass,
                    portId: this.outputPortForClass(previousPorts, outputClass).id,
                    toNodeId,
                    metadata: this.edgeMetadata.get(
                        createWorkflowEdgeKey(nodeId, toNodeId, outputClass, inputClass),
                    ),
                }];
            }),
        );
        const connectionsNeedRemapping = connections.some((connection) => {
            const nextPortIndex = ports.findIndex((port) => port.id === connection.portId);
            return nextPortIndex < 0 || `output_${nextPortIndex + 1}` !== connection.outputClass;
        });

        const wasImportingWorkflow = this.isImportingWorkflow;
        if (connectionsNeedRemapping) {
            this.isImportingWorkflow = true;
            for (const connection of connections) {
                this.drawflow.removeSingleConnection(
                    nodeId,
                    connection.toNodeId,
                    connection.outputClass,
                    connection.inputClass,
                );
            }
        }

        const targetCount = Math.max(1, ports.length);
        let currentCount = Object.keys(node.outputs || {}).length;
        while (currentCount < targetCount) {
            this.drawflow.addNodeOutput(nodeId);
            currentCount += 1;
        }
        while (currentCount > targetCount) {
            this.drawflow.removeNodeOutput(nodeId, `output_${currentCount}`);
            currentCount -= 1;
        }

        if (connectionsNeedRemapping) {
            this.drawflow.updateNodeDataFromId(nodeId, {
                ...node.data,
                outputPorts: ports,
            });
            for (const connection of connections) {
                if (!ports.some((port) => port.id === connection.portId)) continue;
                const outputClass = this.outputClassForPort(ports, connection.portId);
                this.drawflow.addConnection(
                    nodeId,
                    connection.toNodeId,
                    outputClass,
                    connection.inputClass,
                );
                if (connection.metadata) {
                    this.edgeMetadata.set(
                        createWorkflowEdgeKey(
                            nodeId,
                            connection.toNodeId,
                            outputClass,
                            connection.inputClass,
                        ),
                        connection.metadata,
                    );
                }
            }
            this.isImportingWorkflow = wasImportingWorkflow;
            this.refreshWorkflowEdgeLabels();
        }

        this.decorateNodeOutputPorts(nodeId, ports);
    }

    private importSavedWorkflow(): void {
        const workflowJson = this.element?.getAttribute('data-workflow-json') || '';
        if (!workflowJson) return;

        let workflow: SavedWorkflow;
        try {
            workflow = JSON.parse(workflowJson);
        } catch (error) {
            console.error('Invalid workflow JSON', error);
            return;
        }
        
        this.workflowId = workflow.workflow_id?.toString() || this.workflowId;
        this.workflowName = workflow.name || this.workflowName;
        const nodeIdMap = new Map<string, number>();
        let maxNodeId = 0;
        let firstImportedDrawflowNodeId: number | null = null;
        this.isImportingWorkflow = true;

        for (const node of workflow.nodes || []) {
            const drawflowId = parseDrawflowClientId(String(node.client_id)) || node.id;
            const nodeSubType = node.sub_type || '';
            const definition = this.getNodeDefinition(node.type, nodeSubType);
            const nodeData = {
                workflowNodeId: node.id,
                nodeType: node.type,
                nodeSubType,
                nodeName: node.name || '',
                nodeDefinition: definition,
                parameters: node.parameters || {},
                outputPorts: node.output_ports || definition?.outputPorts || [],
            };
            const inputs = node.type === 'TRIGGER' ? 0 : 1;
            
            const addedNodeId = Number(this.drawflow.addNode(
                node.type,
                inputs,
                Math.max(1, nodeData.outputPorts.length),
                toCanvasPosition(node.pos_x, WORKFLOW_CANVAS_OFFSET_X),
                toCanvasPosition(node.pos_y, WORKFLOW_CANVAS_OFFSET_Y),
                `${node.type}-${drawflowId}`,
                nodeData,
                createNodeHtml(node.type, nodeSubType, drawflowId, definition, nodeData.parameters, node.id, node.name),
                false
            ));
            this.decorateNodeOutputPorts(addedNodeId, nodeData.outputPorts);

            if (firstImportedDrawflowNodeId === null) {
                firstImportedDrawflowNodeId = addedNodeId;
            }

            nodeIdMap.set(node.client_id, addedNodeId);
            maxNodeId = Math.max(maxNodeId, addedNodeId);
        }

        for (const edge of workflow.edges || []) {
            const fromNode = nodeIdMap.get(edge.from_node);
            const toNode = nodeIdMap.get(edge.to_node);
            if (!fromNode || !toNode) continue;
            const fromData = this.drawflow.getNodeFromId(fromNode)?.data;
            const outputClass = this.outputClassForPort(
                fromData?.outputPorts || [],
                edge.output_port || 'default',
            );
            this.drawflow.addConnection(fromNode, toNode, outputClass, 'input_1');
            this.edgeMetadata.set(
                createWorkflowEdgeKey(fromNode, toNode, outputClass, 'input_1'),
                {
                    id: edge.id,
                    name: edge.name || '',
                },
            );
        }

        this.nodeId = Math.max(this.nodeId, maxNodeId + 1);
        this.isImportingWorkflow = false;
        this.refreshWorkflowEdgeLabels();

        if (firstImportedDrawflowNodeId) {
            this.centerNodeInViewport(firstImportedDrawflowNodeId);
        } else {
            this.fitWorkflowToViewport();
        }
    }

    /**
     * Setup the canvas workspace with initial dimensions and zoom level
     * @param container 
     * @returns 
     */
    private setupCanvasWorkspace(container: HTMLElement): void {
        const precanvas = (this.drawflow as any).precanvas as HTMLElement | null;
        if (!precanvas) return;

        //Setup height and width of the canvas
        precanvas.style.width = `${WORKFLOW_CANVAS_WIDTH}px`;
        precanvas.style.height = `${WORKFLOW_CANVAS_HEIGHT}px`;
        precanvas.style.minWidth = `${WORKFLOW_CANVAS_WIDTH}px`;
        precanvas.style.minHeight = `${WORKFLOW_CANVAS_HEIGHT}px`;
        precanvas.style.transformOrigin = '0 0';

        (this.drawflow as any).zoom_value = WORKFLOW_DEFAULT_ZOOM_STEP;
        (this.drawflow as any).zoom_max = WORKFLOW_MAX_ZOOM;
        
    }
    
    private centerNodeInViewport(nodeId: number): void {
        window.requestAnimationFrame(() => {
            const container = this.element?.querySelector<HTMLElement>('#drawflow');
            const precanvas = (this.drawflow as any).precanvas as HTMLElement | null;
            if (!container || !precanvas) return;

            const node = this.drawflow.getNodeFromId(nodeId);
            if (!node) {
                this.fitWorkflowToViewport();
                return;
            }

            const nodeLeft = safePosition((node as any).pos_x);
            const nodeTop = safePosition((node as any).pos_y);
            const nodeWidth = 240;
            const nodeHeight = 120;
            const targetCenterX = nodeLeft + (nodeWidth / 2);
            const targetCenterY = nodeTop + (nodeHeight / 2);
            const zoom = WORKFLOW_FIT_MAX_ZOOM;
            const canvasX = Math.round((container.clientWidth / 2) - (targetCenterX * zoom));
            const canvasY = Math.round((container.clientHeight / 2) - (targetCenterY * zoom));

            (this.drawflow as any).zoom = zoom;
            (this.drawflow as any).zoom_last_value = zoom;
            (this.drawflow as any).canvas_x = canvasX;
            (this.drawflow as any).canvas_y = canvasY;
            precanvas.style.transform = `translate(${canvasX}px, ${canvasY}px) scale(${zoom})`;
        });
    }

    
    private fitWorkflowToViewport(options: { focusNodeId?: number } = {}): void {
        window.requestAnimationFrame(() => {
            const container = this.element?.querySelector<HTMLElement>('#drawflow');
            const precanvas = (this.drawflow as any).precanvas as HTMLElement | null;
            if (!container || !precanvas) return;

            const nodeElements = Array.from(
                container.querySelectorAll<HTMLElement>('.drawflow-node'),
            );
            if (!nodeElements.length) {
                this.setupCanvasWorkspace(container);
                return;
            }

            let minX = Number.POSITIVE_INFINITY;
            let minY = Number.POSITIVE_INFINITY;
            let maxX = Number.NEGATIVE_INFINITY;
            let maxY = Number.NEGATIVE_INFINITY;

            for (const nodeElement of nodeElements) {
                const left = Number.parseFloat(nodeElement.style.left) || 0;
                const top = Number.parseFloat(nodeElement.style.top) || 0;
                const width = nodeElement.offsetWidth || 240;
                const height = nodeElement.offsetHeight || 120;

                minX = Math.min(minX, left);
                minY = Math.min(minY, top);
                maxX = Math.max(maxX, left + width);
                maxY = Math.max(maxY, top + height);
            }

            const contentWidth = Math.max(1, maxX - minX);
            const contentHeight = Math.max(1, maxY - minY);
            const availableWidth = Math.max(1, container.clientWidth - (WORKFLOW_FIT_PADDING * 2));
            const availableHeight = Math.max(1, container.clientHeight - (WORKFLOW_FIT_PADDING * 2));
            let fitZoom = Math.min(
                WORKFLOW_FIT_MAX_ZOOM,
                Math.max(
                    WORKFLOW_FIT_MIN_ZOOM,
                    Math.min(availableWidth / contentWidth, availableHeight / contentHeight),
                ),
            );

            const contentCenterX = minX + (contentWidth / 2);
            const contentCenterY = minY + (contentHeight / 2);
            let targetCenterX = contentCenterX;
            let targetCenterY = contentCenterY;

            if (options.focusNodeId) {
                const focusNodeElement = container.querySelector<HTMLElement>(`#node-${options.focusNodeId}`);
                if (focusNodeElement) {
                    const firstNodeLeft = Number.parseFloat(focusNodeElement.style.left) || 0;
                    const firstNodeTop = Number.parseFloat(focusNodeElement.style.top) || 0;
                    const firstNodeWidth = focusNodeElement.offsetWidth || 240;
                    const firstNodeHeight = focusNodeElement.offsetHeight || 120;
                    targetCenterX = firstNodeLeft + (firstNodeWidth / 2);
                    targetCenterY = firstNodeTop + (firstNodeHeight / 2);
                    fitZoom = WORKFLOW_FIT_MAX_ZOOM;
                }
            }

            const canvasX = Math.round((container.clientWidth / 2) - (targetCenterX * fitZoom));
            const canvasY = Math.round((container.clientHeight / 2) - (targetCenterY * fitZoom));

            (this.drawflow as any).zoom = fitZoom;
            (this.drawflow as any).zoom_last_value = fitZoom;
            (this.drawflow as any).canvas_x = canvasX;
            (this.drawflow as any).canvas_y = canvasY;
            precanvas.style.transform = `translate(${canvasX}px, ${canvasY}px) scale(${fitZoom})`;
        });
    }
    
    /**
     * Setup double-click handler for workflow nodes
     */
    private setupNodeDoubleClickHandler(): void {
        const container = this.element.querySelector('#drawflow') as HTMLElement;
        if (!container) return;
        
        container.addEventListener('dblclick', (e: MouseEvent) => {
            const target = e.target as HTMLElement;
            const nodeElement = target.closest('.drawflow-node') as HTMLElement;
            
            if (nodeElement) {
                const nodeId = parseInt(nodeElement.getAttribute('id')?.replace('node-', '') || '0');
                if (nodeId > 0) {
                    void this.handleNodeDoubleClick(nodeId);
                }
            }
        });
    }
    
    /**
     * Setup the context menu for a workflow node to allow editing the node title
     */
    private startEditingNodeName(nodeId: number): void {
        const nodeElement = this.element.querySelector<HTMLElement>(`#node-${nodeId}`);
        const nodeData = this.drawflow.getNodeFromId(nodeId);
        const titleElement = nodeElement?.querySelector<HTMLElement>('.workflow-node-title');
        if (!nodeData || !titleElement) return;
        const currentTitle = titleElement.textContent || '';
        const currentName = nodeData.data?.nodeName || '';

        const input = document.createElement('input');
        input.type = 'text';
        input.value = currentName || currentTitle;
        input.setAttribute('aria-label', 'Node name');
        input.style.width = '100%';
        input.style.minWidth = '0';
        input.style.border = '0';
        input.style.borderBottom = '1px solid #94a3b8';
        input.style.borderRadius = '0';
        input.style.background = 'transparent';
        input.style.padding = '0';
        input.style.font = 'inherit';
        input.style.fontWeight = 'inherit';
        input.style.lineHeight = 'inherit';
        input.style.color = 'inherit';
        input.style.outline = 'none';

        let finished = false;
        const finishEditing = async (commit: boolean) => {
            if (finished) return;
            finished = true;

            const nextName = input.value.trim();
            input.replaceWith(titleElement);

            if (!commit) {
                titleElement.textContent = currentTitle;
                return;
            }

            const updatedData = {
                ...nodeData.data,
                nodeName: nextName,
            };
            this.drawflow.updateNodeDataFromId(nodeId, updatedData);
            this.refreshNodeCard(nodeId, updatedData);

            this.scheduleAutosave();
            await this.flushAutosave();
        };

        input.addEventListener('click', (event) => event.stopPropagation());
        input.addEventListener('dblclick', (event) => event.stopPropagation());
        input.addEventListener('contextmenu', (event) => event.stopPropagation());
        input.addEventListener('keydown', (event: KeyboardEvent) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                void finishEditing(true);
                this.element.querySelector<HTMLElement>('#drawflow')?.focus({ preventScroll: true });
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                void finishEditing(false);
                this.element.querySelector<HTMLElement>('#drawflow')?.focus({ preventScroll: true });
            }
        });
        input.addEventListener('blur', () => void finishEditing(true));

        titleElement.replaceWith(input);
        input.focus();
        input.select();
    }

    private async startEditingWorkflowEdge(edgeInfo: {
        fromNodeId: string;
        toNodeId: string;
        outputClass: string;
        inputClass: string;
    }): Promise<void> {
        const edgeKey = createWorkflowEdgeKey(
            edgeInfo.fromNodeId,
            edgeInfo.toNodeId,
            edgeInfo.outputClass,
            edgeInfo.inputClass,
        );
        const currentMetadata = this.edgeMetadata.get(edgeKey) || { name: '' };
        const label = this.ensureWorkflowEdgeLabel(edgeInfo);
        if (!label) return;

        const textarea = document.createElement('textarea');
        textarea.value = currentMetadata.name;
        textarea.rows = Math.max(1, currentMetadata.name.split('\n').length);
        textarea.setAttribute('aria-label', 'Edge name');
        textarea.style.width = '160px';
        textarea.style.minHeight = '28px';
        textarea.style.maxHeight = '140px';
        textarea.style.resize = 'both';
        textarea.style.border = '0';
        textarea.style.borderBottom = '1px solid #94a3b8';
        textarea.style.borderRadius = '0';
        textarea.style.background = 'rgba(255, 255, 255, 0.92)';
        textarea.style.padding = '2px 4px';
        textarea.style.font = 'inherit';
        textarea.style.fontSize = '12px';
        textarea.style.lineHeight = '1.25';
        textarea.style.color = '#0f172a';
        textarea.style.outline = 'none';
        textarea.style.boxShadow = '0 1px 3px rgba(15, 23, 42, 0.12)';

        let finished = false;
        const finishEditing = async (commit: boolean) => {
            if (finished) return;
            finished = true;

            const nextName = textarea.value.trim();
            textarea.remove();

            if (!commit) {
                this.refreshWorkflowEdgeLabels();
                return;
            }

            this.edgeMetadata.set(edgeKey, {
                ...currentMetadata,
                name: nextName,
            });
            this.refreshWorkflowEdgeLabels();
            this.scheduleAutosave();
            await this.flushAutosave();
        };

        textarea.addEventListener('click', (event) => event.stopPropagation());
        textarea.addEventListener('dblclick', (event) => event.stopPropagation());
        textarea.addEventListener('contextmenu', (event) => event.stopPropagation());
        textarea.addEventListener('keydown', (event: KeyboardEvent) => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                void finishEditing(true);
                this.element.querySelector<HTMLElement>('#drawflow')?.focus({ preventScroll: true });
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                void finishEditing(false);
                this.element.querySelector<HTMLElement>('#drawflow')?.focus({ preventScroll: true });
            }
        });
        textarea.addEventListener('blur', () => void finishEditing(true));

        label.replaceChildren(textarea);
        label.style.display = 'block';
        textarea.focus();
        textarea.select();
    }

    private ensureWorkflowEdgeLabel(edgeInfo: {
        fromNodeId: string;
        toNodeId: string;
        outputClass: string;
        inputClass: string;
    }): HTMLElement | null {
        const container = this.element.querySelector<HTMLElement>('#drawflow');
        const precanvas = (this.drawflow as any).precanvas as HTMLElement | null;
        if (!container || !precanvas) return null;

        const edgeKey = createWorkflowEdgeKey(
            edgeInfo.fromNodeId,
            edgeInfo.toNodeId,
            edgeInfo.outputClass,
            edgeInfo.inputClass,
        );
        let label = precanvas.querySelector<HTMLElement>(`[data-workflow-edge-label="${CSS.escape(edgeKey)}"]`);
        if (!label) {
            label = document.createElement('div');
            label.dataset.workflowEdgeLabel = edgeKey;
            label.dataset.fromNodeId = edgeInfo.fromNodeId;
            label.dataset.toNodeId = edgeInfo.toNodeId;
            label.dataset.outputClass = edgeInfo.outputClass;
            label.dataset.inputClass = edgeInfo.inputClass;
            label.style.position = 'absolute';
            label.style.transform = 'translate(-50%, -50%)';
            label.style.zIndex = '4';
            label.style.maxWidth = '220px';
            label.style.minHeight = '18px';
            label.style.padding = '2px 5px';
            label.style.borderRadius = '4px';
            label.style.background = 'rgba(255, 255, 255, 0.88)';
            label.style.color = '#334155';
            label.style.fontSize = '12px';
            label.style.lineHeight = '1.25';
            label.style.textAlign = 'center';
            label.style.whiteSpace = 'pre-wrap';
            label.style.overflowWrap = 'anywhere';
            label.style.cursor = 'text';
            label.style.boxShadow = '0 1px 2px rgba(15, 23, 42, 0.08)';
            precanvas.appendChild(label);
        }

        const connectionElement = getConnectionElement(
            container,
            edgeInfo.fromNodeId,
            edgeInfo.toNodeId,
            edgeInfo.outputClass,
            edgeInfo.inputClass,
        );
        const path = connectionElement?.querySelector<SVGPathElement>('.main-path');
        if (!path) return label;

        try {
            const point = path.getPointAtLength(path.getTotalLength() / 2);
            label.style.left = `${point.x}px`;
            label.style.top = `${point.y}px`;
        } catch {
            label.style.display = 'none';
        }

        return label;
    }

    private refreshWorkflowEdgeLabels(): void {
        const container = this.element.querySelector<HTMLElement>('#drawflow');
        const precanvas = (this.drawflow as any).precanvas as HTMLElement | null;
        if (!container || !precanvas) return;

        precanvas.querySelectorAll<HTMLElement>('[data-workflow-edge-label]').forEach((label) => {
            if (!label.querySelector('textarea')) label.remove();
        });

        container.querySelectorAll<SVGElement>('.connection').forEach((connectionElement) => {
            const edgeInfo = edgeFromElement(connectionElement);
            if (!edgeInfo) return;
            const edgeKey = createWorkflowEdgeKey(
                edgeInfo.fromNodeId,
                edgeInfo.toNodeId,
                edgeInfo.outputClass,
                edgeInfo.inputClass,
            );
            const metadata = this.edgeMetadata.get(edgeKey);
            if (!metadata?.name) return;
            const label = this.ensureWorkflowEdgeLabel(edgeInfo);
            if (!label) return;
            if (label.querySelector('textarea')) return;
            label.textContent = metadata.name;
            label.style.display = 'block';
        });
    }


    private setupToolbar(): void {
        const addNodeBtn = this.element.querySelector('#add-node-btn');
        const clearBtn = this.element.querySelector('#clear-btn');
        const exportBtn = this.element.querySelector('#export-btn');
        const zoomInBtn = this.element.querySelector('#zoom-in-btn');
        const zoomOutBtn = this.element.querySelector('#zoom-out-btn');
        const zoomResetBtn = this.element.querySelector('#zoom-reset-btn');
        const focusFirstNodeBtn = this.element.querySelector('#focus-first-node-btn');
        
        if (addNodeBtn) {
            addNodeBtn.addEventListener('click', () => void this.openNodeDrawer());
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', () => this.clearAll());
        }
        
        if (exportBtn) {
            exportBtn.addEventListener('click', () => this.exportData());
        }
        
        if (zoomInBtn) {
            zoomInBtn.addEventListener('click', () => {
                this.adjustZoom(WORKFLOW_DEFAULT_ZOOM_STEP);
            });
        }
        
        if (zoomOutBtn) {
            zoomOutBtn.addEventListener('click', () => {
                this.adjustZoom(-WORKFLOW_DEFAULT_ZOOM_STEP);
            });
        }
        
        if (zoomResetBtn) {
            zoomResetBtn.addEventListener('click', () => {
                this.setZoomAtViewportCenter(1);
            });
        }

        if (focusFirstNodeBtn) {
            focusFirstNodeBtn.addEventListener('click', () => {
                this.focusViewportOnFirstNode();
            });
        }
    }

    private focusViewportOnFirstNode(): void {
        const firstNodeId = this.getFirstNodeId();
        if (!firstNodeId) {
            this.fitWorkflowToViewport();
            return;
        }

        this.centerNodeInViewport(firstNodeId);
    }

    private getFirstNodeId(): number | null {
        const exportData = this.drawflow.export();
        const activeModule = (this.drawflow as any).module || 'Home';
        const workflowData = exportData.drawflow?.[activeModule]?.data || {};
        const sortedNodeIds = Object.keys(workflowData)
            .map((id) => Number.parseInt(id, 10))
            .filter((id): id is number => Number.isFinite(id))
            .sort((a, b) => a - b);

        return sortedNodeIds.length ? sortedNodeIds[0] : null;
    }

    private adjustZoom(delta: number): void {
        const currentZoom = Number((this.drawflow as any).zoom) || 1;
        const nextZoom = Math.min(
            WORKFLOW_MAX_ZOOM,
            Math.max(WORKFLOW_MIN_ZOOM, currentZoom + delta),
        );
        this.setZoomAtViewportCenter(nextZoom);
    }

    private setZoomAtViewportCenter(nextZoom: number): void {
        const container = this.element.querySelector<HTMLElement>('#drawflow');
        const precanvas = (this.drawflow as any).precanvas as HTMLElement | null;
        if (!container || !precanvas) return;

        const currentZoom = Number((this.drawflow as any).zoom) || 1;
        const canvasX = Number((this.drawflow as any).canvas_x) || 0;
        const canvasY = Number((this.drawflow as any).canvas_y) || 0;
        const viewportCenterX = container.clientWidth / 2;
        const viewportCenterY = container.clientHeight / 2;

        // Keep the same graph point under the viewport center while zooming.
        const graphCenterX = (viewportCenterX - canvasX) / currentZoom;
        const graphCenterY = (viewportCenterY - canvasY) / currentZoom;
        const nextCanvasX = Math.round(viewportCenterX - (graphCenterX * nextZoom));
        const nextCanvasY = Math.round(viewportCenterY - (graphCenterY * nextZoom));

        (this.drawflow as any).zoom = nextZoom;
        (this.drawflow as any).zoom_last_value = nextZoom;
        (this.drawflow as any).canvas_x = nextCanvasX;
        (this.drawflow as any).canvas_y = nextCanvasY;
        precanvas.style.transform = `translate(${nextCanvasX}px, ${nextCanvasY}px) scale(${nextZoom})`;
    }
    
    private clearAll(): void {
        if (confirm('Are you sure you want to clear all nodes?')) {
            this.drawflow.clear();
            this.edgeMetadata.clear();
            this.nodeId = 1;
        }
    }

    private exportData(): void {
        console.log(this.drawflow.export());
    }
    

    private buildWorkflowPayload() {
        const exportData = this.drawflow.export();
        const workflowData = exportData.drawflow?.Home?.data || {};
        const nodes = Object.values(workflowData as Record<string, any>);
        const normalizedNodes = (nodes as Array<any>)
            .map((node) => ({
                node,
                drawflowId: normalizeDrawflowId(node.id),
            }))
            .filter(
                (entry): entry is { node: any; drawflowId: number } =>
                    entry.drawflowId !== null,
            );
        const edges: Array<{
            id?: number;
            from_node: string;
            to_node: string;
            name?: string | null;
            output_port: string;
        }> = [];
        const clientIdByDrawflowId = new Map<number, string>();

        for (const { node, drawflowId } of normalizedNodes) {
            clientIdByDrawflowId.set(
                drawflowId,
                buildWorkflowClientId(drawflowId, node.data?.workflowNodeId),
            );
        }

        for (const { node, drawflowId: fromDrawflowId } of normalizedNodes) {
            const outputs = node.outputs || {};
            for (const [outputClass, output] of Object.entries(outputs) as Array<[string, any]>) {
                for (const connection of output.connections || []) {
                    const toDrawflowId = normalizeDrawflowId(connection.node);
                    if (toDrawflowId === null) continue;
                    const inputClass = connection.output || 'input_1';
                    const edgeMetadata = this.edgeMetadata.get(
                        createWorkflowEdgeKey(fromDrawflowId, toDrawflowId, outputClass, inputClass),
                    );
                    edges.push({
                        ...(edgeMetadata?.id ? { id: edgeMetadata.id } : {}),
                        from_node: clientIdByDrawflowId.get(fromDrawflowId) || buildWorkflowClientId(fromDrawflowId),
                        to_node: clientIdByDrawflowId.get(toDrawflowId) || buildWorkflowClientId(toDrawflowId),
                        name: edgeMetadata?.name || null,
                        output_port: this.outputPortForClass(
                            node.data?.outputPorts || [],
                            outputClass,
                        ).id,
                    });
                }
            }
        }

        return {
            ...(this.workflowId ? { workflow_id: parseInt(this.workflowId, 10) } : {}),
            name: this.workflowName,
            nodes: normalizedNodes.map(({ node, drawflowId }) => ({
                ...(node.data?.workflowNodeId ? { id: node.data.workflowNodeId } : {}),
                client_id: clientIdByDrawflowId.get(drawflowId) || buildWorkflowClientId(drawflowId),
                type: node.data?.nodeType || node.name,
                name: node.data?.nodeName || null,
                sub_type: node.data?.nodeSubType,
                parameters: node.data?.parameters || {},
                pos_x: toStoredPosition(node.pos_x, WORKFLOW_CANVAS_OFFSET_X),
                pos_y: toStoredPosition(node.pos_y, WORKFLOW_CANVAS_OFFSET_Y),
            })),
            edges,
        };
    }

    private scheduleAutosave(): void {
        if (this.isImportingWorkflow || !this.workflowId) return;

        if (this.autosaveTimer) {
            window.clearTimeout(this.autosaveTimer);
        }

        this.autosaveTimer = window.setTimeout(() => {
            this.autosaveTimer = null;
            void this.saveWorkflow();
        }, 700);
    }

    private async flushAutosave(): Promise<void> {
        if (this.autosaveTimer) {
            window.clearTimeout(this.autosaveTimer);
            this.autosaveTimer = null;
            await this.saveWorkflow();
        }

        if (this.saveInFlight) {
            await this.saveInFlight;
        }
    }

    private async saveWorkflow(): Promise<void> {
        if (this.saveInFlight) {
            this.saveAgainAfterCurrent = true;
            await this.saveInFlight;
            return;
        }

        this.saveInFlight = (async () => {
            try {
                do {
                    this.saveAgainAfterCurrent = false;
                    const csrfToken = getCsrfToken();
                    const payload = this.buildWorkflowPayload();

                    const response = await fetch('/components/automation/save_workflow/', {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
                        },
                        body: JSON.stringify(payload),
                    });

                    if (!response.ok) {
                        console.error('Failed to save workflow');
                        return;
                    }

                    const savedWorkflow = await response.json();
                    this.workflowId = savedWorkflow.workflow_id?.toString() || this.workflowId;

                    for (const node of savedWorkflow.nodes || []) {
                        const drawflowId = parseDrawflowClientId(String(node.client_id));
                        if (!drawflowId || !this.drawflow.drawflow.drawflow.Home.data[drawflowId]) continue;
                        const drawflowNode = this.drawflow.getNodeFromId(drawflowId);
                        if (drawflowNode) {
                            const outputPorts = node.output_ports || drawflowNode.data?.outputPorts || [];
                            this.syncNodeOutputPorts(drawflowId, outputPorts);
                            const updatedData = {
                                ...drawflowNode.data,
                                workflowNodeId: node.id,
                                outputPorts,
                            };
                            this.drawflow.updateNodeDataFromId(drawflowId, updatedData);
                            this.refreshNodeCard(drawflowId, updatedData);
                        }
                    }

                    this.updateWorkflowEdgeMetadataFromSavedWorkflow(savedWorkflow);
                } while (this.saveAgainAfterCurrent);
            } catch (error) {
                console.error('Failed to save workflow', error);
            } finally {
                this.saveInFlight = null;
                if (this.saveAgainAfterCurrent) {
                    await this.saveWorkflow();
                }
            }
        })();

        await this.saveInFlight;
    }

    private updateWorkflowEdgeMetadataFromSavedWorkflow(savedWorkflow: SavedWorkflow): void {
        const drawflowIdByClientId = new Map<string, number>();
        const existingMetadata = new Map(this.edgeMetadata);

        for (const node of savedWorkflow.nodes || []) {
            const drawflowId = parseDrawflowClientId(String(node.client_id));
            if (drawflowId) drawflowIdByClientId.set(node.client_id, drawflowId);
        }

        for (const edge of savedWorkflow.edges || []) {
            const fromNodeId = drawflowIdByClientId.get(edge.from_node);
            const toNodeId = drawflowIdByClientId.get(edge.to_node);
            if (!fromNodeId || !toNodeId || !this.drawflow.drawflow.drawflow.Home.data[fromNodeId]) continue;

            const sourceNode = this.drawflow.getNodeFromId(fromNodeId);
            const outputClass = this.outputClassForPort(
                sourceNode?.data?.outputPorts || [],
                edge.output_port || 'default',
            );
            const edgeKey = createWorkflowEdgeKey(
                fromNodeId,
                toNodeId,
                outputClass,
                'input_1',
            );
            const previousMetadata = existingMetadata.get(edgeKey);
            if (!previousMetadata) continue; // The edge may have been deleted during the request.
            this.edgeMetadata.set(edgeKey, {
                id: edge.id,
                name: previousMetadata.name,
            });
        }

        this.refreshWorkflowEdgeLabels();
    }

    private setupNodeDrawer(): void {
        const drawerContent = this.getNodeDrawerContent();
        if (!drawerContent) return;

        drawerContent.addEventListener('click', (event: Event) => {
            const target = event.target as HTMLElement | null;
            const nodeItem = target?.closest<HTMLElement>('[data-node-subtype-id]');
            if (!nodeItem) return;

            const nodeType = nodeItem.getAttribute('data-node-type-id');
            const nodeSubType = nodeItem.getAttribute('data-node-subtype-id');
            if (!nodeType || !nodeSubType) return;

            this.addNode(nodeType, nodeSubType);
            this.filterDrawerTriggerItems();
            this.filterNodeDrawerSearch();
            this.getNodeDrawer()?.close();
        });

        drawerContent.addEventListener('input', (event: Event) => {
            const target = event.target as HTMLElement | null;
            if (!target?.matches('[data-workflow-node-search]')) return;
            this.filterNodeDrawerSearch();
        });
    }

    /**
     * Renders a node to the panel by calling an endpoint to render the node
     * @param nodeType the id of the node type
     * @param nodeSubType the id of the node subtype
     */
    private addNode(nodeType: string, nodeSubType: string) {
        const coordinates = this.getViewportCenterCoordinates();
        let numberOfInputs = 1;
        const definition = this.getNodeDefinition(nodeType, nodeSubType);
        const parameters = {};
        const outputPorts = definition?.outputPorts || [
            { id: 'default', label: 'Output', max_connections: null },
        ];

        if (nodeType==='TRIGGER') {
            numberOfInputs=0
        }

        const addedNodeId = Number(this.drawflow.addNode(
            nodeType,
            numberOfInputs,
            Math.max(1, outputPorts.length),
            coordinates.x,
            coordinates.y,
            `${nodeType}-${this.nodeId}`,
            {
                nodeType,
                nodeSubType,
                nodeDefinition: definition,
                nodeName: '',
                parameters,
                outputPorts,
            },
            createNodeHtml(nodeType, nodeSubType, this.nodeId, definition, parameters),
            false
        ));
        this.decorateNodeOutputPorts(addedNodeId, outputPorts);
                
        this.nodeId++;
    }

    private getViewportCenterCoordinates(): Coordinates {
        const container = this.element.querySelector<HTMLElement>('#drawflow');
        if (!container) {
            return {
                x: WORKFLOW_CANVAS_OFFSET_X + 120,
                y: WORKFLOW_CANVAS_OFFSET_Y + 120,
            };
        }

        const zoom = Number((this.drawflow as any).zoom) || 1;
        const canvasX = Number((this.drawflow as any).canvas_x) || 0;
        const canvasY = Number((this.drawflow as any).canvas_y) || 0;
        const nodeWidth = 240;
        const nodeHeight = 120;
        const centerCanvasX = ((container.clientWidth / 2) - canvasX) / zoom;
        const centerCanvasY = ((container.clientHeight / 2) - canvasY) / zoom;

        return {
            x: Math.round(centerCanvasX - (nodeWidth / 2)),
            y: Math.round(centerCanvasY - (nodeHeight / 2)),
        };
    }

    private getNodeDrawer(): Drawer | null {
        const drawerElement = this.nodeDrawerElement;
        if (!drawerElement) return null;
        return getComponent(drawerElement) as Drawer | null;
    }

    private getNodeDrawerContent(): HTMLElement | null {
        return this.nodeDrawerElement?.querySelector<HTMLElement>('[data-workflow-drawer-content]') ?? null;
    }

    private workflowHasTrigger(): boolean {
        const workflowData = this.drawflow.export().drawflow?.Home?.data || {};
        return Object.values(workflowData as Record<string, any>).some((node: any) => {
            return (node.data?.nodeType || node.name) === 'TRIGGER';
        });
    }

    private async openNodeDrawer(): Promise<void> {
        await this.loadNodeDrawer();
        this.getNodeDrawer()?.open();
    }

    private async loadNodeDrawer(): Promise<void> {
        if (this.nodeDrawerLoadPromise) {
            await this.nodeDrawerLoadPromise;
            return;
        }

        const drawerContent = this.getNodeDrawerContent();
        if (!drawerContent) return;

        const params = new URLSearchParams();
        if (this.workflowId) params.set('workflow_id', this.workflowId);
        if (this.workflowHasTrigger()) params.set('has_trigger', 'true');

        this.nodeDrawerLoadPromise = htmx.ajax(
            'get',
            `/components/automation/drawer/?${params.toString()}`,
            drawerContent,
        ).then(() => {
            initComponents(drawerContent);
            this.buildNodeDefinitions();
            this.filterDrawerTriggerItems();
            this.filterNodeDrawerSearch();
        }).finally(() => {
            this.nodeDrawerLoadPromise = null;
        });

        await this.nodeDrawerLoadPromise;
    }

    private filterDrawerTriggerItems(): void {
        const drawerContent = this.getNodeDrawerContent();
        if (!drawerContent) return;

        const hasTrigger = this.workflowHasTrigger();
        const triggerGroup = drawerContent.querySelector<HTMLElement>('[data-workflow-node-group-name="trigger"]');
        if (triggerGroup) {
            triggerGroup.classList.toggle('hidden', hasTrigger);
        }

        const notice = drawerContent.querySelector<HTMLElement>('[data-workflow-drawer-root]');
        if (notice) {
            notice.setAttribute('data-workflow-drawer-has-trigger', hasTrigger ? 'true' : 'false');
        }
    }

    private filterNodeDrawerSearch(): void {
        const drawerContent = this.getNodeDrawerContent();
        if (!drawerContent) return;

        const query = (drawerContent.querySelector<HTMLInputElement>('[data-workflow-node-search]')?.value || '')
            .trim()
            .toLowerCase();
        const nodeItems = Array.from(drawerContent.querySelectorAll<HTMLElement>('[data-workflow-node-item]'));
        const nodeGroups = Array.from(drawerContent.querySelectorAll<HTMLElement>('[data-workflow-node-group]'));
        let visibleCount = 0;

        nodeItems.forEach((item) => {
            const searchText = (item.getAttribute('data-workflow-search-text') || '').toLowerCase();
            const matches = !query || searchText.includes(query);
            item.classList.toggle('hidden', !matches);
            if (matches) visibleCount += 1;
        });

        nodeGroups.forEach((group) => {
            const hasVisibleItems = Array.from(group.querySelectorAll<HTMLElement>('[data-workflow-node-item]'))
                .some((item) => !item.classList.contains('hidden'));
            group.classList.toggle('hidden', !hasVisibleItems);
        });

        const emptyState = drawerContent.querySelector<HTMLElement>('[data-workflow-node-empty-search]');
        if (emptyState) {
            emptyState.classList.toggle('hidden', visibleCount !== 0);
        }
    }

    /**
     * Handles double-click on a node to trigger node-specific actions
     * @param nodeId the ID of the double-clicked node
     */
    private async handleNodeDoubleClick(nodeId: number): Promise<void> {
        this.editingNodeId = nodeId;
        const nodeData = this.drawflow.getNodeFromId(nodeId);
        await this.flushAutosave();
        const persistedNodeData = this.drawflow.getNodeFromId(nodeId);
        if (!persistedNodeData?.data?.workflowNodeId) {
            console.error('Cannot edit workflow node before it is saved');
            return;
        }
        
        // Get the general modal
        const modal = getGeneralModal()
        const modalBody = modal.getBodyElement();
        if (!modalBody) return;
        modal.setTitle('Edit node')
        modal.setSize('full')
        modal.setPadding('p-0')
        modal.open()
        this.loadNodeConfigFormForNode(persistedNodeData, modalBody);

    }

    private loadNodeConfigFormForNode(nodeData: any, target: HTMLElement, editMode: 'form' | 'json' = 'form'): void {
        const params = new URLSearchParams({
            node_id: String(nodeData.data.workflowNodeId),
            edit_mode: editMode,
        });

        htmx.ajax(
            'get',
            `/components/automation/render_workflow_node/?${params.toString()}`,
            target,
        ).then(() => {
            this.prepareNodeConfigForm(target);
            initComponents(target);
            this.setupNodeConfigForm(target);
        });
    }

    private prepareNodeConfigForm(container: HTMLElement): void {
        const form = container.querySelector<HTMLFormElement>('form[data-workflow-node-config-form="true"]');
        if (!form) return;

        form.removeAttribute('hx-post');
        form.removeAttribute('hx-target');
        form.removeAttribute('hx-swap');
        form.removeAttribute('action');
    }

    private setupNodeConfigForm(container: HTMLElement): void {
        const form = container.querySelector<HTMLFormElement>('form[data-workflow-node-config-form="true"]');
        if (!form) return;

        const scheduleSave = (event: Event) => {
            this.scheduleNodeConfigSave(
                form,
                this.shouldRefreshNodeConfigFormForEvent(event),
            );
        };
        form.addEventListener('change', scheduleSave);
        form.addEventListener(BaseWidget.changeEventName, scheduleSave);
        form.querySelectorAll<HTMLButtonElement>('[data-workflow-config-edit-mode]').forEach((button) => {
            button.addEventListener('click', () => {
                const editMode = button.dataset.workflowConfigEditMode;
                if (editMode !== 'form' && editMode !== 'json') return;
                if (editMode === form.dataset.editMode) return;
                void this.switchNodeConfigEditMode(form, editMode);
            });
        });
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            event.stopImmediatePropagation();
            void this.saveNodeConfigForm(form, true);
        }, true);
    }

    private shouldRefreshNodeConfigFormForEvent(event: Event): boolean {
        const target = event.target;
        if (!(target instanceof Element)) return true;

        return !target.closest('[bloomerp-component="code-editor-widget"]');
    }

    private async switchNodeConfigEditMode(form: HTMLFormElement, editMode: 'form' | 'json'): Promise<void> {
        const drawflowNodeId = this.editingNodeId;
        if (!drawflowNodeId) return;

        const updatedData = this.updateNodeConfigFromForm(drawflowNodeId, form);
        if (!updatedData) return;

        this.setNodeConfigStatus(form, 'Switching editor...');
        if (this.nodeConfigAutosaveTimer) {
            window.clearTimeout(this.nodeConfigAutosaveTimer);
            this.nodeConfigAutosaveTimer = null;
        }
        await this.saveWorkflow();

        const persistedNodeData = this.drawflow.getNodeFromId(drawflowNodeId);
        if (!persistedNodeData) return;

        const target = form.parentElement as HTMLElement | null;
        if (!target) return;

        this.nodeFormEditMode = editMode;
        this.loadNodeConfigFormForNode(persistedNodeData, target, editMode);
    }

    private scheduleNodeConfigSave(form: HTMLFormElement, refreshForm: boolean = false): void {
        this.setNodeConfigStatus(form, 'Saving changes...');
        this.refreshNodeConfigFormOnNextSave ||= refreshForm;
        this.pendingNodeConfigForm = form;

        if (this.nodeConfigAutosaveTimer) {
            window.clearTimeout(this.nodeConfigAutosaveTimer);
        }

        this.nodeConfigAutosaveTimer = window.setTimeout(() => {
            this.nodeConfigAutosaveTimer = null;
            this.pendingNodeConfigForm = null;
            const shouldRefreshForm = this.refreshNodeConfigFormOnNextSave;
            this.refreshNodeConfigFormOnNextSave = false;
            void this.saveNodeConfigForm(form, shouldRefreshForm);
        }, 600);
    }

    private async saveNodeConfigForm(form: HTMLFormElement, refreshForm: boolean = false): Promise<void> {
        const currentVersion = ++this.nodeConfigSaveVersion;
        const drawflowNodeId = this.editingNodeId;
        if (!drawflowNodeId) return;

        const updatedData = this.updateNodeConfigFromForm(drawflowNodeId, form);
        if (!updatedData) return;

        this.setNodeConfigStatus(form, 'Saving changes...');
        await this.saveWorkflow();

        const persistedNodeData = this.drawflow.getNodeFromId(drawflowNodeId);
        const workflowNodeId = persistedNodeData?.data?.workflowNodeId;
        if (!workflowNodeId || currentVersion !== this.nodeConfigSaveVersion) return;

        await this.refreshNodeSchemaPanel(form, workflowNodeId, refreshForm);
        this.setNodeConfigStatus(form, 'All changes saved.');
    }

    private updateNodeConfigFromForm(drawflowNodeId: number, form: HTMLFormElement): any | null {
        const nodeData = this.drawflow.getNodeFromId(drawflowNodeId);
        if (!nodeData) return null;

        const parameters = this.formToParameters(form);
        if (!parameters) return null;
        const updatedData = {
            ...nodeData.data,
            parameters,
        };
        this.drawflow.updateNodeDataFromId(drawflowNodeId, updatedData);
        this.refreshNodeCard(drawflowNodeId, updatedData);
        return updatedData;
    }

    private async refreshNodeSchemaPanel(
        form: HTMLFormElement,
        workflowNodeId: number,
        refreshForm: boolean = false,
    ): Promise<void> {
        const panel = form.querySelector<HTMLElement>('[data-workflow-node-schema-panel]');
        if (!panel) return;

        const params = new URLSearchParams({
            node_id: String(workflowNodeId),
            edit_mode: form.dataset.editMode || this.nodeFormEditMode,
        });
        if (refreshForm) {
            params.set('refresh_form', '1');
        }
        await htmx.ajax(
            'get',
            `/components/automation/render_workflow_node_schema_panel/?${params.toString()}`,
            panel,
        );
        const refreshedPanel = form.querySelector<HTMLElement>('[data-workflow-node-schema-panel]');
        if (refreshedPanel) initComponents(refreshedPanel);
        const refreshedFormFields = form.querySelector<HTMLElement>('#workflow-node-form');
        if (refreshedFormFields) initComponents(refreshedFormFields);
    }

    private setNodeConfigStatus(form: HTMLFormElement, message: string): void {
        const status = form.querySelector<HTMLElement>('[data-workflow-node-config-status]');
        if (status) status.textContent = message;
    }

    private refreshNodeCard(nodeId: number, nodeData: any): void {
        const nodeElement = this.element.querySelector<HTMLElement>(`#node-${nodeId}`);
        const content = nodeElement?.querySelector<HTMLElement>('.node-content');
        if (!content || content.querySelector('input[aria-label="Node name"]')) return;

        const definition = nodeData.nodeDefinition || this.getNodeDefinition(nodeData.nodeType, nodeData.nodeSubType);
        const html = createNodeHtml(
            nodeData.nodeType,
            nodeData.nodeSubType,
            nodeId,
            definition,
            nodeData.parameters,
            nodeData.workflowNodeId,
            nodeData.nodeName,
        );
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html;
        const newContent = wrapper.firstElementChild;
        if (newContent) content.replaceWith(newContent);
    }

    private formToParameters(form: HTMLFormElement): Record<string, any> | null {
        if (form.dataset.editMode === 'json') {
            const input = form.querySelector<HTMLTextAreaElement | HTMLInputElement>('[name="parameters"]');
            const rawValue = input?.value?.trim() || '';
            if (!rawValue) return {};

            try {
                const parsed = JSON.parse(rawValue);
                if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
                    this.setNodeConfigStatus(form, 'JSON config must be an object.');
                    return null;
                }
                return parsed;
            } catch {
                this.setNodeConfigStatus(form, 'JSON is invalid; changes not saved.');
                return null;
            }
        }

        const formData = new FormData(form);
        const parameters: Record<string, any> = {};
        const multiValueFieldNames = new Set(
            Array.from(form.querySelectorAll<HTMLElement>(
                'select[multiple][name], [bloomerp-component="foreign-field-widget"][data-is-m2m="true"][data-field-name]',
            )).map((field) => field.getAttribute('name') || field.dataset.fieldName || ''),
        );

        formData.forEach((value, key) => {
            if (key === 'csrfmiddlewaretoken') return;
            const parsedValue = this.parseFormValue(String(value));

            if (!(key in parameters)) {
                parameters[key] = multiValueFieldNames.has(key) ? [parsedValue] : parsedValue;
                return;
            }

            const currentValue = parameters[key];
            parameters[key] = Array.isArray(currentValue)
                ? [...currentValue, parsedValue]
                : [currentValue, parsedValue];
        });

        return parameters;
    }
    

    // TODO: Move to utility function
    private parseFormValue(value: string): any {
        if (/^-?\d+$/.test(value)) return parseInt(value, 10);

        const trimmed = value.trim();
        if (
            (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
            (trimmed.startsWith('[') && trimmed.endsWith(']'))
        ) {
            try {
                return JSON.parse(trimmed);
            } catch {
                return value;
            }
        }

        return value;
    }
}
