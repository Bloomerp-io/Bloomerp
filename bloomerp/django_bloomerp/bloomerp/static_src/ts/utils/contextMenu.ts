export type ContextMenuItem = {
	label: string;
	onClick: (context: ContextMenuContext) => void | Promise<void>;
	disabled?: boolean;
};

export type ContextMenuContext = {
	trigger: HTMLElement;
	event: MouseEvent;
	hide: () => void;
};

export type ContextMenuController = {
	element: HTMLDivElement;
	show: (event: MouseEvent, trigger: HTMLElement, items: ContextMenuItem[]) => void;
	hide: () => void;
	destroy: () => void;
};

const DEFAULT_MENU_CLASS =
	'fixed hidden bg-white shadow-lg rounded-lg border border-gray-200 z-50 min-w-[160px]';

const menuCache = new Map<string, ContextMenuController>();

function getOrCreateMenuElement(id: string): HTMLDivElement {
	const existing = document.getElementById(id);
	if (existing) return existing as HTMLDivElement;

	const menu = document.createElement('div');
	menu.id = id;
	menu.className = DEFAULT_MENU_CLASS;
	const ul = document.createElement('ul');
	ul.className = 'py-1';
	menu.appendChild(ul);
	document.body.appendChild(menu);
	return menu;
}

function clearMenu(menu: HTMLDivElement): HTMLUListElement {
	const ul = (menu.querySelector('ul') ?? document.createElement('ul')) as HTMLUListElement;
	if (!ul.isConnected) {
		ul.className = 'py-1';
		menu.appendChild(ul);
	}
	ul.replaceChildren();
	return ul;
}

function clampToViewport(x: number, y: number, menu: HTMLDivElement): { x: number; y: number } {
	const padding = 8;
	const rect = menu.getBoundingClientRect();
	const maxX = window.innerWidth - rect.width - padding;
	const maxY = window.innerHeight - rect.height - padding;

	return {
		x: Math.max(padding, Math.min(x, maxX)),
		y: Math.max(padding, Math.min(y, maxY)),
	};
}

export function getContextMenu(id = 'bloomerp-context-menu'): ContextMenuController {
	const existing = menuCache.get(id);
	if (existing) return existing;

	const element = getOrCreateMenuElement(id);
	const abortController = new AbortController();

	const hide = (): void => {
		element.classList.add('hidden');
	};

	// Hide on any click outside
	document.addEventListener(
		'click',
		(event: MouseEvent) => {
			if (element.classList.contains('hidden')) return;
			if (element.contains(event.target as Node)) return;
			hide();
		},
		{ signal: abortController.signal }
	);

	// Hide on escape
	document.addEventListener(
		'keydown',
		(event: KeyboardEvent) => {
			if (event.key !== 'Escape') return;
			hide();
		},
		{ signal: abortController.signal }
	);

	// Hide on scroll/resize to avoid "floating" menu
	window.addEventListener('scroll', hide, { signal: abortController.signal, capture: true });
	window.addEventListener('resize', hide, { signal: abortController.signal });

	const show = (event: MouseEvent, trigger: HTMLElement, items: ContextMenuItem[]): void => {
		// Populate
		const ul = clearMenu(element);

		const context: ContextMenuContext = {
			trigger,
			event,
			hide,
		};

		for (const item of items) {
			const li = document.createElement('li');
			const btn = document.createElement('button');
			btn.type = 'button';
			btn.className =
				'w-full text-left px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed';
			btn.textContent = item.label;
			if (item.disabled) btn.disabled = true;

			btn.addEventListener(
				'click',
				async (e) => {
					e.preventDefault();
					e.stopPropagation();
					await item.onClick(context);
					hide();
				},
				{ signal: abortController.signal }
			);

			li.appendChild(btn);
			ul.appendChild(li);
		}

		// Show and position
		element.classList.remove('hidden');

		// First place at cursor, then clamp based on measured size.
		element.style.left = `${event.clientX}px`;
		element.style.top = `${event.clientY}px`;

		const clamped = clampToViewport(event.clientX, event.clientY, element);
		element.style.left = `${clamped.x}px`;
		element.style.top = `${clamped.y}px`;
	};

	const destroy = (): void => {
		abortController.abort();
		menuCache.delete(id);
		if (element.parentElement) element.parentElement.removeChild(element);
	};

	const controller: ContextMenuController = { element, show, hide, destroy };
	menuCache.set(id, controller);
	return controller;
}

