/**
 * Bloomerp Main TypeScript Entry Point
 * 
 * This file serves as the main entry point for all TypeScript modules.
 * It sets up HTMX event listeners to handle dynamically loaded content
 * and initializes modules as needed.
 */
import 'htmx.org';
import 'drawflow/dist/drawflow.min.css';

import { registerComponent, setupComponentAutoInit } from './components/BaseComponent';
import { Modal } from './components/Modal';
import { Drawer } from './components/Drawer';
import { Sidebar } from './components/Sidebar';
import { DataTable } from './components/data_view_components/DataTable'
import { DataTableCell } from './components/data_view_components/DataTable'
import { DataViewContainer } from './components/data_view_components/DataViewContainer';
import { KanbanBoard } from './components/data_view_components/KanbanBoard';
import { KanbanCard } from './components/data_view_components/KanbanBoard';
import { CardView } from './components/data_view_components/CardView';
import { CardViewCard } from './components/data_view_components/CardView';
import { PermissionsTable } from './components/PermissionsTable';
import FilterContainer from './components/Filters';
import TextEditor from './components/inputs/TextEditor';
import WebsiteBuilder from './components/WebsiteBuilder';
import PermissionCheckboxes from './components/inputs/PermissionCheckboxes';
import DropdownInput from './components/inputs/DropdownInput';
import SelectableCards from './components/inputs/SelectableCards';
import ForeignFieldWidget from './components/widgets/ForeignFieldWidget';
import CodeEditorWidget from './components/widgets/CodeEditorWidget';
import IconPickerWidget from './components/widgets/IconPickerWidget';
import UiMessage from './components/UiMessage';
import ObjectDetailViewContainer from './components/detail_view_components/ObjectDetailViewContainer';
import { DetailViewCell } from './components/detail_view_components/DetailViewCell';
import DetailTabs from './components/detail_view_components/DetailTabs';
import Workflow from './components/workflows/Workflow';
import GlobalSearch from './components/GlobalSearch';
import { initMessagesWebsocket } from './modules/messages';
import WorkspaceContainer from './components/workspaces/WorkspaceContainer';
import WorkspaceTile from './components/workspaces/WorkspaceTile';
import SqlQueryEditor from './components/inputs/SqlQueryEditor';
import Canvas from './components/workspaces/tiles/Canvas';

// Register components here
registerComponent('modal', Modal);
registerComponent('drawer', Drawer);
registerComponent('sidebar', Sidebar);

// Dataview component
registerComponent('dataview-container', DataViewContainer);

// Datatable
registerComponent('datatable', DataTable);
registerComponent('datatable-cell', DataTableCell);

// Kanban
registerComponent('kanban-board', KanbanBoard);
registerComponent('kanban-card', KanbanCard);

// Card view
registerComponent('card-view', CardView);
registerComponent('card-view-card', CardViewCard);

// Permissions table
registerComponent('permissions-table', PermissionsTable)

// Filter container
registerComponent('filter-container', FilterContainer)

// Textfield
registerComponent('text-editor', TextEditor)

// Website builder
registerComponent('website-builder', WebsiteBuilder)

// Permission checkboxes
registerComponent('permission-checkboxes', PermissionCheckboxes)

// Dropdown input
registerComponent('dropdown-input', DropdownInput);

// Selectable cards
registerComponent('selectable-cards', SelectableCards);

// Form widgets
registerComponent('foreign-field-widget', ForeignFieldWidget);
registerComponent('code-editor-widget', CodeEditorWidget);
registerComponent('icon-picker-widget', IconPickerWidget);

// Messages
registerComponent('ui-message', UiMessage);

// Detail view
registerComponent('object-detail-view-container', ObjectDetailViewContainer);
registerComponent('detail-view-value', DetailViewCell);
registerComponent('detail-tabs', DetailTabs);

// Workflow
registerComponent('workflow', Workflow);

// Global search
registerComponent('global-search-modal', GlobalSearch);

// Workspace components
registerComponent('workspace-container', WorkspaceContainer);
registerComponent('workspace-tile', WorkspaceTile);

registerComponent('sql-query-editor', SqlQueryEditor);

registerComponent('workspace-tile-canvas', Canvas);

// Auto init comonents
setupComponentAutoInit();


// Realtime messages
initMessagesWebsocket();
