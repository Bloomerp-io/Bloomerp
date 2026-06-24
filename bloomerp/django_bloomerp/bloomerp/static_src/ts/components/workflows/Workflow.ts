import getGeneralModal from "@/utils/modals";
import { getCsrfToken } from "@/utils/cookies";
import BaseComponent, { getComponent, initComponents } from "../BaseComponent";
import { BaseWidget } from "../widgets/BaseWidget";
import { Drawer } from "../Drawer";
import DrawFlow from 'drawflow';
import htmx from "htmx.org";
import getSdk from "@/sdk/getSdk";

interface SavedWorkflowNode {
    id: number;
    client_id: string;
    type: string;
    name?: string | null;
    config: WorkflowNodeConfig;
    pos_x: number;
    pos_y: number;
}

interface SavedWorkflowEdge {
    id?: number;
    from_node: string;
    to_node: string;
    name?: string | null;
}

interface SavedWorkflow {
    workflow_id?: number;
    name?: string;
    nodes?: SavedWorkflowNode[];
    edges?: SavedWorkflowEdge[];
}

interface WorkflowNodeConfig {
    sub_type?: string;
    parameters?: Record<string, any>;
}

interface WorkflowNodeDefinition {
    typeId: string;
    typeName: string;
    subTypeId: string;
    subTypeName: string;
    description: string;
    icon: string;
}

interface WorkflowEdgeMetadata {
    id?: number;
    name: string;
}

const WORKFLOW_CANVAS_WIDTH = 4000;
const WORKFLOW_CANVAS_HEIGHT = 3000;
const WORKFLOW_CANVAS_OFFSET_X = 1200;
const WORKFLOW_CANVAS_OFFSET_Y = 900;
const WORKFLOW_DEFAULT_ZOOM_STEP = 0.05;
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

function getConnectionInfoFromElement(connectionElement: Element): {
    fromNodeId: string;
    toNodeId: string;
    outputClass: string;
    inputClass: string;
} | null {
    const classes = Array.from(connectionElement.classList);
    const toNodeClass = classes.find((className) => className.startsWith('node_in_node-'));
    const fromNodeClass = classes.find((className) => className.startsWith('node_out_node-'));
    const outputClass = classes.find((className) => className.startsWith('output_')) || 'output_1';
    const inputClass = classes.find((className) => className.startsWith('input_')) || 'input_1';

    if (!fromNodeClass || !toNodeClass) return null;

    return {
        fromNodeId: fromNodeClass.replace('node_out_node-', ''),
        toNodeId: toNodeClass.replace('node_in_node-', ''),
        outputClass,
        inputClass,
    };
}

function createConfigSummary(config?: WorkflowNodeConfig): string {
    const parameters = config?.parameters || {};
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
    config?: WorkflowNodeConfig,
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
                <div class="workflow-node-config">${createConfigSummary(config)}</div>
            </div>
        </div>
    `;
}

interface Coordinates {
    x:number,
    y:number
}

function createRandomCoordinates() : Coordinates {
    return {
        x: Math.random() * 300 + WORKFLOW_CANVAS_OFFSET_X + 120,
        y: Math.random() * 200 + WORKFLOW_CANVAS_OFFSET_Y + 120,
    }
}

function safePosition(value: any): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.round(parsed) : 0;
}

export default class Workflow extends BaseComponent {
    private drawflow: DrawFlow;
    private nodeId: number = 1;
    private workflowId: string | null = null;
    private workflowName: string = 'Workflow';
    private editingNodeId: number | null = null;
    private nodeDefinitions: Map<string, WorkflowNodeDefinition> = new Map();
    private edgeMetadata: Map<string, WorkflowEdgeMetadata> = new Map();
    private isImportingWorkflow: boolean = false;
    private autosaveTimer: number | null = null;
    private nodeConfigAutosaveTimer: number | null = null;
    private nodeConfigSaveVersion: number = 0;
    private refreshNodeConfigFormOnNextSave: boolean = false;
    private saveInFlight: Promise<void> | null = null;
    private saveAgainAfterCurrent: boolean = false;
    private nodeDrawerLoadPromise: Promise<void> | null = null;

    private nodeFormEditMode: 'form' | 'json' = 'form';


    public initialize(): void {
        if (!this.element) return;

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
        this.workflowId = this.element.getAttribute('data-workflow-id');
        this.buildNodeDefinitions();
        this.importSavedWorkflow();
        
        
        // Setup toolbar buttons
        this.setupToolbar();

        // Setup double-click handler for nodes
        this.setupNodeDoubleClickHandler();

        // Setup context menu for nodes
        this.setupNodeContextMenu();
        this.setupEdgeContextMenu();

        //
        this.setupNodeDrawer();
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
            });
        });
    }

    private nodeDefinitionKey(nodeType: string, nodeSubType: string): string {
        return `${nodeType}:${nodeSubType}`;
    }

    private getNodeDefinition(nodeType: string, nodeSubType: string): WorkflowNodeDefinition | undefined {
        return this.nodeDefinitions.get(this.nodeDefinitionKey(nodeType, nodeSubType));
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
        this.isImportingWorkflow = true;

        for (const node of workflow.nodes || []) {
            const drawflowId = parseDrawflowClientId(String(node.client_id)) || node.id;
            const nodeSubType = node.config?.sub_type || '';
            const definition = this.getNodeDefinition(node.type, nodeSubType);
            const nodeData = {
                workflowNodeId: node.id,
                nodeType: node.type,
                nodeSubType,
                nodeName: node.name || '',
                nodeDefinition: definition,
                config: node.config || { sub_type: nodeSubType, parameters: {} },
            };
            const inputs = node.type === 'TRIGGER' ? 0 : 1;

            const addedNodeId = Number(this.drawflow.addNode(
                node.type,
                inputs,
                1,
                toCanvasPosition(node.pos_x, WORKFLOW_CANVAS_OFFSET_X),
                toCanvasPosition(node.pos_y, WORKFLOW_CANVAS_OFFSET_Y),
                `${node.type}-${drawflowId}`,
                nodeData,
                createNodeHtml(node.type, nodeSubType, drawflowId, definition, nodeData.config, node.id, node.name),
                false
            ));

            nodeIdMap.set(node.client_id, addedNodeId);
            maxNodeId = Math.max(maxNodeId, addedNodeId);
        }

        for (const edge of workflow.edges || []) {
            const fromNode = nodeIdMap.get(edge.from_node);
            const toNode = nodeIdMap.get(edge.to_node);
            if (!fromNode || !toNode) continue;
            this.drawflow.addConnection(fromNode, toNode, 'output_1', 'input_1');
            this.edgeMetadata.set(
                createWorkflowEdgeKey(fromNode, toNode),
                {
                    id: edge.id,
                    name: edge.name || '',
                },
            );
        }

        this.nodeId = Math.max(this.nodeId, maxNodeId + 1);
        this.isImportingWorkflow = false;
        this.refreshWorkflowEdgeLabels();
        this.fitWorkflowToViewport();
    }

    private setupCanvasWorkspace(container: HTMLElement): void {
        const precanvas = (this.drawflow as any).precanvas as HTMLElement | null;
        if (!precanvas) return;

        precanvas.style.width = `${WORKFLOW_CANVAS_WIDTH}px`;
        precanvas.style.height = `${WORKFLOW_CANVAS_HEIGHT}px`;
        precanvas.style.minWidth = `${WORKFLOW_CANVAS_WIDTH}px`;
        precanvas.style.minHeight = `${WORKFLOW_CANVAS_HEIGHT}px`;
        precanvas.style.transformOrigin = '0 0';

        (this.drawflow as any).zoom_value = WORKFLOW_DEFAULT_ZOOM_STEP;

        const initialCanvasX = Math.round((container.clientWidth / 2) - WORKFLOW_CANVAS_OFFSET_X);
        const initialCanvasY = Math.round((container.clientHeight / 2) - WORKFLOW_CANVAS_OFFSET_Y);
        (this.drawflow as any).canvas_x = initialCanvasX;
        (this.drawflow as any).canvas_y = initialCanvasY;
        precanvas.style.transform = `translate(${(this.drawflow as any).canvas_x}px, ${(this.drawflow as any).canvas_y}px) scale(${(this.drawflow as any).zoom})`;
    }

    private fitWorkflowToViewport(): void {
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
                const left = safePosition(nodeElement.style.left);
                const top = safePosition(nodeElement.style.top);
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
            const fitZoom = Math.min(
                WORKFLOW_FIT_MAX_ZOOM,
                Math.max(
                    WORKFLOW_FIT_MIN_ZOOM,
                    Math.min(availableWidth / contentWidth, availableHeight / contentHeight),
                ),
            );

            const contentCenterX = minX + (contentWidth / 2);
            const contentCenterY = minY + (contentHeight / 2);
            const canvasX = Math.round((container.clientWidth / 2) - (contentCenterX * fitZoom));
            const canvasY = Math.round((container.clientHeight / 2) - (contentCenterY * fitZoom));

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
    private setupNodeContextMenu(): void {
        const container = this.element.querySelector('#drawflow') as HTMLElement;
        if (!container) return;

        container.addEventListener('contextmenu', (e: MouseEvent) => {
            const target = e.target as HTMLElement;
            const nodeElement = target.closest('.drawflow-node') as HTMLElement;

            if (nodeElement) {
                const nodeId = parseInt(nodeElement.getAttribute('id')?.replace('node-', '') || '0');
                const nodeData = this.drawflow.getNodeFromId(nodeId);
                if (!nodeData) return;

                // Get the title element and turn it into an editable input
                const titleElement = nodeElement.querySelector('.workflow-node-title') as HTMLElement;
                if (titleElement) {
                    e.preventDefault();
                    e.stopPropagation();
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

                        await this.flushAutosave();
                        const persistedNodeData = this.drawflow.getNodeFromId(nodeId);
                        const workflowNodeId = persistedNodeData?.data?.workflowNodeId;
                        if (!workflowNodeId) return;

                        try {
                            const savedNode = await getSdk().workflowNodes.partialUpdate(
                                workflowNodeId,
                                { name: nextName || null },
                            );
                            const refreshedNodeData = this.drawflow.getNodeFromId(nodeId);
                            if (!refreshedNodeData) return;
                            const savedData = {
                                ...refreshedNodeData.data,
                                nodeName: savedNode.name || '',
                            };
                            this.drawflow.updateNodeDataFromId(nodeId, savedData);
                            this.refreshNodeCard(nodeId, savedData);
                        } catch (error) {
                            console.error('Failed to rename workflow node', error);
                            const revertedData = {
                                ...this.drawflow.getNodeFromId(nodeId)?.data,
                                nodeName: currentName,
                            };
                            this.drawflow.updateNodeDataFromId(nodeId, revertedData);
                            this.refreshNodeCard(nodeId, revertedData);
                        }
                    };

                    input.addEventListener('click', (event) => event.stopPropagation());
                    input.addEventListener('dblclick', (event) => event.stopPropagation());
                    input.addEventListener('contextmenu', (event) => event.stopPropagation());
                    input.addEventListener('keydown', (event: KeyboardEvent) => {
                        if (event.key === 'Enter') {
                            event.preventDefault();
                            void finishEditing(true);
                        }
                        if (event.key === 'Escape') {
                            event.preventDefault();
                            void finishEditing(false);
                        }
                    });
                    input.addEventListener('blur', () => void finishEditing(true));

                    titleElement.replaceWith(input);
                    input.focus();
                    input.select();
                }

            }
        });
    }

    private setupEdgeContextMenu(): void {
        const container = this.element.querySelector('#drawflow') as HTMLElement;
        if (!container) return;

        container.addEventListener('contextmenu', (event: MouseEvent) => {
            const target = event.target as HTMLElement;
            const label = target.closest<HTMLElement>('[data-workflow-edge-label]');
            const connectionPath = target.closest<SVGPathElement>('.main-path');
            const connectionElement = label
                ? getConnectionElement(
                    container,
                    label.dataset.fromNodeId || '',
                    label.dataset.toNodeId || '',
                    label.dataset.outputClass || 'output_1',
                    label.dataset.inputClass || 'input_1',
                )
                : connectionPath?.closest<SVGElement>('.connection');

            if (!connectionElement) return;

            const edgeInfo = getConnectionInfoFromElement(connectionElement);
            if (!edgeInfo) return;

            event.preventDefault();
            event.stopPropagation();
            void this.startEditingWorkflowEdge(edgeInfo);
        });
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
            await this.flushAutosave();

            const persistedMetadata = this.edgeMetadata.get(edgeKey);
            if (!persistedMetadata?.id) return;

            try {
                const savedEdge = await (getSdk().workflowEdges as any).partialUpdate(
                    persistedMetadata.id,
                    { name: nextName || null },
                );
                this.edgeMetadata.set(edgeKey, {
                    id: savedEdge.id || persistedMetadata.id,
                    name: savedEdge.name || '',
                });
                this.refreshWorkflowEdgeLabels();
            } catch (error) {
                console.error('Failed to rename workflow edge', error);
                this.edgeMetadata.set(edgeKey, currentMetadata);
                this.refreshWorkflowEdgeLabels();
            }
        };

        textarea.addEventListener('click', (event) => event.stopPropagation());
        textarea.addEventListener('dblclick', (event) => event.stopPropagation());
        textarea.addEventListener('contextmenu', (event) => event.stopPropagation());
        textarea.addEventListener('keydown', (event: KeyboardEvent) => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                void finishEditing(true);
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                void finishEditing(false);
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
            label.remove();
        });

        container.querySelectorAll<SVGElement>('.connection').forEach((connectionElement) => {
            const edgeInfo = getConnectionInfoFromElement(connectionElement);
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
            zoomInBtn.addEventListener('click', () => this.drawflow.zoom_in());
        }
        
        if (zoomOutBtn) {
            zoomOutBtn.addEventListener('click', () => this.drawflow.zoom_out());
        }
        
        if (zoomResetBtn) {
            zoomResetBtn.addEventListener('click', () => this.drawflow.zoom_reset());
        }
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
        const edges: Array<{ id?: number; from_node: string; to_node: string; name?: string | null }> = [];
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
                config: {
                    sub_type: node.data?.nodeSubType,
                    parameters: node.data?.config?.parameters || {},
                },
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
                        if (!drawflowId) continue;
                        const drawflowNode = this.drawflow.getNodeFromId(drawflowId);
                        if (drawflowNode) {
                            const updatedData = {
                                ...drawflowNode.data,
                                workflowNodeId: node.id,
                                nodeName: node.name || '',
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

        this.edgeMetadata.clear();
        for (const edge of savedWorkflow.edges || []) {
            const fromNodeId = drawflowIdByClientId.get(edge.from_node);
            const toNodeId = drawflowIdByClientId.get(edge.to_node);
            if (!fromNodeId || !toNodeId) continue;

            const edgeKey = createWorkflowEdgeKey(fromNodeId, toNodeId);
            const previousMetadata = existingMetadata.get(edgeKey);
            this.edgeMetadata.set(edgeKey, {
                id: edge.id,
                name: edge.name ?? previousMetadata?.name ?? '',
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
        const coordinates = createRandomCoordinates() 
        let numberOfInputs = 1;
        const definition = this.getNodeDefinition(nodeType, nodeSubType);
        const config = {
            sub_type: nodeSubType,
            parameters: {},
        };

        if (nodeType==='TRIGGER') {
            numberOfInputs=0
        }

        this.drawflow.addNode(
            nodeType,
            numberOfInputs,
            1,
            coordinates.x,
            coordinates.y,
            `${nodeType}-${this.nodeId}`,
            {
                nodeType,
                nodeSubType,
                nodeDefinition: definition,
                nodeName: '',
                config,
            },
            createNodeHtml(nodeType, nodeSubType, this.nodeId, definition, config),
            false
        );
                
        this.nodeId++;
    }

    private getNodeDrawer(): Drawer | null {
        const drawerElement = this.element.querySelector<HTMLElement>('#node-drawer');
        if (!drawerElement) return null;
        return getComponent(drawerElement) as Drawer | null;
    }

    private getNodeDrawerContent(): HTMLElement | null {
        return this.element.querySelector<HTMLElement>('[data-workflow-drawer-content]');
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

        if (this.nodeConfigAutosaveTimer) {
            window.clearTimeout(this.nodeConfigAutosaveTimer);
        }

        this.nodeConfigAutosaveTimer = window.setTimeout(() => {
            this.nodeConfigAutosaveTimer = null;
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
        const config = {
            sub_type: nodeData.data?.nodeSubType,
            parameters,
        };

        const updatedData = {
            ...nodeData.data,
            config,
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
        if (!content) return;

        const definition = nodeData.nodeDefinition || this.getNodeDefinition(nodeData.nodeType, nodeData.nodeSubType);
        const html = createNodeHtml(
            nodeData.nodeType,
            nodeData.nodeSubType,
            nodeId,
            definition,
            nodeData.config,
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

        formData.forEach((value, key) => {
            if (key === 'csrfmiddlewaretoken') return;
            parameters[key] = this.parseFormValue(String(value));
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


    /**
     * Opens a node editor/configuration panel
     * This is a placeholder that should be replaced with your actual implementation
     */
    private openNodeEditor(nodeId: number, nodeType: string, nodeSubType: string, data: any): void {
        // TODO: Implement the actual node editor
        // This could be a modal, a sidebar panel, or navigate to a different page
        
        console.log('Opening node editor for:', { nodeId, nodeType, nodeSubType, data });
        
        // Placeholder: show an alert for now
        alert(`Node Editor\n\nNode ID: ${nodeId}\nType: ${nodeType}\nSubtype: ${nodeSubType}\n\nDouble-click handler working!`);
        
        // Example: You might want to:
        // 1. Open a modal with a form for this node type
        // 2. Make an HTMX request to load a configuration panel
        // 3. Dispatch a custom event that another component can listen to
        // 4. Update the node's data property with new configuration
    }



}
