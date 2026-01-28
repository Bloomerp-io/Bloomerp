import BaseComponent, { registerComponent } from "../BaseComponent";
import { getContextMenu, type ContextMenuItem } from "../../utils/contextMenu";

export class DetailViewCell extends BaseComponent {
	public value: string | null = null;
	public label: string | null = null;
	public applicationFieldId: string | null = null;

	public initialize(): void {
		if (!this.element) return;

		// Extract data attributes
		this.value = this.element.getAttribute('data-value') ?? null;
		this.label = this.element.getAttribute('data-label') ?? null;
		this.applicationFieldId = this.element.getAttribute('data-application-field-id') ?? null;

		// Setup right-click context menu
		this.setupContextMenu();
	}

	public destroy(): void {
		if (!this.element) return;
		this.element.removeEventListener('contextmenu', this.onContextMenu, true);
	}

	private onContextMenu = (event: MouseEvent): void => {
		event.preventDefault();
		this.showContextMenu(event);
	};

	private setupContextMenu(): void {
		if (!this.element) return;
		this.element.addEventListener('contextmenu', this.onContextMenu, true);
	}

	private showContextMenu(event: MouseEvent): void {
		if (!this.element) return;

		const items = this.constructContextMenu();
		if (items.length === 0) return;

		getContextMenu().show(event, this.element, items);
	}

	public constructContextMenu(): ContextMenuItem[] {
		const items: ContextMenuItem[] = [];

		// Add copy value option
		if (this.value) {
			items.push({
				label: 'Copy Value',
				icon: 'fa-solid fa-copy',
				onClick: (context) => {
					this.copyValue();
					context.hide();
				},
			});
		}

		return items;
	}

	private copyValue(): void {
		if (!this.value) return;

		// Copy to clipboard
		navigator.clipboard.writeText(this.value).then(
			() => {
				console.log('Value copied to clipboard');
				// Optional: Show a toast notification
			},
			(err) => {
				console.error('Failed to copy value:', err);
			}
		);
	}

	/**
	 * Highlights the cell (for keyboard navigation)
	 */
	public highlight(): void {
		if (!this.element) return;
		this.element.classList.add('cell-focused');
	}

	/**
	 * Removes highlight from the cell
	 */
	public unhighlight(): void {
		if (!this.element) return;
		this.element.classList.remove('cell-focused');
	}
}

// Register the component
