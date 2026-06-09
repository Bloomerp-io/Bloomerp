import getGeneralModal from "@/utils/modals";
import { getCsrfToken } from "@/utils/cookies";
import BaseComponent, { getComponent, initComponents } from "../BaseComponent";
import { BaseWidget } from "../widgets/BaseWidget";
import { Drawer } from "../Drawer";
import DrawFlow from 'drawflow';
import htmx from "htmx.org";

interface SavedWorkflowNode {
    id: number;
    client_id: string;
    type: string;
    config: WorkflowNodeConfig;
    pos_x: number;
    pos_y: number;
}

interface SavedWorkflowEdge {
    from_node: string;
    to_node: string;
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
): string {
    const typeLabel = definition?.typeName || nodeType;
    const subTypeLabel = definition?.subTypeName || nodeSubType;
    const icon = definition?.icon || 'fa-solid fa-circle-nodes';
    const cardType = nodeType.toLowerCase();
    const persistedLabel = workflowNodeId ? `Saved #${workflowNodeId}` : `Draft #${nodeId}`;

    return `
        <div class="node-content workflow-node-card workflow-node-card--${escapeHtml(cardType)}">
            <div class="node-header workflow-node-header">
                <div class="workflow-node-icon"><i class="${escapeHtml(icon)}"></i></div>
                <div class="workflow-node-title-wrap">
                    <div class="workflow-node-kicker">${escapeHtml(typeLabel)}</div>
                    <div class="workflow-node-title">${escapeHtml(subTypeLabel)}</div>
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
        x:Math.random() * 300 + 200,
        y:Math.random() * 200 + 100
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
    private isImportingWorkflow: boolean = false;
    private autosaveTimer: number | null = null;
    private nodeConfigAutosaveTimer: number | null = null;
    private nodeConfigSaveVersion: number = 0;
    private refreshNodeConfigFormOnNextSave: boolean = false;
    private saveInFlight: Promise<void> | null = null;
    private saveAgainAfterCurrent: boolean = false;
    private nodeDrawerLoadPromise: Promise<void> | null = null;

    private saveWorkflowBtn: HTMLButtonElement

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
        
        // Register events
        this.drawflow.on('nodeCreated', (id: number) => {
            console.log('Node created:', id);
            this.scheduleAutosave();
        });
        
        this.drawflow.on('connectionCreated', (info: any) => {
            console.log('Connection created:', info);
            this.scheduleAutosave();
        });
        
        this.drawflow.on('nodeRemoved', (id: number) => {
            console.log('Node removed:', id);
            this.scheduleAutosave();
        });

        this.drawflow.on('connectionRemoved', (info: any) => {
            console.log('Connection removed:', info);
            this.scheduleAutosave();
        });

        this.drawflow.on('nodeMoved', (id: number) => {
            console.log('Node moved:', id);
            this.scheduleAutosave();
        });
        
        this.drawflow.on('nodeSelected', (id: number) => {
            console.log('Node selected:', id);
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
            const drawflowId = parseInt(String(node.client_id).replace('node-', ''), 10) || node.id;
            const nodeSubType = node.config?.sub_type || '';
            const definition = this.getNodeDefinition(node.type, nodeSubType);
            const nodeData = {
                workflowNodeId: node.id,
                nodeType: node.type,
                nodeSubType,
                nodeDefinition: definition,
                config: node.config || { sub_type: nodeSubType, parameters: {} },
            };
            const inputs = node.type === 'TRIGGER' ? 0 : 1;

            const addedNodeId = Number(this.drawflow.addNode(
                node.type,
                inputs,
                1,
                node.pos_x || 0,
                node.pos_y || 0,
                `${node.type}-${drawflowId}`,
                nodeData,
                createNodeHtml(node.type, nodeSubType, drawflowId, definition, nodeData.config, node.id),
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
        }

        this.nodeId = Math.max(this.nodeId, maxNodeId + 1);
        this.isImportingWorkflow = false;
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
        const edges: Array<{ from_node: string; to_node: string }> = [];

        for (const node of nodes) {
            const outputs = node.outputs || {};
            for (const output of Object.values(outputs) as Array<any>) {
                for (const connection of output.connections || []) {
                    edges.push({
                        from_node: `node-${node.id}`,
                        to_node: `node-${connection.node}`,
                    });
                }
            }
        }

        return {
            ...(this.workflowId ? { workflow_id: parseInt(this.workflowId, 10) } : {}),
            name: this.workflowName,
            nodes: nodes.map((node: any) => ({
                ...(node.data?.workflowNodeId ? { id: node.data.workflowNodeId } : {}),
                client_id: `node-${node.id}`,
                type: node.data?.nodeType || node.name,
                config: {
                    sub_type: node.data?.nodeSubType,
                    parameters: node.data?.config?.parameters || {},
                },
                pos_x: safePosition(node.pos_x),
                pos_y: safePosition(node.pos_y),
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
                        const drawflowId = parseInt(String(node.client_id).replace('node-', ''), 10);
                        const drawflowNode = this.drawflow.getNodeFromId(drawflowId);
                        if (drawflowNode) {
                            const updatedData = {
                                ...drawflowNode.data,
                                workflowNodeId: node.id,
                            };
                            this.drawflow.updateNodeDataFromId(drawflowId, updatedData);
                            this.refreshNodeCard(drawflowId, updatedData);
                        }
                    }
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
