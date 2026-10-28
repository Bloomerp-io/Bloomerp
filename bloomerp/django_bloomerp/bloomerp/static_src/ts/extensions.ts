/** Load installed app entries before the shared component lifecycle starts. */
export async function loadFrontendExtensions(): Promise<void> {
    const configuration = document.getElementById('bloomerp-frontend-extensions');
    if (!configuration) return;
    const extensions: { script: string; client?: string }[] = JSON.parse(configuration.textContent || '[]');
    for (const extension of extensions) {
        try {
            if (extension.client) await import(/* @vite-ignore */ extension.client);
            await import(/* @vite-ignore */ extension.script);
        } catch (error) {
            console.error(`Could not load Bloomerp frontend extension ${extension.script}`, error);
        }
    }
}
