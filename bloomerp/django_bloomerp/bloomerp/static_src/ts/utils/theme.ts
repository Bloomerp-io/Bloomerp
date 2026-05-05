import { getLocalStorageValue, setLocalStorageValue } from './localStorage';

type ThemeMode = 'light' | 'dark';

const STORAGE_KEY = 'bloomerp-theme';

function getSystemTheme(): ThemeMode {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getStoredTheme(): ThemeMode | null {
    const stored = getLocalStorageValue<ThemeMode | null>(STORAGE_KEY, null);
    return stored === 'dark' || stored === 'light' ? stored : null;
}

function getActiveTheme(): ThemeMode {
    const current = document.documentElement.dataset.theme;
    return current === 'dark' ? 'dark' : 'light';
}

function updateToggleButtons(theme: ThemeMode): void {
    const nextLabel = theme === 'dark' ? 'Light mode' : 'Dark mode';

    document.querySelectorAll<HTMLElement>('[data-theme-toggle]').forEach((button) => {
        button.setAttribute('aria-pressed', String(theme === 'dark'));
    });

    document.querySelectorAll<HTMLElement>('[data-theme-toggle-label]').forEach((label) => {
        label.textContent = nextLabel;
    });
}

export function applyTheme(theme: ThemeMode): void {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    updateToggleButtons(theme);
    document.dispatchEvent(new CustomEvent('bloomerp:theme-change', { detail: theme }));
}

export function toggleTheme(): void {
    const nextTheme: ThemeMode = getActiveTheme() === 'dark' ? 'light' : 'dark';
    setLocalStorageValue(STORAGE_KEY, nextTheme);
    applyTheme(nextTheme);
}

export function initTheme(): void {
    const initialTheme = getStoredTheme() ?? getSystemTheme();
    applyTheme(initialTheme);

    document.addEventListener('click', (event) => {
        const target = event.target as HTMLElement | null;
        const toggle = target?.closest<HTMLElement>('[data-theme-toggle]');

        if (!toggle) return;

        event.preventDefault();
        toggleTheme();
    });

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', () => {
        if (getStoredTheme() !== null) return;
        applyTheme(getSystemTheme());
    });
}
