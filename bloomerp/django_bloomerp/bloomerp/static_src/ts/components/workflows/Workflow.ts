import BaseComponent from "../BaseComponent";
import DrawFlow from 'drawflow';

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


export default class Workflow extends BaseComponent {
    private drawflow: DrawFlow;
    private nodeId: number = 1;
    private workflowId: string | null = null;

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
        
        // Add sample nodes with connections
        this.addSampleNodes();
        
        // Setup toolbar buttons
        this.setupToolbar();

        // Add event listeners
        this.addEventListeners();
        
        // Setup double-click handler for nodes
        this.setupNodeDoubleClickHandler();
        
        console.log('Workflow component initialized');
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
    
    private addSampleNodes(): void {
        // Start Node (ID will be 1)
        const startHtml = createNodeHtml('TRIGGER', 'ON_START', this.nodeId);
        const startId = this.drawflow.addNode('TRIGGER', 0, 1, 150, 100, 'start-node', { nodeType: 'TRIGGER', nodeSubType: 'ON_START' }, startHtml, false);
        this.nodeId++;
        
        // Process Node (ID will be 2)
        const processHtml = createNodeHtml('ACTION', 'PROCESS_DATA', this.nodeId);
        const processId = this.drawflow.addNode('ACTION', 1, 1, 400, 150, 'process-node', { nodeType: 'ACTION', nodeSubType: 'PROCESS_DATA' }, processHtml, false);
        this.nodeId++;
        
        // Decision Node (ID will be 3)
        const decisionHtml = createNodeHtml('FLOW', 'IF_CONDITION', this.nodeId);
        const decisionId = this.drawflow.addNode('FLOW', 1, 2, 700, 100, 'decision-node', { nodeType: 'FLOW', nodeSubType: 'IF_CONDITION' }, decisionHtml, false);
        this.nodeId++;
        
        // End Node (ID will be 4)
        const endHtml = createNodeHtml('ACTION', 'END', this.nodeId);
        const endId = this.drawflow.addNode('ACTION', 2, 0, 1000, 200, 'end-node', { nodeType: 'ACTION', nodeSubType: 'END' }, endHtml, false);
        this.nodeId++;
        
        // Create connections programmatically
        // Format: addConnection(fromNodeId, toNodeId, outputClass, inputClass)
        
        // Connect Start -> Process
        this.drawflow.addConnection(startId, processId, 'output_1', 'input_1');
        
        // Connect Process -> Decision
        this.drawflow.addConnection(processId, decisionId, 'output_1', 'input_1');
        
        // Connect Decision -> End (first output)
        this.drawflow.addConnection(decisionId, endId, 'output_1', 'input_1');
        
        // You can also connect Decision -> End (second output) if you want multiple paths
        // this.drawflow.addConnection(decisionId, endId, 'output_2', 'input_2');
        
        console.log('Created connections between nodes');
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
        const endpoint = `/components/automation/render_workflow_node/?node_type=${nodeType}&node_subtype=${nodeSubType}`;
        
        fetch(endpoint)
            .then(response => response.text())
            .then(html => {
                const posX = Math.random() * 300 + 200;
                const posY = Math.random() * 200 + 100;
                
                this.drawflow.addNode(
                    nodeType,
                    1,
                    1,
                    posX,
                    posY,
                    `${nodeType}-${this.nodeId}`,
                    { nodeType, nodeSubType },
                    html,
                    false
                );
                
                this.nodeId++;
            })
            .catch(error => {
                console.error('Error fetching node HTML:', error);
            });
    }

    /**
     * Handles double-click on a node to trigger node-specific actions
     * @param nodeId the ID of the double-clicked node
     */
    private handleNodeDoubleClick(nodeId: number): void {
        const nodeData = this.drawflow.getNodeFromId(nodeId);
        
        if (!nodeData) {
            console.error('Node not found:', nodeId);
            return;
        }

        const { data } = nodeData;
        const nodeType = data.nodeType;
        const nodeSubType = data.nodeSubType;

        console.log('Double-clicked node:', { nodeId, nodeType, nodeSubType, data });

        // Handle different node types
        switch (nodeType) {
            case 'TRIGGER':
                this.handleTriggerNodeAction(nodeId, nodeSubType, data);
                break;
            case 'ACTION':
                this.handleActionNodeAction(nodeId, nodeSubType, data);
                break;
            case 'FLOW':
                this.handleFlowNodeAction(nodeId, nodeSubType, data);
                break;
            default:
                console.warn('Unknown node type:', nodeType);
                this.openNodeEditor(nodeId, nodeType, nodeSubType, data);
        }
    }

    /**
     * Handle trigger node actions
     */
    private handleTriggerNodeAction(nodeId: number, nodeSubType: string, data: any): void {
        console.log('Trigger node action:', { nodeId, nodeSubType, data });
        
        // TODO: Open modal or panel to configure trigger settings
        // Examples: schedule configuration, webhook URL, event filters, etc.
        this.openNodeEditor(nodeId, 'TRIGGER', nodeSubType, data);
    }

    /**
     * Handle action node actions
     */
    private handleActionNodeAction(nodeId: number, nodeSubType: string, data: any): void {
        console.log('Action node action:', { nodeId, nodeSubType, data });
        
        // TODO: Open modal or panel to configure action settings
        // Examples: email template, API endpoint, record fields, etc.
        this.openNodeEditor(nodeId, 'ACTION', nodeSubType, data);
    }

    /**
     * Handle flow node actions
     */
    private handleFlowNodeAction(nodeId: number, nodeSubType: string, data: any): void {
        console.log('Flow node action:', { nodeId, nodeSubType, data });
        
        // TODO: Open modal or panel to configure flow logic
        // Examples: condition builder, switch cases, etc.
        this.openNodeEditor(nodeId, 'FLOW', nodeSubType, data);
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