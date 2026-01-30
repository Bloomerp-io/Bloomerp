import BaseComponent, { getComponent } from "../BaseComponent";
import { getContextMenu, type ContextMenuItem } from "../../utils/contextMenu";
import { DetailViewCell } from "./DetailViewCell";

type SectionInfo = {
	element: HTMLElement;
	columns: number;
	items: DetailViewCell[];
};

export default class ObjectDetailViewContainer extends BaseComponent {
	private keydownHandler: ((event: KeyboardEvent) => void) | null = null;
	private focusInHandler: ((event: FocusEvent) => void) | null = null;
	private currentItem: DetailViewCell | null = null;
	private sections: SectionInfo[] = [];

	public initialize(): void {
		if (!this.element) return;

		this.parseSections();
		this.applyTabIndexToItems();

		this.keydownHandler = (event: KeyboardEvent) => this.onKeyDown(event);
		this.element.addEventListener('keydown', this.keydownHandler);

		this.focusInHandler = (event: FocusEvent) => this.onFocusIn(event);
		this.element.addEventListener('focusin', this.focusInHandler);
	}

	public destroy(): void {
		if (!this.element) return;
		if (this.keydownHandler) {
			this.element.removeEventListener('keydown', this.keydownHandler);
		}
		if (this.focusInHandler) {
			this.element.removeEventListener('focusin', this.focusInHandler);
		}
		this.keydownHandler = null;
		this.focusInHandler = null;
		this.currentItem = null;
		this.sections = [];
	}

	public onAfterSwap(): void {
		this.parseSections();
		this.applyTabIndexToItems();
	}

	private parseSections(): void {
		if (!this.element) return;

		this.sections = [];
		const sectionElements = this.element.querySelectorAll<HTMLElement>('[data-section]');

		sectionElements.forEach((sectionEl) => {
			const columnsAttr = sectionEl.getAttribute('data-section-columns');
			const columns = columnsAttr ? parseInt(columnsAttr, 10) : 1;

			const items: DetailViewCell[] = [];
			const itemElements = sectionEl.querySelectorAll<HTMLElement>('[bloomerp-component="detail-view-value"]');

			itemElements.forEach((el) => {
				if (el.offsetParent === null) return;
				
				const component = getComponent(el);
				if (component instanceof DetailViewCell) {
					items.push(component);
				}
			});

			this.sections.push({
				element: sectionEl,
				columns,
				items,
			});
		});
	}

	private onFocusIn(event: FocusEvent): void {
		const target = event.target as HTMLElement | null;
		if (!target) return;
		const itemEl = target.closest<HTMLElement>(`[bloomerp-component="detail-view-value"]`);
		if (itemEl && this.element?.contains(itemEl)) {
			const component = getComponent(itemEl);
			if (component instanceof DetailViewCell) {
				this.currentItem = component;
			}
		}
	}

	private onKeyDown(event: KeyboardEvent): void {
		if (!this.element) return;

		const key = event.key;
		const isMeta = event.metaKey || event.ctrlKey;
		const isAlt = event.altKey;
		const isShift = event.shiftKey;

		// Shift+Arrow triggers navigation
		if (isShift && this.isArrowKey(key)) {
			event.preventDefault();

			const allItems = this.getAllItems();
			if (allItems.length === 0) return;

			if (!this.currentItem || !allItems.includes(this.currentItem)) {
				this.currentItem = allItems[0];
			}

			let next: DetailViewCell | null = null;

			if (isMeta) {
				// Cmd+Shift+arrow: move to edge within section
				next = this.getEdgeItem(key);
			} else {
				// Shift+arrow: move one step
				next = this.findNextItem(key);
			}

			if (!next) return;

			this.focusItem(next);
			this.currentItem = next;
			return;
		}

		// Option+Down triggers context menu
		if (isAlt && key === 'ArrowDown') {
			event.preventDefault();
			this.openContextMenu();
			return;
		}
	}

	private isArrowKey(key: string): boolean {
		return key === 'ArrowUp' || key === 'ArrowDown' || key === 'ArrowLeft' || key === 'ArrowRight';
	}

	private applyTabIndexToItems(): void {
		this.getAllItems().forEach((item) => {
			if (!item.element || item.element.hasAttribute('tabindex')) return;
			item.element.setAttribute('tabindex', '0');
		});
	}

	private focusItem(item: DetailViewCell): void {
		if (!item.element) return;
		
		// Focus the inner input element so it shows its native focus ring
		const focusTarget = this.getFocusableTarget(item.element);
		if (focusTarget) {
			focusTarget.focus();
		} else {
			// Fallback to cell container if no focusable element found
			item.element.focus();
		}

		// Unhighlight the previous item
		if (this.currentItem && this.currentItem !== item) {
			this.currentItem.unhighlight();
		}
		// Don't highlight the new item - let the native input focus ring show instead
	}

	private getFocusableTarget(itemElement: HTMLElement): HTMLElement | null {
		const focusable = itemElement.querySelector<HTMLElement>(
			'input, textarea, select, button, [contenteditable="true"], [tabindex]:not([tabindex="-1"])'
		);
		return focusable ?? null;
	}

	private getAllItems(): DetailViewCell[] {
		return this.sections.flatMap((section) => section.items);
	}

	private getCurrentPosition(): { section: SectionInfo; index: number } | null {
		if (!this.currentItem) return null;

		for (const section of this.sections) {
			const index = section.items.indexOf(this.currentItem);
			if (index !== -1) {
				return { section, index };
			}
		}

		return null;
	}

	private findNextItem(key: string): DetailViewCell | null {
		const pos = this.getCurrentPosition();
		if (!pos) return null;

		const { section, index } = pos;

		switch (key) {
			case 'ArrowLeft':
				return this.moveLeft(section, index);
			case 'ArrowRight':
				return this.moveRight(section, index);
			case 'ArrowUp':
				return this.moveUp(section, index);
			case 'ArrowDown':
				return this.moveDown(section, index);
			default:
				return null;
		}
	}

	private moveLeft(section: SectionInfo, index: number): DetailViewCell | null {
		const col = index % section.columns;

		if (col > 0) {
			// Can move left within the same row
			return section.items[index - 1] ?? null;
		}

		// Already at leftmost column, stay in place
		return null;
	}

	private moveRight(section: SectionInfo, index: number): DetailViewCell | null {
		const col = index % section.columns;

		if (col < section.columns - 1 && index + 1 < section.items.length) {
			// Can move right within the same row
			return section.items[index + 1] ?? null;
		}

		// Already at rightmost column or end of items, stay in place
		return null;
	}

	private moveUp(section: SectionInfo, index: number): DetailViewCell | null {
		const targetIndex = index - section.columns;

		if (targetIndex >= 0) {
			// Move up within the same section
			return section.items[targetIndex] ?? null;
		}

		// At top of section, move to last item of previous section
		const currentSectionIndex = this.sections.indexOf(section);
		if (currentSectionIndex > 0) {
			const prevSection = this.sections[currentSectionIndex - 1];
			return prevSection.items[prevSection.items.length - 1] ?? null;
		}

		// Already at first section, stay in place
		return null;
	}

	private moveDown(section: SectionInfo, index: number): DetailViewCell | null {
		const targetIndex = index + section.columns;

		if (targetIndex < section.items.length) {
			// Move down within the same section
			return section.items[targetIndex] ?? null;
		}

		// At bottom of section, move to first item of next section
		const currentSectionIndex = this.sections.indexOf(section);
		if (currentSectionIndex < this.sections.length - 1) {
			const nextSection = this.sections[currentSectionIndex + 1];
			return nextSection.items[0] ?? null;
		}

		// Already at last section, stay in place
		return null;
	}

	private getEdgeItem(key: string): DetailViewCell | null {
		const pos = this.getCurrentPosition();
		if (!pos) return null;

		const { section, index } = pos;

		switch (key) {
			case 'ArrowLeft':
				return this.getLeftmostItem(section, index);
			case 'ArrowRight':
				return this.getRightmostItem(section, index);
			case 'ArrowUp':
				return this.getTopmostItem(section, index);
			case 'ArrowDown':
				return this.getBottommostItem(section, index);
			default:
				return null;
		}
	}

	private getLeftmostItem(section: SectionInfo, index: number): DetailViewCell | null {
		const row = Math.floor(index / section.columns);
		const rowStartIndex = row * section.columns;
		return section.items[rowStartIndex] ?? null;
	}

	private getRightmostItem(section: SectionInfo, index: number): DetailViewCell | null {
		const row = Math.floor(index / section.columns);
		const rowStartIndex = row * section.columns;
		const rowEndIndex = Math.min(rowStartIndex + section.columns - 1, section.items.length - 1);
		return section.items[rowEndIndex] ?? null;
	}

	private getTopmostItem(section: SectionInfo, index: number): DetailViewCell | null {
		const col = index % section.columns;
		return section.items[col] ?? section.items[0] ?? null;
	}

	private getBottommostItem(section: SectionInfo, index: number): DetailViewCell | null {
		const col = index % section.columns;
		const totalRows = Math.ceil(section.items.length / section.columns);
		const lastRowStartIndex = (totalRows - 1) * section.columns;
		const targetIndex = lastRowStartIndex + col;

		if (targetIndex < section.items.length) {
			return section.items[targetIndex] ?? null;
		}

		// If the column doesn't exist in the last row, return the last item
		return section.items[section.items.length - 1] ?? null;
	}

	private openContextMenu(): void {
		if (!this.currentItem || !this.currentItem.element) return;

		const items = this.constructContextMenu();
		if (items.length === 0) {
			// If container has no menu, try the cell's menu
			this.currentItem.constructContextMenu();
			return;
		}

		const rect = this.currentItem.element.getBoundingClientRect();
		const clientX = Math.round(rect.left + Math.min(24, rect.width / 2));
		const clientY = Math.round(rect.bottom - 4);

		const synthetic = new MouseEvent('contextmenu', {
			bubbles: true,
			cancelable: true,
			clientX,
			clientY,
		});

		getContextMenu().show(synthetic, this.currentItem.element, items);
	}

	protected constructContextMenu(): ContextMenuItem[] {
		// Override in subclasses to provide context menu items
		return [];
	}
}
