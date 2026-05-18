import getGeneralModal from "@/utils/modals";
import { getCsrfToken } from "@/utils/cookies";
import BaseComponent from "../BaseComponent";
import DrawFlow from 'drawflow';
import htmx from "htmx.org";

interface WorkflowNode {
    id: number;
    name: string;
    posX: number;
    posY: number;
}

function createNodeHtml(nodeType: string, nodeSubType: string, nodeId: number): string {
    return `
        <div class="node-content">
            <div class="node-header">${nodeType} - ${nodeSubType}</div>
            <div class="node-body">
                <p>Node ID: ${nodeId}</p>
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

export default class Workflow extends BaseComponent {
    private drawflow: DrawFlow;
    private nodeId: number = 1;
    private workflowId: string | null = null;

    private saveWorkflowBtn: HTMLButtonElement

    public initialize(): void {
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
        });
        
        this.drawflow.on('connectionCreated', (info: any) => {
            console.log('Connection created:', info);
        });
        
        this.drawflow.on('nodeRemoved', (id: number) => {
            console.log('Node removed:', id);
        });
        
        this.drawflow.on('nodeSelected', (id: number) => {
            console.log('Node selected:', id);
        });
        
        // Create initial editor module
        this.drawflow.addModule('Home');
        this.drawflow.changeModule('Home');
        
        
        // Setup toolbar buttons
        this.setupToolbar();

        // Add event listeners
        this.addEventListeners();
        
        // Setup double-click handler for nodes
        this.setupNodeDoubleClickHandler();
        
        // Setup the sidebar
        this.element.querySelectorAll('[data-node-subtype-id]').forEach((el)=>{
            const nodeTypeId = el.getAttribute('data-node-type-id');
            const nodeSubTypeId = el.getAttribute('data-node-subtype-id')

            el.addEventListener('click', ()=>{
                this.addNode(nodeTypeId, nodeSubTypeId)
            })
        })

        this.workflowId = this.element.getAttribute('data-workflow-id');
        this.saveWorkflowBtn = this.element.querySelector('#save-workflow-btn')
        this.saveWorkflowBtn.addEventListener('click', () => void this.saveWorkflow());

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
                    this.handleNodeDoubleClick(nodeId);
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
        const data = this.drawflow.export();
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
            name: 'Workflow',
            nodes: nodes.map((node: any) => ({
                ...(node.data?.workflowNodeId ? { id: node.data.workflowNodeId } : {}),
                client_id: `node-${node.id}`,
                type: node.data?.nodeType || node.name,
                config: {
                    ...(node.data?.config || {}),
                    sub_type: node.data?.nodeSubType,
                },
                pos_x: node.pos_x,
                pos_y: node.pos_y,
            })),
            edges,
        };
    }

    private async saveWorkflow(): Promise<void> {
        const csrfToken = getCsrfToken();
        const payload = this.buildWorkflowPayload();

        try {
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
                    drawflowNode.data = {
                        ...drawflowNode.data,
                        workflowNodeId: node.id,
                    };
                }
            }
        } catch (error) {
            console.error('Failed to save workflow', error);
        }
    }

    private addEventListeners(): void {
        // Listen for clicks on workflow node buttons
        const nodeButtons = this.element.querySelectorAll('.workflow-node-btn');
        
        nodeButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                const target = e.currentTarget as HTMLElement;
                const nodeType = target.getAttribute('data-workflow-node-type');
                const nodeSubType = target.getAttribute('data-workflow-node-subtype');
                
                if (nodeType && nodeSubType) {
                    console.log('Adding node:', nodeType, nodeSubType);
                    this.addNode(nodeType, nodeSubType);
                }
            });
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
            { nodeType, nodeSubType },
            createNodeHtml(nodeType, nodeSubType, this.nodeId),
            false
        );
                
        this.nodeId++;
    }

    /**
     * Handles double-click on a node to trigger node-specific actions
     * @param nodeId the ID of the double-clicked node
     */
    private handleNodeDoubleClick(nodeId: number): void {
        let url = "/components/automation/render_workflow_node?"
        const nodeData = this.drawflow.getNodeFromId(nodeId);

        url += 'node_type=' + nodeData.data['nodeType'] + '&node_sub_type=' + nodeData.data['nodeSubType']
        
        // Get the general modal
        const modal = getGeneralModal()
        
        htmx.ajax(
            'get',
            url,
            {
                target: `#${modal.getBodyElement().id}`,
                swap: 'innerHTML'

            }
        )

        modal.open()

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
