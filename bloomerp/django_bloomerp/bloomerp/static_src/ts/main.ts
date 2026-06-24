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
import { Sidebar } from './components/sidebar/Sidebar';
import { DataTable } from './components/data_view_components/DataTable'
import { DataTableCell } from './components/data_view_components/DataTable'
import { DataViewContainer } from './components/data_view_components/DataViewContainer';
import { KanbanBoard } from './components/data_view_components/KanbanBoard';
import { KanbanCard } from './components/data_view_components/KanbanBoard';
import { CardView } from './components/data_view_components/CardView';
import { CardViewCard } from './components/data_view_components/CardView';
import { PermissionsTable } from './components/PermissionsTable';
import FilterContainer from './components/Filters';
import WebsiteBuilder from './components/WebsiteBuilder';
import PermissionCheckboxes from './components/inputs/PermissionCheckboxes';
import DropdownInput from './components/inputs/DropdownInput';
import SelectableCards from './components/inputs/SelectableCards';
import ForeignFieldWidget from './components/widgets/ForeignFieldWidget';
import ListFilterWidget from './components/widgets/ListFilterWidget';
import OneToManyFieldWidget from './components/widgets/OneToManyFieldWidget';
import CodeEditorWidget from './components/widgets/CodeEditorWidget';
import IconPickerWidget from './components/widgets/IconPickerWidget';
import AddressFieldWidget from './components/widgets/AddressFieldWidget';
import UiMessage from './components/UiMessage';
import ObjectCRUDViewContainer from './components/detail_view_components/ObjectCRUDViewContainer';
import { DetailViewCell } from './components/detail_view_components/DetailViewCell';
import DetailTabs from './components/detail_view_components/DetailTabs';
import DetailViewFrame from './components/detail_view_components/DetailViewFrame';
import Workflow from './components/workflows/Workflow';
import GlobalSearch from './components/GlobalSearch';
import SearchSection from './components/SearchSection';
import { initMessagesWebsocket } from './modules/messages';
import WorkspaceContainer from './components/workspaces/WorkspaceContainer';
import WorkspaceTile from './components/workspaces/WorkspaceTile';
import SqlQueryEditor from './components/inputs/SqlQueryEditor';
import Canvas from './components/workspaces/tiles/Canvas';
import FileBrowser from './components/files/FileBrowser';
import DocumentTemplateDataViewContainer from './components/data_view_components/DocumentTemplateDataViewContainer';
import { SidebarItem } from './components/sidebar/SidebarItem';
import FocusIn from './components/inputs/FocusIn';
import ShortcutTooltip from './components/ShortcutTooltip';
import OrderedFieldSelect from './components/inputs/OrderedFieldSelect';
import FocusOnForm from './components/FocusOnForm';
import { BloomerpTextEditor } from './components/text_editor/BloomerpTextEditor';
import { DocumentTemplateBuilder } from './components/DocumentTemplateBuilder';
import { SetupAnimationListener } from './utils/animations';
import BaseWizard from './components/BaseWizard';
import showMessage from './utils/messages';
import Breadcrumb from './components/Breadcrumb';
import ResizableDiv from './components/ResizableDiv';
import { DataViewDisplayOptions } from './components/data_view_components/DisplayOptions';

import { openModal } from './utils/modals';
import { closeModal } from './utils/modals';

Object.assign(window, { showMessage });

// Register components here
registerComponent('modal', Modal);
registerComponent('drawer', Drawer);
registerComponent('sidebar', Sidebar);
registerComponent('breadcrumb', Breadcrumb);
registerComponent('resizable-div', ResizableDiv);

// Dataview component
registerComponent('dataview-container', DataViewContainer);
registerComponent('document-templates-dataview', DocumentTemplateDataViewContainer);
registerComponent('dataview-display-options', DataViewDisplayOptions);

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

// Website builder
registerComponent('website-builder', WebsiteBuilder)
registerComponent('document-template-builder', DocumentTemplateBuilder)

// Permission checkboxes
registerComponent('permission-checkboxes', PermissionCheckboxes)

// Dropdown input
registerComponent('dropdown-input', DropdownInput);

// Selectable cards
registerComponent('selectable-cards', SelectableCards);

// Form widgets
registerComponent('foreign-field-widget', ForeignFieldWidget);
registerComponent('list-filter-widget', ListFilterWidget);
registerComponent('one-to-many-field-widget', OneToManyFieldWidget);
registerComponent('code-editor-widget', CodeEditorWidget);
registerComponent('icon-picker-widget', IconPickerWidget);
registerComponent('address-field-widget', AddressFieldWidget);
registerComponent('bloomerp-text-editor', BloomerpTextEditor);

// Messages
registerComponent('ui-message', UiMessage);

// CRUD detail/create view
registerComponent('object-crud-view-container', ObjectCRUDViewContainer);
registerComponent('detail-view-value', DetailViewCell);
registerComponent('detail-tabs', DetailTabs);
registerComponent('detail-view-frame', DetailViewFrame);

// Workflow
registerComponent('workflow', Workflow);

// Global search
registerComponent('global-search-modal', GlobalSearch);
registerComponent('search-section', SearchSection);

// File browser
registerComponent('file-browser', FileBrowser);

// Workspace components
registerComponent('workspace-container', WorkspaceContainer);
registerComponent('workspace-tile', WorkspaceTile);

registerComponent('sql-query-editor', SqlQueryEditor);

registerComponent('workspace-tile-canvas', Canvas);
registerComponent('sidebar-item', SidebarItem)
registerComponent('focus-in', FocusIn)
registerComponent('shortcut-tooltip', ShortcutTooltip);
registerComponent('ordered-field-select', OrderedFieldSelect);

registerComponent('focus-on-form', FocusOnForm);
registerComponent('base-wizard', BaseWizard)

// Auto init comonents
setupComponentAutoInit();


// Realtime messages
initMessagesWebsocket();


// Setup animation listener
SetupAnimationListener()
