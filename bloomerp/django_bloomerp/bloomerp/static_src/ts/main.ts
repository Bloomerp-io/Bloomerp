/**
 * Bloomerp Main TypeScript Entry Point
 * 
 * This file serves as the main entry point for all TypeScript modules.
 * It sets up HTMX event listeners to handle dynamically loaded content
 * and initializes modules as needed.
 */
import 'htmx.org';

import { registerComponent, setupComponentAutoInit } from './components/BaseComponent';
import { Modal } from './components/Modal';
import { Sidebar } from './components/Sidebar';
import { DataTable } from './components/data_view_components/DataTable'
import { DataTableCell } from './components/data_view_components/DataTable'
import { DataViewContainer } from './components/data_view_components/DataViewContainer';
import { KanbanBoard } from './components/data_view_components/KanbanBoard';
import { KanbanCard } from './components/data_view_components/KanbanBoard';
import { PermissionsTable } from './components/PermissionsTable';
import FilterContainer from './components/Filters';
import TextEditor from './components/inputs/TextEditor';
import WebsiteBuilder from './components/WebsiteBuilder';
import PermissionCheckboxes from './components/inputs/PermissionCheckboxes';
import DropdownInput from './components/inputs/DropdownInput';
import ForeignFieldWidget from './components/widgets/ForeignFieldWidget';

// Register components here
registerComponent('modal', Modal);
registerComponent('sidebar', Sidebar);

// Dataview component
registerComponent('dataview-container', DataViewContainer);

// Datatable
registerComponent('datatable', DataTable);
registerComponent('datatable-cell', DataTableCell);

// Kanban
registerComponent('kanban-board', KanbanBoard);
registerComponent('kanban-card', KanbanCard);

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

// Form widgets
registerComponent('foreign-field-widget', ForeignFieldWidget);


// Auto init comonents
setupComponentAutoInit();