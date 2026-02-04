export function getLocalStorageValue<T>(key: string, fallback: T): T {
    if (typeof window === "undefined" || !window.localStorage) {
        return fallback;
    }

    try {
        const raw = window.localStorage.getItem(key);
        if (raw === null) return fallback;
        return JSON.parse(raw) as T;
    } catch (error) {
        console.warn(`Failed to read localStorage key "${key}"`, error);
        return fallback;
    }
}

export function setLocalStorageValue<T>(key: string, value: T): void {
    if (typeof window === "undefined" || !window.localStorage) return;

    try {
        window.localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
        console.warn(`Failed to write localStorage key "${key}"`, error);
    }
}
